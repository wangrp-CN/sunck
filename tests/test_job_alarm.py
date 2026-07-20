"""作业计划 + 告警管理 测试（阶段3）。

覆盖：
- 作业计划：管理员完整增删改查（含绑定展开、软删后 404）。
- 作业计划：无 job:add 权限用户创建被 403 拦截。
- 作业计划：数据范围隔离（本部门及以下 scope=3 仅见本部门项目下的作业）。
- 告警：列表过滤、alarm_level 字段、处置状态流转、配置 GET/PUT。

通过 TestClient 以真实库运行；按 uid 前缀清理自建数据，避免污染开发库。
"""

import secrets
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
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


def _make_role(client, admin_token, u, code, perms, data_scope=3, dept_ids=None):
    role_code = f"T{u}_{code}"
    body = {"name": role_code, "code": role_code, "data_scope": data_scope, "remark": "test"}
    if dept_ids is not None:
        body["dept_ids"] = dept_ids
    role = client.post("/api/v1/auth/roles", headers=_headers(admin_token), json=body).json()[
        "data"
    ]
    client.post(
        f"/api/v1/auth/roles/{role['id']}/permissions",
        headers=_headers(admin_token),
        json={"permission_codes": perms},
    )
    return role


def _make_user(client, admin_token, u, username, role_code, dept_id):
    pw = "Test@123456"
    client.post(
        "/api/v1/auth/register",
        headers=_headers(admin_token),
        json={
            "username": username,
            "password": pw,
            "dept_id": dept_id,
            "role_codes": [role_code],
            "status": True,
        },
    )
    r = client.post("/api/v1/auth/login", json={"username": username, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


# ---------------------------------------------------------------------------
# 作业计划
# ---------------------------------------------------------------------------


def test_job_full_crud_by_admin(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_项目", "dept_id": dept["id"], "status": "在建"},
        ).json()["data"]

        # 1) 创建（含规则）
        r = client.post(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"J{u}_作业",
                "is_start": True,
                "status": "执行中",
                "plan_time": "2026-07-14~2026-07-20",
                "rule": {
                    "monitor_target": "人员",
                    "trigger_condition": "进入围栏",
                    "time_range": "08:00-18:00",
                    "dwell_time": 60,
                },
            },
        )
        assert r.status_code == 200, r.text
        jid = r.json()["data"]["id"]
        assert r.json()["data"]["name"] == f"J{u}_作业"

        # 2) 列表
        r = client.get(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            params={"keyword": f"J{u}"},
        )
        assert r.status_code == 200, r.text
        ids = {it["id"] for it in r.json()["data"]["items"]}
        assert jid in ids

        # 3) 详情（规则解析）
        r = client.get(f"/api/v1/jobs/{jid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        assert r.json()["data"]["rule"]["monitor_target"] == "人员"
        assert r.json()["data"]["rule"]["dwell_time"] == 60

        # 4) 更新
        r = client.put(
            f"/api/v1/jobs/{jid}",
            headers=_headers(admin_token),
            json={"name": f"J{u}_作业改", "status": "已完成"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "已完成"

        # 5) 软删后详情 404
        r = client.delete(f"/api/v1/jobs/{jid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        r = client.get(f"/api/v1/jobs/{jid}", headers=_headers(admin_token))
        assert r.status_code == 404
    finally:
        _cleanup(u)


def test_job_bindings_expanded(client, admin_token):
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
            json={
                "project_id": proj["id"],
                "person_no": f"PN{u}",
                "name": f"P{u}_人",
            },
        ).json()["data"]
        _device = client.post(
            "/api/v1/devices",
            headers=_headers(admin_token),
            json={
                "device_type": "locate",
                "project_id": proj["id"],
                "name": f"D{u}_设备",
                "device_no": f"DN{u}",
            },
        ).json()["data"]
        fence = client.post(
            "/api/v1/fences",
            headers=_headers(admin_token),
            json={"project_id": proj["id"], "name": f"F{u}_围栏"},
        ).json()["data"]

        r = client.post(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"J{u}_绑定",
                "person_ids": [person["id"]],
                "device_bindings": [{"device_type": "locate", "device_no": f"DN{u}"}],
                "fence_ids": [fence["id"]],
            },
        )
        assert r.status_code == 200, r.text
        jid = r.json()["data"]["id"]

        r = client.get(f"/api/v1/jobs/{jid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert [p["id"] for p in d["persons"]] == [person["id"]]
        assert [(x["device_type"], x["device_no"]) for x in d["devices"]] == [("locate", f"DN{u}")]
        assert [f["id"] for f in d["fences"]] == [fence["id"]]
    finally:
        _cleanup(u)


def test_job_create_requires_permission(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        role = _make_role(client, admin_token, u, "READER", ["job:list"])
        tok = _make_user(client, admin_token, u, f"T{u}_reader", role["code"], dept["id"])
        r = client.post(
            "/api/v1/jobs",
            headers=_headers(tok),
            json={"name": f"J{u}_无权限"},
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(u)


def test_job_data_isolation_by_dept(client, admin_token):
    u = _uid()
    try:
        dept_a = _make_dept(client, admin_token, u, "A")
        dept_b = _make_dept(client, admin_token, u, "B")
        proj_a = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_A", "dept_id": dept_a["id"]},
        ).json()["data"]
        proj_b = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_B", "dept_id": dept_b["id"]},
        ).json()["data"]

        role = _make_role(
            client,
            admin_token,
            u,
            "PM",
            ["job:list", "job:add", "job:edit", "job:delete"],
            data_scope=3,
        )
        tok = _make_user(client, admin_token, u, f"T{u}_pm", role["code"], dept_a["id"])

        ja = client.post(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            json={"project_id": proj_a["id"], "name": f"J{u}_A"},
        ).json()["data"]
        jb = client.post(
            "/api/v1/jobs",
            headers=_headers(admin_token),
            json={"project_id": proj_b["id"], "name": f"J{u}_B"},
        ).json()["data"]

        r = client.get("/api/v1/jobs", headers=_headers(tok))
        assert r.status_code == 200, r.text
        ids = {it["id"] for it in r.json()["data"]["items"]}
        assert ja["id"] in ids
        assert jb["id"] not in ids

        # 越权详情 → 404
        r = client.get(f"/api/v1/jobs/{jb['id']}", headers=_headers(tok))
        assert r.status_code == 404
    finally:
        _cleanup(u)


# ---------------------------------------------------------------------------
# 告警管理
# ---------------------------------------------------------------------------


def _make_alarm(db, project_id, u) -> int:
    a = Alarm(
        project_id=project_id,
        alarm_type="fence_intrusion",
        device_type="locate",
        device_name="测试设备",
        device_no=f"DN{u}",
        alarm_info=f"AL{u}",
        alarm_status="告警开始",
        alarm_level="严重",
        handle_status="待处理",
        alarm_time=datetime.now(timezone.utc),
    )
    db.add(a)
    db.flush()
    return a.id


def test_alarm_list_filter_and_level(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_项目", "dept_id": dept["id"]},
        ).json()["data"]

        db = SessionLocal()
        try:
            aid = _make_alarm(db, proj["id"], u)
            db.commit()
        finally:
            db.close()

        # 按类型过滤
        r = client.get(
            "/api/v1/alarms",
            headers=_headers(admin_token),
            params={"alarm_type": "fence_intrusion"},
        )
        assert r.status_code == 200, r.text
        items = r.json()["data"]["items"]
        found = [a for a in items if a["id"] == aid]
        assert found, "告警未出现在列表"
        assert found[0]["alarm_level"] == "严重"
        assert found[0]["media_urls"] == []

        # 处置 → 已消警
        r = client.post(
            f"/api/v1/alarms/{aid}/handle",
            headers=_headers(admin_token),
            json={"handle_status": "已消警", "content": "已处理"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["handle_status"] == "已消警"
        assert r.json()["data"]["alarm_status"] == "已消警"
    finally:
        _cleanup(u)


def test_alarm_config_get_and_update(client, admin_token):
    u = _uid()
    try:
        # GET 配置
        r = client.get("/api/v1/alarms/config", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        assert "distance_machine" in r.json()["data"]

        # PUT 配置
        r = client.put(
            "/api/v1/alarms/config",
            headers=_headers(admin_token),
            json={"distance_machine": 123},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["distance_machine"] == 123

        # 还原，避免污染
        r = client.put(
            "/api/v1/alarms/config",
            headers=_headers(admin_token),
            json={"distance_machine": 50},
        )
        assert r.status_code == 200, r.text
    finally:
        _cleanup(u)
