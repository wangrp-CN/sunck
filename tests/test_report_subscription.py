"""定期订阅推送测试（模块①·报告与触达增强）。

覆盖：列表/创建/更新/删除、归属隔离(404)、手动触发生成+站内信触达、下载重生报告、
调度到期判定(is_due) 与 run_due_subscriptions 幂等。
"""

import secrets
from datetime import datetime

import pytest
from sqlalchemy import delete, select, text

from app.core.clock import LOCAL_TZ
from app.core.database import SessionLocal
from app.model.report_subscription import ReportSubscription
from app.model.system import Department, Role, User
from app.service import report_subscription as sub_svc


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _admin_id(db) -> int:
    """取真实 admin 用户 id（避免硬编码 1 触发外键违反）。"""
    uid = db.scalar(select(User.id).where(User.username == "admin"))
    assert uid is not None, "测试依赖 admin 用户存在"
    return uid


def _make_sub(db, user_id, **kw):
    defaults = dict(
        user_id=user_id,
        name="周报",
        fmt="excel",
        days=30,
        project_id=None,
        frequency="daily",
        send_hour=8,
        send_weekday=0,
        send_day=1,
        channels=["in_app"],
        enabled=True,
    )
    defaults.update(kw)
    sub = ReportSubscription(**defaults)
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def test_create_and_list(client, auth_headers):
    r = client.post(
        "/api/v1/subscriptions",
        headers=auth_headers,
        json={"name": "我的周报", "fmt": "pdf", "days": 30, "frequency": "weekly", "send_hour": 9},
    )
    assert r.status_code == 200, r.text
    sid = r.json()["data"]["id"]
    assert r.json()["data"]["frequency"] == "weekly"

    lst = client.get("/api/v1/subscriptions", headers=auth_headers)
    assert lst.status_code == 200
    ids = [x["id"] for x in lst.json()["data"]]
    assert sid in ids


def test_update_and_delete(client, auth_headers):
    c = client.post(
        "/api/v1/subscriptions",
        headers=auth_headers,
        json={"name": "待改", "days": 30},
    )
    sid = c.json()["data"]["id"]

    u = client.put(
        "/api/v1/subscriptions/" + str(sid),
        headers=auth_headers,
        json={"days": 60, "enabled": False},
    )
    assert u.status_code == 200, u.text
    assert u.json()["data"]["days"] == 60
    assert u.json()["data"]["enabled"] is False

    d = client.delete("/api/v1/subscriptions/" + str(sid), headers=auth_headers)
    assert d.status_code == 200
    lst = client.get("/api/v1/subscriptions", headers=auth_headers)
    assert sid not in [x["id"] for x in lst.json()["data"]]


def test_invalid_project_id_rejected(client, auth_headers):
    r = client.post(
        "/api/v1/subscriptions",
        headers=auth_headers,
        json={"name": "坏项目", "project_id": 999999},
    )
    # BusinessError 返回 HTTP 200 + body code=400（非 HTTP 400）
    assert r.json()["code"] == 400, r.text
    assert "聚焦项目不存在" in r.json()["message"]


def _make_viewer(client, admin_headers, u):
    """建一个拥有 dashboard:view 的普通用户，返回 (token, uname, dept_id, role_id)。"""
    dept = client.post(
        "/api/v1/departments",
        headers=admin_headers,
        json={"name": f"T{u}_dept", "code": f"T{u}_dept", "parent_id": None},
    ).json()["data"]
    role = client.post(
        "/api/v1/auth/roles",
        headers=admin_headers,
        json={"name": f"T{u}_role", "code": f"T{u}_role", "data_scope": 1, "remark": "test"},
    ).json()["data"]
    client.post(
        f"/api/v1/auth/roles/{role['id']}/permissions",
        headers=admin_headers,
        json={"permission_codes": ["dashboard:view"]},
    )
    uname = f"T{u}_viewer"
    reg = client.post(
        "/api/v1/auth/register",
        headers=admin_headers,
        json={
            "username": uname,
            "nickname": uname,
            "password": "Viewer@123456",
            "dept_id": dept["id"],
            "role_codes": [role["code"]],
            "status": True,
        },
    )
    assert reg.status_code == 200, reg.text
    lr = client.post("/api/v1/auth/login", json={"username": uname, "password": "Viewer@123456"})
    assert lr.status_code == 200, lr.text
    return lr.json()["data"]["access_token"], uname, dept["id"], role["id"]


def _cleanup_viewer(uname, dept_id, role_id):
    db = SessionLocal()
    try:
        # 删用户→级联删其订阅；再删角色与部门
        db.execute(delete(User).where(User.username == uname))
        db.execute(delete(Role).where(Role.id == role_id))
        db.execute(delete(Department).where(Department.id == dept_id))
        db.commit()
    finally:
        db.close()


def test_ownership_isolation(client, auth_headers):
    # 创建一条归属 admin 的订阅
    c = client.post(
        "/api/v1/subscriptions", headers=auth_headers, json={"name": "归属admin", "days": 30}
    )
    sid = c.json()["data"]["id"]

    u = secrets.token_hex(3)
    try:
        tok, uname, dept_id, role_id = _make_viewer(client, auth_headers, u)
        vh = {"Authorization": f"Bearer {tok}"}

        # 普通用户（有 dashboard:view）创建自己的订阅应成功
        mine = client.post(
            "/api/v1/subscriptions", headers=vh, json={"name": "viewer订阅", "days": 30}
        )
        assert mine.status_code == 200, mine.text
        my_id = mine.json()["data"]["id"]

        # 自己的列表不应包含 admin 的订阅（归属隔离）
        my_list = client.get("/api/v1/subscriptions", headers=vh).json()["data"]
        my_ids = [x["id"] for x in my_list]
        assert my_id in my_ids
        assert sid not in my_ids, "不应看到他人的订阅"

        # 下载 admin 的订阅 → BusinessError code=404（不泄露存在性）
        dl_other = client.get(f"/api/v1/subscriptions/{sid}/download", headers=vh)
        assert dl_other.json()["code"] == 404, dl_other.text

        # 自己的可下载
        dl_mine = client.get(f"/api/v1/subscriptions/{my_id}/download", headers=vh)
        assert dl_mine.status_code == 200
        assert dl_mine.content[:4] in (b"PK\x03\x04", b"%PDF")  # xlsx 或 pdf 魔数
    finally:
        _cleanup_viewer(uname, dept_id, role_id)


def test_trigger_generates_and_notifies(client, auth_headers):
    c = client.post(
        "/api/v1/subscriptions", headers=auth_headers, json={"name": "触发测试", "days": 30}
    )
    sid = c.json()["data"]["id"]

    # 触发前通知数
    before = client.get("/api/v1/notifications?page=1&size=1", headers=auth_headers).json()["data"][
        "total"
    ]

    t = client.post(f"/api/v1/subscriptions/{sid}/trigger", headers=auth_headers)
    assert t.status_code == 200, t.text
    assert t.json()["data"]["status"] == "ok"
    assert t.json()["data"]["bytes"] > 0

    after = client.get("/api/v1/notifications?page=1&size=1", headers=auth_headers).json()["data"][
        "total"
    ]
    assert after > before, "触发应下发一条站内信"


def test_download_reborn_report(client, auth_headers):
    c = client.post(
        "/api/v1/subscriptions",
        headers=auth_headers,
        json={"name": "下载测试", "fmt": "pdf", "days": 30},
    )
    sid = c.json()["data"]["id"]
    dl = client.get(f"/api/v1/subscriptions/{sid}/download", headers=auth_headers)
    assert dl.status_code == 200
    assert dl.content[:4] == b"%PDF"


# --- 调度判定（不依赖网络/DB 的纯逻辑，但需真实用户避免外键违反） ---
def test_is_due_logic(client):
    db = SessionLocal()
    try:
        uid = _admin_id(db)
        # 北京 08:10 应到点（send_hour 取北京时）
        now = datetime(2026, 7, 28, 8, 10, tzinfo=LOCAL_TZ)
        sub = _make_sub(db, user_id=uid, frequency="daily", send_hour=8, enabled=True)
        assert sub_svc.is_due(sub, now) is True
        # 标记已运行（本周期）
        sub.last_run_at = now
        db.commit()
        assert sub_svc.is_due(sub, now) is False, "本周期已运行不应重复"
        # 非发送时刻
        off = datetime(2026, 7, 28, 20, 10, tzinfo=LOCAL_TZ)
        assert sub_svc.is_due(sub, off) is False
        db.delete(sub)
        db.commit()
    finally:
        db.close()


def test_run_due_subscriptions_idempotent(client):
    db = SessionLocal()
    try:
        uid = _admin_id(db)
        now = datetime(2026, 7, 28, 8, 10, tzinfo=LOCAL_TZ)
        sub = _make_sub(db, user_id=uid, frequency="daily", send_hour=8, enabled=True)
        res = sub_svc.run_due_subscriptions(db, now)
        assert any(r["id"] == sub.id and r["status"] == "ok" for r in res)
        # 再跑一次：因已记录 last_run_at 本周期，不再触发
        res2 = sub_svc.run_due_subscriptions(db, now)
        assert not any(r["id"] == sub.id for r in res2)
        db.delete(sub)
        db.commit()
    finally:
        db.close()


def test_project_scoped_subscription_scope():
    """聚焦项目的订阅，run_one 按订阅人自身数据范围生成报告并触达（不越权）。"""
    db = SessionLocal()
    try:
        uid = _admin_id(db)
        # project_id 仅作报告标题标签，模型无外键，任意值即可验证流程
        sub = _make_sub(db, user_id=uid, project_id=999999, days=30)
        n0 = db.scalar(text("SELECT count(*) FROM notification"))
        summary = sub_svc.run_one(db, sub, datetime.now(LOCAL_TZ))
        db.commit()
        assert summary["status"] == "ok"
        n1 = db.scalar(text("SELECT count(*) FROM notification"))
        assert n1 > n0, "run_one 应下发一条站内信"
        db.delete(sub)
        db.commit()
    finally:
        db.close()
