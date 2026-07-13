"""部门数据隔离端到端测试。

覆盖四种数据范围：
- 1 全部（超级管理员可见全部）
- 2 自定义部门（角色绑定部门，自动含下级）
- 3 本部门及以下（用户所属部门及其下级）
- 4 仅本人（created_by == 当前用户）

通过 TestClient 以真实数据库连接运行；测试结束按 uid 清理自建数据，避免污染开发库。
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
    """按 uid 清理本次测试自建的部门/角色/用户/项目与 role_dept。"""
    db = SessionLocal()
    try:
        role_ids = db.scalars(select(Role.id).where(Role.code.like(f"T{u}%"))).all()
        if role_ids:
            db.execute(role_dept.delete().where(role_dept.c.role_id.in_(role_ids)))
        db.execute(delete(Project).where(Project.name.like(f"P{u}%")))
        db.execute(delete(User).where(User.username.like(f"T{u}%")))
        db.execute(delete(Role).where(Role.code.like(f"T{u}%")))
        # 部门需先删子级再删父级
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


def test_health_smoke(client):
    # 确保数据范围相关路由已挂载
    assert client.get("/api/v1/departments").status_code in (200, 401)
    assert client.get("/api/v1/projects").status_code in (200, 401)


def test_data_scope_isolation(client, admin_token):
    u = _uid()
    try:
        # 1) 建部门树：T_HQ -> T_SEC -> T_WS
        hq = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": "测试集团", "code": f"T{u}_HQ", "parent_id": None},
        ).json()["data"]
        sec = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": "测试段", "code": f"T{u}_SEC", "parent_id": hq["id"]},
        ).json()["data"]
        ws = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": "测试车间", "code": f"T{u}_WS", "parent_id": sec["id"]},
        ).json()["data"]

        # 2) 建角色（精确控制权限与数据范围）
        def make_role(code, data_scope, perms, dept_ids=None):
            body = {"name": code, "code": code, "data_scope": data_scope, "remark": "test"}
            if dept_ids is not None:
                body["dept_ids"] = dept_ids
            role = client.post(
                "/api/v1/auth/roles", headers=_headers(admin_token), json=body
            ).json()["data"]
            client.post(
                f"/api/v1/auth/roles/{role['id']}/permissions",
                headers=_headers(admin_token),
                json={"permission_codes": perms},
            )
            return role

        r_monitor = make_role(f"T{u}_MON", 3, ["project:list", "user:list"])
        r_pm = make_role(f"T{u}_PM", 2, ["project:list"], dept_ids=[sec["id"]])
        r_self = make_role(f"T{u}_SELF", 4, ["project:list", "project:add", "user:list"])
        r_other = make_role(f"T{u}_OTHER", 3, ["project:list"])

        def make_user(username, role_code, dept_id):
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

        tok_monitor = make_user(f"T{u}_mon", r_monitor["code"], ws["id"])
        tok_pm = make_user(f"T{u}_pm", r_pm["code"], ws["id"])
        tok_self = make_user(f"T{u}_self", r_self["code"], ws["id"])
        tok_other = make_user(f"T{u}_oth", r_other["code"], hq["id"])

        # 3) 建项目
        def make_project(name, dept_id, token):
            return client.post(
                "/api/v1/projects",
                headers=_headers(token),
                json={"name": name, "dept_id": dept_id, "status": "在建"},
            ).json()["data"]

        p_ws = make_project(f"P{u}_WS", ws["id"], admin_token)
        p_hq = make_project(f"P{u}_HQ", hq["id"], admin_token)
        p_self = make_project(f"P{u}_SELF", ws["id"], tok_self)

        def project_ids(token):
            r = client.get("/api/v1/projects", headers=_headers(token))
            assert r.status_code == 200, r.text
            return {it["id"] for it in r.json()["data"]["items"]}

        # 4) 断言隔离结果（管理员可见全部：以子集断言，规避历史测试遗留数据）
        assert {p_ws["id"], p_hq["id"], p_self["id"]} <= project_ids(admin_token)
        assert project_ids(tok_monitor) == {p_ws["id"], p_self["id"]}
        assert project_ids(tok_pm) == {p_ws["id"], p_self["id"]}
        assert project_ids(tok_self) == {p_self["id"]}
        # 另一部门(集团=测试树根)监测员：本部门及以下=整棵测试树，应见全部 3 个
        assert project_ids(tok_other) == {p_ws["id"], p_hq["id"], p_self["id"]}

        # 越权详情：监测员访问集团项目应 404
        r = client.get(f"/api/v1/projects/{p_hq['id']}", headers=_headers(tok_monitor))
        assert r.status_code == 404

        # 用户列表隔离：监测员仅见本部门(车间)用户
        r = client.get("/api/v1/auth/users", headers=_headers(tok_monitor))
        assert r.status_code == 200
        visible_users = {it["username"] for it in r.json()["data"]["items"]}
        assert f"T{u}_mon" in visible_users
        assert f"T{u}_pm" in visible_users
        assert f"T{u}_self" in visible_users
        assert f"T{u}_oth" not in visible_users

        # 仅本人角色查用户列表：无 created_by 列 → 返回空
        r = client.get("/api/v1/auth/users", headers=_headers(tok_self))
        assert r.status_code == 200
        assert r.json()["data"]["total"] == 0
    finally:
        _cleanup(u)


def test_custom_dept_scope_expands_descendants(client, admin_token):
    """自定义部门绑定父级时，应自动包含其下级部门数据。"""
    u = _uid()
    try:
        sec = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": "段X", "code": f"T{u}_SEC", "parent_id": None},
        ).json()["data"]
        ws = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": "车间X", "code": f"T{u}_WS", "parent_id": sec["id"]},
        ).json()["data"]
        role = client.post(
            "/api/v1/auth/roles",
            headers=_headers(admin_token),
            json={"name": f"T{u}_PM", "code": f"T{u}_PM", "data_scope": 2, "dept_ids": [sec["id"]]},
        ).json()["data"]
        client.post(
            f"/api/v1/auth/roles/{role['id']}/permissions",
            headers=_headers(admin_token),
            json={"permission_codes": ["project:list", "project:add"]},
        )
        pw = "Test@123456"
        client.post(
            "/api/v1/auth/register",
            headers=_headers(admin_token),
            json={
                "username": f"T{u}_u",
                "password": pw,
                "dept_id": ws["id"],
                "role_codes": [role["code"]],
                "status": True,
            },
        )
        tok = client.post(
            "/api/v1/auth/login", json={"username": f"T{u}_u", "password": pw}
        ).json()["data"]["access_token"]
        p = client.post(
            "/api/v1/projects",
            headers=_headers(tok),
            json={"name": f"P{u}", "dept_id": ws["id"], "status": "在建"},
        ).json()["data"]
        ids = {
            it["id"]
            for it in client.get("/api/v1/projects", headers=_headers(tok)).json()["data"]["items"]
        }
        assert p["id"] in ids  # 自定义部门(段)自动覆盖下级(车间)
    finally:
        _cleanup(u)
