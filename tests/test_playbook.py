"""🅱 M5 处置预案（知识库联动）测试。

覆盖：预案 CRUD、匹配优先级（项目×类型×级别）、步骤/链接 JSON 编解码、
推荐端点（按类型/按告警 ID）、以及系统预置 mock 预案存在性。

隔离约定：每用例用 uuid 唯一 alarm_type，finally 内同会话清理自建预案/告警。
"""

import secrets

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.data_scope import DataScope
from app.core.database import SessionLocal
from app.model.alarm import Alarm
from app.model.playbook import Playbook
from app.model.project import Project
from app.service import playbook_service as svc


def _uid() -> str:
    return secrets.token_hex(3)


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _first_pid(db) -> int:
    pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
    assert pid is not None, "需存在真实项目"
    return pid


# ---------------------------------------------------------------------------
# CRUD（API 层）
# ---------------------------------------------------------------------------


def test_playbook_crud(client: TestClient, admin_token: str):
    db = SessionLocal()
    created_id = None
    try:
        pid = _first_pid(db)
        # 创建（含步骤与知识库链接）
        r = client.post(
            "/api/v1/playbooks/",
            headers=_h(admin_token),
            json={
                "name": f"测试预案{_uid()}",
                "project_id": pid,
                "alarm_type": "fence_intrusion",
                "alarm_level": "严重",
                "summary": "现场核实并处置",
                "steps": ["1. 调阅视频", "2. 通知现场"],
                "references": [{"title": "安全细则", "url": "https://example.com/kb"}],
                "owner_role": "现场安全员",
                "est_minutes": 15,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == 0
        created_id = body["data"]["id"]
        assert body["data"]["project_name"]
        # 步骤/链接 JSON 已解码为列表
        assert body["data"]["steps"] == ["1. 调阅视频", "2. 通知现场"]
        assert body["data"]["references"][0]["title"] == "安全细则"

        # 列表 + 过滤
        r = client.get(
            "/api/v1/playbooks/",
            headers=_h(admin_token),
            params={"project_id": pid, "alarm_type": "fence_intrusion"},
        )
        assert r.json()["code"] == 0
        assert any(it["id"] == created_id for it in r.json()["data"]["items"])

        # meta
        r = client.get("/api/v1/playbooks/meta", headers=_h(admin_token))
        meta = r.json()["data"]
        assert {"key": "predictive_alert", "label": "预测预警"} in meta["alarm_types"]
        assert "严重" in meta["levels"]

        # 编辑：清除级别（空串） + 修改步骤
        r = client.put(
            f"/api/v1/playbooks/{created_id}",
            headers=_h(admin_token),
            json={"alarm_level": "", "steps": ["1. 仅一步"]},
        )
        data = r.json()["data"]
        assert data["alarm_level"] is None
        assert data["steps"] == ["1. 仅一步"]

        # 非法级别
        r = client.put(
            f"/api/v1/playbooks/{created_id}",
            headers=_h(admin_token),
            json={"alarm_level": "灾难"},
        )
        assert r.json()["code"] == 400

        # 删除（逻辑删除）
        r = client.delete(f"/api/v1/playbooks/{created_id}", headers=_h(admin_token))
        assert r.json()["data"]["deleted"] is True
        r = client.get(f"/api/v1/playbooks/{created_id}", headers=_h(admin_token))
        assert r.json()["code"] == 404
    finally:
        if created_id:
            db.execute(delete(Playbook).where(Playbook.id == created_id))
            db.commit()
        db.close()


# ---------------------------------------------------------------------------
# 匹配优先级（服务层）
# ---------------------------------------------------------------------------


def test_resolve_playbooks_precedence():
    db = SessionLocal()
    ids: list[int] = []
    try:
        pid = _first_pid(db)
        atype = f"t_{_uid()}"

        def _mk(name, project_id, alarm_type, alarm_level=None):
            p = Playbook(
                name=name,
                project_id=project_id,
                alarm_type=alarm_type,
                alarm_level=alarm_level,
                summary="x",
                steps="[]",
            )
            db.add(p)
            db.flush()
            ids.append(p.id)
            return p

        _mk("全局通配", None, None)  # 仅占位：验证更具体预案胜出时其不被置顶
        _mk("全局+类型", None, atype)
        g_type_level = _mk("全局+类型+级别", None, atype, "严重")
        p_all = _mk("项目通配", pid, None)
        p_type = _mk("项目+类型", pid, atype)
        p_type_level = _mk("项目+类型+级别", pid, atype, "严重")
        db.commit()

        scope = DataScope(is_all=True)
        # (项目, 类型, 严重) → 项目+类型+级别 优先
        res = svc.resolve_playbooks(db, scope, pid, atype, "严重", limit=10)
        assert res[0].id == p_type_level.id
        # (项目, 类型, None) → 项目+类型 优先（级别不限排在类型之后）
        res = svc.resolve_playbooks(db, scope, pid, atype, None, limit=10)
        assert res[0].id == p_type.id
        # (None, 类型, 严重) → 仅全局，按 类型+级别 优先
        res = svc.resolve_playbooks(db, scope, None, atype, "严重", limit=10)
        assert res[0].id == g_type_level.id
        # 类型不匹配时仅通用预案
        res = svc.resolve_playbooks(db, scope, pid, "other_type_x", None, limit=10)
        assert res[0].id == p_all.id
        # 禁用后不再命中
        p_type_level.enabled = False
        db.commit()
        res = svc.resolve_playbooks(db, scope, pid, atype, "严重", limit=10)
        assert res[0].id == p_type.id
    finally:
        db.execute(delete(Playbook).where(Playbook.id.in_(ids)))
        db.commit()
        db.close()


# ---------------------------------------------------------------------------
# 推荐端点（API 层）
# ---------------------------------------------------------------------------


def test_recommend_endpoint(client: TestClient, admin_token: str):
    db = SessionLocal()
    created_id = None
    alarm_id = None
    try:
        pid = _first_pid(db)
        atype = f"t_{_uid()}"
        # 建一条该类型的告警 + 一个通用预案
        alarm = Alarm(
            project_id=pid,
            alarm_type=atype,
            device_no=f"PB-{_uid()}",
            device_name="预案推荐测试",
            alarm_info="x",
            alarm_level="警告",
            handle_status="待处理",
        )
        db.add(alarm)
        db.commit()
        alarm_id = alarm.id

        r = client.post(
            "/api/v1/playbooks/",
            headers=_h(admin_token),
            json={
                "name": f"推荐预案{_uid()}",
                "project_id": None,
                "alarm_type": atype,
                "summary": "通用处置",
                "steps": ["1. 处置"],
            },
        )
        created_id = r.json()["data"]["id"]

        # 按类型推荐
        r = client.get(
            "/api/v1/playbooks/recommend",
            headers=_h(admin_token),
            params={"alarm_type": atype},
        )
        assert r.json()["code"] == 0
        assert any(it["id"] == created_id for it in r.json()["data"])

        # 按告警 ID 推荐
        r = client.get(
            f"/api/v1/playbooks/recommend-by-alarm/{alarm_id}",
            headers=_h(admin_token),
        )
        assert r.json()["code"] == 0
        assert any(it["id"] == created_id for it in r.json()["data"])
    finally:
        if alarm_id:
            db.execute(delete(Alarm).where(Alarm.id == alarm_id))
        if created_id:
            db.execute(delete(Playbook).where(Playbook.id == created_id))
        db.commit()
        db.close()


# ---------------------------------------------------------------------------
# 系统预置 mock 预案存在性（seed 已运行）
# ---------------------------------------------------------------------------


def test_seeded_playbooks_exist(client: TestClient, admin_token: str):
    r = client.get(
        "/api/v1/playbooks/",
        headers=_h(admin_token),
        params={"page": 1, "size": 100},
    )
    assert r.json()["code"] == 0
    names = {it["name"] for it in r.json()["data"]["items"]}
    # 6 类告警的预置预案应已存在
    for n in (
        "电子围栏侵入处置预案",
        "人机间距过近处置预案",
        "设备自报告警处置预案",
        "列车接近预警处置预案",
        "趋势异常处置预案",
        "预测性预警处置预案",
    ):
        assert n in names, f"缺少预置预案：{n}"
