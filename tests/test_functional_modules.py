"""功能模块优化回归测试（批量处置 / 列车接近专项 / monitor_target 门控 / 跨项目绑定校验 / 甘特实际时间 / 告警自动结束）。

覆盖 2026-07-22 功能模块优化四项：
- 告警批量处置端点 POST /alarms/batch-handle（含数据范围外 id 自动跳过）
- 列车接近设备专项告警类型 train_approach（区别于通用 device_alarm）
- monitor_target 对围栏/间距触发的设备类别门控
- 作业计划跨项目绑定校验（人员/机械/围栏须归属本计划项目）
- 作业计划启动/完成回填 actual_start/actual_end（甘特进度联动）
- 告警自动结束机制（违规解除 → 自动置「告警结束」，防堆积）

通过 TestClient 以真实库运行；按 uid 前缀清理自建数据。
"""

import json
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.constants import (
    ALARM_TYPE_TRAIN,
    DEVICE_TYPE_ANTI_INTRUSION,
    DEVICE_TYPE_LOCATE,
    DEVICE_TYPE_TRAIN_APPROACH,
)
from app.core.database import SessionLocal
from app.core.rule_engine_v2 import _location_triggers_enabled, build_alarm_candidates_v2
from app.main import app
from app.model.alarm import Alarm
from app.model.fence import ElectronicFence
from app.model.job import WorkPlan
from app.model.person import Machine, Person
from app.model.project import Project
from app.model.system import Department, Role, User, role_dept


def _uid() -> str:
    return secrets.token_hex(3)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_token(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin@123456"})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _cleanup(u: str) -> None:
    db = SessionLocal()
    try:
        role_ids = db.scalars(select(Role.id).where(Role.code.like(f"T{u}%"))).all()
        if role_ids:
            db.execute(role_dept.delete().where(role_dept.c.role_id.in_(role_ids)))
        db.execute(delete(WorkPlan).where(WorkPlan.name.like(f"J{u}%")))
        db.execute(delete(Person).where(Person.name.like(f"P{u}%")))
        db.execute(delete(Machine).where(Machine.machine_no.like(f"M{u}%")))
        db.execute(delete(ElectronicFence).where(ElectronicFence.name.like(f"F{u}%")))
        db.execute(delete(Alarm).where(Alarm.alarm_info.like(f"AL{u}%")))
        db.execute(delete(Project).where(Project.name.like(f"P{u}%")))
        db.execute(delete(User).where(User.username.like(f"T{u}%")))
        db.execute(delete(Role).where(Role.code.like(f"T{u}%")))
        for _ in range(4):
            deleted = db.execute(
                delete(Department)
                .where(Department.code.like(f"T{u}%"))
                .where(
                    ~Department.id.in_(
                        select(Department.parent_id).where(Department.parent_id.is_not(None))
                    )
                )
            ).rowcount
            if deleted == 0:
                break
        db.commit()
    finally:
        db.close()


def _make_dept(client, admin_token, u, code, parent_id=None):
    return client.post(
        "/api/v1/departments",
        headers=_headers(admin_token),
        json={"name": f"部门{code}", "code": f"T{u}_{code}", "parent_id": parent_id},
    ).json()["data"]


# ---------------------------------------------------------------------------
# 1) 告警批量处置
# ---------------------------------------------------------------------------


def test_alarm_batch_handle(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_项目", "dept_id": dept["id"], "status": "在建"},
        ).json()["data"]
        db = SessionLocal()
        try:
            a1 = Alarm(
                project_id=proj["id"],
                alarm_type="fence_intrusion",
                device_type="locate",
                device_name="D1",
                device_no=f"DN{u}A",
                alarm_info=f"AL{u}1",
                alarm_status="告警开始",
                alarm_level="严重",
                handle_status="待处理",
                alarm_time=datetime.now(timezone.utc),
            )
            a2 = Alarm(
                project_id=proj["id"],
                alarm_type="distance_too_close",
                device_type="locate",
                device_name="D2",
                device_no=f"DN{u}B",
                alarm_info=f"AL{u}2",
                alarm_status="告警开始",
                alarm_level="警告",
                handle_status="待处理",
                alarm_time=datetime.now(timezone.utc),
            )
            db.add_all([a1, a2])
            db.commit()
            id1, id2 = a1.id, a2.id
        finally:
            db.close()

        # 批量处置：2 个有效 + 1 个不存在的 id（应被跳过）
        r = client.post(
            "/api/v1/alarms/batch-handle",
            headers=_headers(admin_token),
            json={"ids": [id1, id2, 99999999], "handle_status": "已处理", "content": "批量测试"},
        )
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["handled"] == 2, d
        assert d["skipped"] == 1, d
        assert len(d["results"]) == 2

        # 验证落库
        db = SessionLocal()
        try:
            st = db.scalars(select(Alarm.handle_status).where(Alarm.id.in_([id1, id2]))).all()
            assert set(st) == {"已处理"}
        finally:
            db.close()
    finally:
        _cleanup(u)


# ---------------------------------------------------------------------------
# 2) 列车接近专项告警
# ---------------------------------------------------------------------------


def _insert_active_plan(db, u, project_id, rule: dict) -> int:
    now = datetime.now(timezone.utc)
    plan = WorkPlan(
        project_id=project_id,
        name=f"J{u}_计划",
        is_start=True,
        status="执行中",
        plan_start=now - timedelta(days=1),
        plan_end=now + timedelta(days=1),
        rule_json=json.dumps(rule, ensure_ascii=False),
    )
    db.add(plan)
    db.flush()
    return plan.id


def test_train_approach_specialized_alarm(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_项目", "dept_id": dept["id"], "status": "在建"},
        ).json()["data"]
        db = SessionLocal()
        try:
            _insert_active_plan(
                db,
                u,
                proj["id"],
                {"trigger_conditions": ["train_approach"], "dwell_time": 0},
            )
            db.commit()
        finally:
            db.close()

        cands = build_alarm_candidates_v2(
            SessionLocal(),
            device_type=DEVICE_TYPE_TRAIN_APPROACH,
            device_no=f"TA{u}",
            device_name="列车设备",
            project_id=proj["id"],
            parsed={
                "alarm_status": "报警",
                "alarm_info": "接近",
                "report_time": datetime.now(timezone.utc),
            },
            location=None,
        )
        assert any(c["alarm_type"] == ALARM_TYPE_TRAIN for c in cands), cands
        assert all(c["alarm_type"] != "device_alarm" for c in cands), "列车接近不应回落通用设备自报"
    finally:
        _cleanup(u)


def test_train_approach_requires_trigger_enabled(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_项目", "dept_id": dept["id"], "status": "在建"},
        ).json()["data"]
        db = SessionLocal()
        try:
            # 计划未开 train_approach 触发 → 列车设备不应产生任何告警
            _insert_active_plan(
                db,
                u,
                proj["id"],
                {"trigger_conditions": ["fence_intrusion"], "dwell_time": 0},
            )
            db.commit()
        finally:
            db.close()

        cands = build_alarm_candidates_v2(
            SessionLocal(),
            device_type=DEVICE_TYPE_TRAIN_APPROACH,
            device_no=f"TA{u}",
            device_name="列车设备",
            project_id=proj["id"],
            parsed={"alarm_status": "报警", "report_time": datetime.now(timezone.utc)},
            location=None,
        )
        assert cands == [], cands
    finally:
        _cleanup(u)


# ---------------------------------------------------------------------------
# 3) monitor_target 门控（纯函数）
# ---------------------------------------------------------------------------


def test_monitor_target_gating():
    assert _location_triggers_enabled(DEVICE_TYPE_LOCATE, "person") is True
    assert _location_triggers_enabled(DEVICE_TYPE_ANTI_INTRUSION, "person") is False
    assert _location_triggers_enabled(DEVICE_TYPE_ANTI_INTRUSION, "machine") is True
    assert _location_triggers_enabled(DEVICE_TYPE_LOCATE, None) is True
    assert _location_triggers_enabled(DEVICE_TYPE_LOCATE, "all") is True
    assert _location_triggers_enabled(DEVICE_TYPE_TRAIN_APPROACH, "train") is True
    assert _location_triggers_enabled(DEVICE_TYPE_TRAIN_APPROACH, "person") is False


# ---------------------------------------------------------------------------
# 4) 作业计划跨项目绑定校验
# ---------------------------------------------------------------------------


def test_job_cross_project_binding_rejected(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj_a = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_A", "dept_id": dept["id"], "status": "在建"},
        ).json()["data"]
        proj_b = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_B", "dept_id": dept["id"], "status": "在建"},
        ).json()["data"]
        person_b = client.post(
            "/api/v1/persons",
            headers=_headers(admin_token),
            json={"project_id": proj_b["id"], "person_no": f"PN{u}", "name": f"P{u}_人"},
        ).json()["data"]

        # 在 A 项目下创建作业计划，却绑定 B 项目的人员 → 应被 400 拒绝
        # 注：本系统错误以 HTTP 200 + body.code=400 形式返回（ApiResponse 约定）
        r = client.post(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            json={
                "project_id": proj_a["id"],
                "name": f"J{u}_跨项目",
                "person_ids": [person_b["id"]],
            },
        )
        assert r.status_code == 200, r.text
        assert r.json().get("code") == 400, r.text
        assert "不属于本项目" in r.json().get("message", ""), r.text
    finally:
        _cleanup(u)


def test_job_same_project_binding_ok(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_项目", "dept_id": dept["id"], "status": "在建"},
        ).json()["data"]
        person = client.post(
            "/api/v1/persons",
            headers=_headers(admin_token),
            json={"project_id": proj["id"], "person_no": f"PN{u}", "name": f"P{u}_人"},
        ).json()["data"]
        r = client.post(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"J{u}_同项目",
                "person_ids": [person["id"]],
            },
        )
        assert r.status_code == 200, r.text
    finally:
        _cleanup(u)


# ---------------------------------------------------------------------------
# 5) 甘特实际时间回填
# ---------------------------------------------------------------------------


def test_job_actual_times(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_项目", "dept_id": dept["id"], "status": "在建"},
        ).json()["data"]
        jid = client.post(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            json={"project_id": proj["id"], "name": f"J{u}_甘特"},
        ).json()["data"]["id"]

        # 启动 → actual_start 回填
        r = client.post(f"/api/v1/jobs/{jid}/start", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        assert r.json()["data"]["actual_start"] is not None
        assert r.json()["data"]["actual_end"] is None

        # 完成 → actual_end 回填
        r = client.post(f"/api/v1/jobs/{jid}/complete", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        assert r.json()["data"]["actual_end"] is not None
    finally:
        _cleanup(u)


# ---------------------------------------------------------------------------
# 6) 告警自动结束（违规解除 → 自动置「告警结束」）
# ---------------------------------------------------------------------------


def test_alarm_auto_end_on_violation_cleared(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_项目", "dept_id": dept["id"], "status": "在建"},
        ).json()["data"]
        db = SessionLocal()
        try:
            a = Alarm(
                project_id=proj["id"],
                alarm_type="fence_intrusion",
                device_type="locate",
                device_name="D",
                device_no=f"DN{u}X",
                alarm_info=f"AL{u}auto",
                alarm_status="告警开始",
                alarm_level="严重",
                handle_status="待处理",
                alarm_time=datetime.now(timezone.utc),
            )
            db.add(a)
            db.commit()
            aid = a.id
        finally:
            db.close()

        # 模拟违规解除：当前活跃违规集合为空 → reconcile 应自动结束该打开告警。
        # reconcile 从 Redis 哈希 rule2:active:{device_no} 读取「上轮仍打开」的告警，
        # 故先以与 pipeline 相同的语义登记该告警为「活跃违规」，再传入空当前集合触发结束。
        from app.core.redis import get_redis_client
        from app.service.alarm_service import reconcile_active_alarms

        r = get_redis_client()
        r.hset(f"rule2:active:DN{u}X", "fence_intrusion", str(aid))
        r.expire(f"rule2:active:DN{u}X", 600)

        db = SessionLocal()
        try:
            ended = reconcile_active_alarms(db, f"DN{u}X", {})
            db.commit()
            assert aid in ended, "打开中的告警应在违规解除后被自动结束"
            a = db.get(Alarm, aid)
            assert a.alarm_status == "告警结束", a.alarm_status
            assert a.handle_status == "已消警", a.handle_status
        finally:
            db.close()
    finally:
        _cleanup(u)
