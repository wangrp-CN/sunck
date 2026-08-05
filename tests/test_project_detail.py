"""项目详情大屏 endpoint 端到端测试。

验证：
- 超管可见项目详情，返回结构含 project/devices/fences/persons/machines/alarms；
- machines 经作业计划机械绑定补充 guard_person_name / lng / lat / track_device_no；
- 数据范围隔离：scope 受限用户看不到他人部门项目（BusinessError 404）。
"""

import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.main import app
from app.model.device import AntiIntrusionDevice
from app.model.job import WorkPlan
from app.model.person import Machine, Person
from app.model.project import Project
from app.model.system import Department


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
        db.execute(delete(WorkPlan).where(WorkPlan.name.like(f"J{u}%")))
        db.execute(delete(AntiIntrusionDevice).where(AntiIntrusionDevice.device_no.like(f"{u}%")))
        db.execute(delete(Machine).where(Machine.machine_no.like(f"M{u}%")))
        db.execute(delete(Person).where(Person.name.like(f"P{u}%")))
        db.execute(delete(Project).where(Project.name.like(f"P{u}%")))
        db.execute(delete(Department).where(Department.code.like(f"T{u}%")))
        db.commit()
    finally:
        db.close()


def _build(client, token, u):
    """建部门/项目/防护人员/前臂定位设备(含坐标)/大机/作业计划(绑定大机+防护+前臂)。"""
    dept = client.post(
        "/api/v1/departments",
        headers=_headers(token),
        json={"name": f"部门{u}", "code": f"T{u}_A", "parent_id": None},
    ).json()["data"]
    proj = client.post(
        "/api/v1/projects",
        headers=_headers(token),
        json={"name": f"P{u}_项目", "dept_id": dept["id"], "status": "在建"},
    ).json()["data"]
    guard = client.post(
        "/api/v1/persons",
        headers=_headers(token),
        json={"project_id": proj["id"], "person_no": f"PN{u}", "name": f"P{u}_防护"},
    ).json()["data"]
    arm = client.post(
        "/api/v1/devices",
        headers=_headers(token),
        json={
            "device_type": "anti_intrusion",
            "project_id": proj["id"],
            "name": f"D{u}_前臂",
            "device_no": f"{u}A1",
            "longitude": 116.397428,
            "latitude": 39.90923,
        },
    ).json()["data"]
    machine = client.post(
        "/api/v1/machines",
        headers=_headers(token),
        json={"project_id": proj["id"], "machine_no": f"M{u}", "machine_type": "捣固车"},
    ).json()["data"]
    client.post(
        "/api/v1/jobs",
        headers=_headers(token),
        json={
            "project_id": proj["id"],
            "name": f"J{u}_计划",
            "is_start": True,
            "status": "执行中",
            "machine_bindings": [
                {
                    "machine_id": machine["id"],
                    "guard_person_id": guard["id"],
                    "arm_device_no": arm["device_no"],
                }
            ],
        },
    )
    return {
        "dept": dept,
        "project": proj,
        "guard": guard,
        "arm": arm,
        "machine": machine,
    }


def test_project_detail_machine_enrichment(client, admin_token):
    """大机详情应补充防护人员姓名 + 坐标（来自作业计划机械绑定）。"""
    u = _uid()
    try:
        env = _build(client, admin_token, u)
        r = client.get(
            f"/api/v1/dashboard/project-detail/{env['project']['id']}",
            headers=_headers(admin_token),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == 0
        data = body["data"]

        # 结构完整
        for key in ("project", "devices", "fences", "persons", "machines", "alarms"):
            assert key in data

        # 找到测试大机
        m = next((x for x in data["machines"] if x["machine_no"] == f"M{u}"), None)
        assert m is not None, "测试大机应出现在 machines 中"

        # 新字段存在且经绑定解析
        assert m["guard_person_name"] == env["guard"]["name"]
        assert m["lng"] is not None and m["lat"] is not None
        assert m["track_device_no"] == env["arm"]["device_no"]
    finally:
        _cleanup(u)


def test_project_detail_scope_isolation(client, admin_token):
    """scope 受限用户看不到他人部门项目（BusinessError 404）。"""
    u = _uid()
    try:
        # 项目所在部门 A
        dept_a = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": f"部门{u}A", "code": f"T{u}_A", "parent_id": None},
        ).json()["data"]
        proj = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_项目", "dept_id": dept_a["id"], "status": "在建"},
        ).json()["data"]

        # 隔离部门 B + 受限角色（data_scope=3 仅本部门）+ dashboard:view
        dept_b = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": f"部门{u}B", "code": f"T{u}_B", "parent_id": None},
        ).json()["data"]
        role = client.post(
            "/api/v1/auth/roles",
            headers=_headers(admin_token),
            json={"name": f"R{u}", "code": f"T{u}_R", "data_scope": 3, "dept_ids": [dept_b["id"]]},
        ).json()["data"]
        client.post(
            f"/api/v1/auth/roles/{role['id']}/permissions",
            headers=_headers(admin_token),
            json={"permission_codes": ["dashboard:view"]},
        )
        lr = client.post(
            "/api/v1/auth/register",
            headers=_headers(admin_token),
            json={
                "username": f"U{u}",
                "nickname": f"U{u}",
                "password": "Test@123456",
                "dept_id": dept_b["id"],
                "role_codes": [f"T{u}_R"],
                "status": True,
            },
        )
        assert lr.status_code == 200, lr.text
        token = client.post(
            "/api/v1/auth/login", json={"username": f"U{u}", "password": "Test@123456"}
        ).json()["data"]["access_token"]

        r = client.get(
            f"/api/v1/dashboard/project-detail/{proj['id']}",
            headers=_headers(token),
        )
        assert r.status_code == 200
        assert r.json()["code"] == 404
    finally:
        _cleanup(u)
