"""项目 CRUD 与权限/数据隔离测试。

覆盖：
- 管理员完整增删改查（含关键词搜索、软删后不可见）。
- 无 project:add 权限用户创建被 403 拦截。
- 数据范围隔离：本部门及以下(scope=3)用户仅可见其部门内数据。

通过 TestClient 以真实库运行；按 uid 前缀清理自建数据，避免污染开发库。
"""

import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.main import app
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


def test_project_full_crud_by_admin(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        # 1) 创建
        r = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={
                "name": f"P{u}_项目",
                "dept_id": dept["id"],
                "short_name": "PX",
                "status": "在建",
                "section": "K1~K2",
                "mileage": "1.2km",
            },
        )
        assert r.status_code == 200, r.text
        pid = r.json()["data"]["id"]
        assert r.json()["data"]["name"] == f"P{u}_项目"

        # 2) 列表 + 关键词搜索
        r = client.get(
            "/api/v1/projects",
            headers=_headers(admin_token),
            params={"keyword": f"P{u}", "page": 1, "size": 20},
        )
        assert r.status_code == 200, r.text
        body = r.json()["data"]
        ids = {it["id"] for it in body["items"]}
        assert pid in ids

        # 3) 详情
        r = client.get(f"/api/v1/projects/{pid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        assert r.json()["data"]["section"] == "K1~K2"

        # 4) 更新
        r = client.put(
            f"/api/v1/projects/{pid}",
            headers=_headers(admin_token),
            json={"name": f"P{u}_项目改", "status": "竣工"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == "竣工"

        # 5) 软删后不可见（详情 404）
        r = client.delete(f"/api/v1/projects/{pid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        r = client.get(f"/api/v1/projects/{pid}", headers=_headers(admin_token))
        assert r.status_code == 404
    finally:
        _cleanup(u)


def test_project_create_requires_permission(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        # 仅 project:list 权限、无 project:add 的用户
        role = _make_role(client, admin_token, u, "READER", ["project:list"])
        tok = _make_user(client, admin_token, u, f"T{u}_reader", role["code"], dept["id"])

        r = client.post(
            "/api/v1/projects",
            headers=_headers(tok),
            json={"name": f"P{u}_无权限", "dept_id": dept["id"]},
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(u)


def test_project_data_isolation_by_dept(client, admin_token):
    u = _uid()
    try:
        dept_a = _make_dept(client, admin_token, u, "A")
        dept_b = _make_dept(client, admin_token, u, "B")
        # 本部门及以下(scope=3) + project 全权限
        role = _make_role(
            client,
            admin_token,
            u,
            "PM",
            ["project:list", "project:add", "project:edit", "project:delete"],
            data_scope=3,
        )
        tok = _make_user(client, admin_token, u, f"T{u}_pm", role["code"], dept_a["id"])

        # 管理员在 A、B 各建一个项目
        pa = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_A", "dept_id": dept_a["id"]},
        ).json()["data"]
        pb = client.post(
            "/api/v1/projects",
            headers=_headers(admin_token),
            json={"name": f"P{u}_B", "dept_id": dept_b["id"]},
        ).json()["data"]

        # 该用户仅应见到 A 部门项目，看不见 B 部门项目
        r = client.get("/api/v1/projects", headers=_headers(tok))
        assert r.status_code == 200, r.text
        ids = {it["id"] for it in r.json()["data"]["items"]}
        assert pa["id"] in ids
        assert pb["id"] not in ids

        # 越权访问 B 项目详情 → 404
        r = client.get(f"/api/v1/projects/{pb['id']}", headers=_headers(tok))
        assert r.status_code == 404

        # 该用户在 A 部门创建项目应成功
        r = client.post(
            "/api/v1/projects",
            headers=_headers(tok),
            json={"name": f"P{u}_A2", "dept_id": dept_a["id"]},
        )
        assert r.status_code == 200, r.text
    finally:
        _cleanup(u)
