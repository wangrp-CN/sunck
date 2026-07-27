"""根因派单闭环（#80）测试。

覆盖：从共因事件组创建派单（根因/级别自动带入）、站内信通知、列表/详情、
状态机流转（待派→处理中→已闭环，非法动作报错）、改派、统计。
使用 admin（超管，数据范围=全部），测试前后清理自建数据。
"""

import secrets
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.model.correlation import CorrelatedEventGroup
from app.model.dispatch import DispatchOrder
from app.model.notification import Notification
from app.model.project import Project
from app.model.system import User


def _uid() -> str:
    return secrets.token_hex(3)


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def env(client: TestClient, admin_token: str):
    db = SessionLocal()
    try:
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
        assert pid is not None, "需存在真实项目"
        now = datetime.now(timezone.utc)
        grp = CorrelatedEventGroup(
            project_id=pid,
            project_name="P",
            spatial_type="fence",
            scope_key="f",
            fence_name="F",
            started_at=now,
            alarm_count=2,
            device_count=2,
            is_cross_device=True,
            max_level="严重",
            root_cause_hint="多设备同围栏侵入",
            computed_at=now,
        )
        db.add(grp)
        db.flush()
        gid = grp.id
        u = _uid()
        r = client.post(
            "/api/v1/auth/register",
            headers=_h(admin_token),
            json={
                "username": f"DISP{u}",
                "password": "Test@123456",
                "role_codes": ["operator"],
                "status": True,
            },
        )
        assert r.status_code == 200, r.text
        assignee_id = r.json()["data"]["id"]
        db.commit()
    finally:
        db.close()
    yield {
        "pid": pid,
        "gid": gid,
        "assignee_id": assignee_id,
        "admin_token": admin_token,
        "client": client,
    }
    # 清理
    db = SessionLocal()
    try:
        db.execute(delete(DispatchOrder))
        db.execute(delete(User).where(User.username.like("DISP%")))
        db.execute(delete(CorrelatedEventGroup).where(CorrelatedEventGroup.id == gid))
        db.commit()
    finally:
        db.close()


def test_dispatch_create_and_flow(env):
    c = env["client"]
    h = _h(env["admin_token"])
    gid, aid, pid = env["gid"], env["assignee_id"], env["pid"]

    # 1) 从共因事件组创建派单：根因/级别自动带入
    r = c.post(
        "/api/v1/dispatch/",
        headers=h,
        json={
            "title": "处理围栏侵入",
            "source_type": "correlation",
            "source_id": gid,
            "assignee_id": aid,
            "project_id": pid,
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "待派"
    assert d["assignee_id"] == aid
    assert d["root_cause_hint"] == "多设备同围栏侵入"
    assert d["level"] == "严重"
    oid = d["id"]

    # 2) 处理人收到站内信
    db = SessionLocal()
    try:
        n = db.scalars(
            select(Notification).where(
                Notification.user_id == aid, Notification.category == "dispatch"
            )
        ).first()
        assert n is not None
    finally:
        db.close()

    # 3) 列表包含
    rl = c.get("/api/v1/dispatch/", headers=h)
    assert rl.status_code == 200
    assert any(it["id"] == oid for it in rl.json()["data"]["items"])

    # 4) 详情
    rd = c.get(f"/api/v1/dispatch/{oid}", headers=h)
    assert rd.status_code == 200 and rd.json()["data"]["id"] == oid

    # 5) 状态机：待派 → 处理中 → 已闭环
    r2 = c.patch(f"/api/v1/dispatch/{oid}", headers=h, json={"action": "start"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["status"] == "处理中"
    r3 = c.patch(f"/api/v1/dispatch/{oid}", headers=h, json={"action": "close", "note": "已处置"})
    assert r3.status_code == 200
    assert r3.json()["data"]["status"] == "已闭环"
    assert r3.json()["data"]["closed_at"] is not None

    # 6) 已闭环再执行 start 非法 → BusinessError（HTTP 200, code!=0）
    r4 = c.patch(f"/api/v1/dispatch/{oid}", headers=h, json={"action": "start"})
    assert r4.status_code == 200 and r4.json()["code"] != 0

    # 7) 统计：已闭环计数 >= 1
    rs = c.get("/api/v1/dispatch/stats", headers=h)
    assert rs.status_code == 200
    assert rs.json()["data"]["by_status"].get("已闭环", 0) >= 1


def test_dispatch_reassign(env):
    c = env["client"]
    h = _h(env["admin_token"])
    aid, pid = env["assignee_id"], env["pid"]

    r = c.post(
        "/api/v1/dispatch/",
        headers=h,
        json={"title": "手工单", "source_type": "manual", "project_id": pid, "assignee_id": aid},
    )
    assert r.status_code == 200, r.text
    oid = r.json()["data"]["id"]

    u2 = _uid()
    r2 = c.post(
        "/api/v1/auth/register",
        headers=h,
        json={
            "username": f"DISP{u2}",
            "password": "Test@123456",
            "role_codes": ["operator"],
            "status": True,
        },
    )
    assert r2.status_code == 200, r2.text
    aid2 = r2.json()["data"]["id"]

    rr = c.post(
        f"/api/v1/dispatch/{oid}/reassign", headers=h, json={"assignee_id": aid2, "note": "转派"}
    )
    assert rr.status_code == 200, rr.text
    assert rr.json()["data"]["assignee_id"] == aid2

    # 新处理人收到改派站内信
    db = SessionLocal()
    try:
        n = db.scalars(
            select(Notification).where(
                Notification.user_id == aid2, Notification.category == "dispatch"
            )
        ).first()
        assert n is not None
        db.execute(delete(User).where(User.id == aid2))
        db.commit()
    finally:
        db.close()


def test_dispatch_requires_auth(env):
    c = env["client"]
    r = c.post(
        "/api/v1/dispatch/",
        json={"title": "t", "source_type": "manual", "project_id": env["pid"]},
    )
    assert r.status_code in (401, 403)


def test_dispatch_invalid_project_id_rejected(env):
    """截图问题修复：人工建单传不存在的 project_id → 优雅 BusinessError(400)，不再 500。

    旧版缺少存在性校验，PG ``fk_dispatch_order_project_id_project`` 外键违反 → 500。
    修复后：service 在 INSERT 前显式 ``select Project by id``，不存在/已删除则抛
    ``BusinessError(code=400)``，前端展示可读提示。
    """
    c = env["client"]
    h = _h(env["admin_token"])
    # project_id=1 不存在（项目 ID 实际从 68 起步）
    r = c.post(
        "/api/v1/dispatch/",
        headers=h,
        json={
            "title": "测试派单",
            "source_type": "manual",
            "project_id": 1,
            "level": "提示",
            "root_cause_hint": "测试根因",
            "deadline": "2026-07-28T23:59:59",
            "description": "测试要求",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 400, f"应抛 code=400 BusinessError，实际 {body}"
    assert "归属项目不存在" in body.get("message", "")
