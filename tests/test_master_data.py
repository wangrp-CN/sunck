"""主数据（设备/人员/机械/围栏）CRUD 与权限/数据隔离测试。

覆盖：
- 管理员对四类主数据完整增删改查（含软删后不可见）。
- 无对应 add 权限用户创建被 403 拦截。
- 数据范围隔离：本部门及以下(scope=3)用户经 project 关联仅见其部门内数据（VIA_PROJECT）。

通过 TestClient 以真实库运行；按 uid 前缀清理自建数据，避免污染开发库。
"""

import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.main import app
from app.model.device import (
    AntiIntrusionDevice,
    LocateDevice,
    TrainApproachDevice,
)
from app.model.fence import ElectronicFence
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
        db.execute(delete(LocateDevice).where(LocateDevice.name.like(f"D{u}%")))
        db.execute(delete(AntiIntrusionDevice).where(AntiIntrusionDevice.name.like(f"D{u}%")))
        db.execute(delete(TrainApproachDevice).where(TrainApproachDevice.name.like(f"D{u}%")))
        db.execute(delete(Person).where(Person.name.like(f"PER{u}%")))
        db.execute(delete(Machine).where(Machine.machine_no.like(f"M{u}%")))
        db.execute(delete(ElectronicFence).where(ElectronicFence.name.like(f"F{u}%")))
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


def _make_project(client, admin_token, u, dept_id, suffix="A"):
    r = client.post(
        "/api/v1/projects",
        headers=_headers(admin_token),
        json={
            "name": f"P{u}_{suffix}",
            "dept_id": dept_id,
            "short_name": "PX",
            "status": "在建",
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


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


def test_master_data_admin_full_crud(client, admin_token):
    """管理员对设备/人员/机械/围栏完整 CRUD，软删后不可见。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _make_project(client, admin_token, u, dept["id"])

        # ---- 设备(locate) ----
        r = client.post(
            "/api/v1/devices",
            headers=_headers(admin_token),
            json={
                "device_type": "locate",
                "project_id": proj["id"],
                "name": f"D{u}_loc",
                "device_no": f"DN{u}1",
                "function": "定位",
            },
        )
        assert r.status_code == 200, r.text
        did = r.json()["data"]["id"]
        assert r.json()["data"]["device_type"] == "locate"

        r = client.get(
            "/api/v1/devices",
            headers=_headers(admin_token),
            params={"keyword": f"D{u}", "page": 1, "size": 20},
        )
        assert did in {it["id"] for it in r.json()["data"]["items"]}

        r = client.put(
            f"/api/v1/devices/{did}",
            headers=_headers(admin_token),
            params={"device_type": "locate"},
            json={"name": f"D{u}_loc2"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["name"] == f"D{u}_loc2"

        r = client.delete(
            f"/api/v1/devices/{did}",
            headers=_headers(admin_token),
            params={"device_type": "locate"},
        )
        assert r.status_code == 200, r.text
        r = client.get(
            f"/api/v1/devices/{did}",
            headers=_headers(admin_token),
            params={"device_type": "locate"},
        )
        assert r.status_code == 404

        # ---- 人员 ----
        r = client.post(
            "/api/v1/persons",
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "person_no": f"PN{u}1",
                "name": f"PER{u}_甲",
                "gender": "男",
                "person_type": "防护",
            },
        )
        assert r.status_code == 200, r.text
        pid = r.json()["data"]["id"]

        r = client.put(
            f"/api/v1/persons/{pid}",
            headers=_headers(admin_token),
            json={"name": f"PER{u}_乙"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["name"] == f"PER{u}_乙"

        r = client.delete(f"/api/v1/persons/{pid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        r = client.get(f"/api/v1/persons/{pid}", headers=_headers(admin_token))
        assert r.status_code == 404

        # ---- 机械 ----
        r = client.post(
            "/api/v1/machines",
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "machine_no": f"M{u}1",
                "machine_type": "捣固车",
            },
        )
        assert r.status_code == 200, r.text
        mid = r.json()["data"]["id"]

        r = client.delete(f"/api/v1/machines/{mid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        r = client.get(f"/api/v1/machines/{mid}", headers=_headers(admin_token))
        assert r.status_code == 404

        # ---- 围栏 ----
        r = client.post(
            "/api/v1/fences",
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"F{u}_围栏",
                "fence_type": "人员",
                "enabled": True,
                "geometry_wkt": "POLYGON((0 0,1 0,1 1,0 1,0 0))",
            },
        )
        assert r.status_code == 200, r.text
        fid = r.json()["data"]["id"]

        r = client.delete(f"/api/v1/fences/{fid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        r = client.get(f"/api/v1/fences/{fid}", headers=_headers(admin_token))
        assert r.status_code == 404
    finally:
        _cleanup(u)


def test_master_data_create_requires_permission(client, admin_token):
    """仅 device:list 权限用户创建设备被 403。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _make_project(client, admin_token, u, dept["id"])
        role = _make_role(client, admin_token, u, "READER", ["device:list"])
        tok = _make_user(client, admin_token, u, f"T{u}_reader", role["code"], dept["id"])

        r = client.post(
            "/api/v1/devices",
            headers=_headers(tok),
            json={
                "device_type": "locate",
                "project_id": proj["id"],
                "name": f"D{u}_无权限",
                "device_no": f"DN{u}X",
            },
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(u)


def test_master_data_isolation_via_project(client, admin_token):
    """本部门及以下(scope=3)用户经 project 关联仅见其部门内数据。"""
    u = _uid()
    try:
        dept_a = _make_dept(client, admin_token, u, "A")
        dept_b = _make_dept(client, admin_token, u, "B")
        proj_a = _make_project(client, admin_token, u, dept_a["id"], "A")
        proj_b = _make_project(client, admin_token, u, dept_b["id"], "B")

        role = _make_role(
            client,
            admin_token,
            u,
            "PM",
            [
                "device:list",
                "device:add",
                "device:edit",
                "device:delete",
                "person:list",
                "person:add",
            ],
            data_scope=3,
        )
        tok = _make_user(client, admin_token, u, f"T{u}_pm", role["code"], dept_a["id"])

        # 管理员在 A、B 项目各建一个设备
        da = client.post(
            "/api/v1/devices",
            headers=_headers(admin_token),
            json={
                "device_type": "locate",
                "project_id": proj_a["id"],
                "name": f"D{u}_A",
                "device_no": f"DN{u}A",
            },
        ).json()["data"]
        db = client.post(
            "/api/v1/devices",
            headers=_headers(admin_token),
            json={
                "device_type": "anti_intrusion",
                "project_id": proj_b["id"],
                "name": f"D{u}_B",
                "device_no": f"DN{u}B",
            },
        ).json()["data"]

        # 该用户仅应见到 A 项目设备
        r = client.get("/api/v1/devices", headers=_headers(tok))
        assert r.status_code == 200, r.text
        ids = {it["id"] for it in r.json()["data"]["items"]}
        assert da["id"] in ids
        assert db["id"] not in ids

        # 越权访问 B 设备详情 → 404
        r = client.get(
            f"/api/v1/devices/{db['id']}",
            headers=_headers(tok),
            params={"device_type": "anti_intrusion"},
        )
        assert r.status_code == 404

        # 该用户在 A 项目创建设备应成功
        r = client.post(
            "/api/v1/devices",
            headers=_headers(tok),
            json={
                "device_type": "locate",
                "project_id": proj_a["id"],
                "name": f"D{u}_A2",
                "device_no": f"DN{u}A2",
            },
        )
        assert r.status_code == 200, r.text
    finally:
        _cleanup(u)
