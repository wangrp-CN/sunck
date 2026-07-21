"""人员 CRUD 与权限/数据隔离测试。

覆盖：
- 管理员完整增删改查（含关键词搜索、软删后详情 404）。
- 无 person:add 权限用户创建被 403 拦截。
- 数据范围隔离：本部门及以下(scope=3)用户仅可见其部门内项目下的人员。

按 uid 前缀清理自建数据，避免污染开发库。
"""

from sqlalchemy import delete

from app.core.database import SessionLocal
from app.model.person import Person
from app.model.project import Project
from tests.helpers import (
    _cleanup_org,
    _headers,
    _make_dept,
    _make_role,
    _make_user,
    _uid,
)


def _cleanup(u: str) -> None:
    db = SessionLocal()
    try:
        db.execute(delete(Person).where(Person.person_no.like(f"P{u}%")))
        db.execute(delete(Project).where(Project.name.like(f"P{u}%")))
        db.commit()
    finally:
        db.close()
    _cleanup_org(u)


def _create_project(client, admin_token, u, dept_id, suffix):
    return client.post(
        "/api/v1/projects",
        headers=_headers(admin_token),
        json={"name": f"P{u}_{suffix}", "dept_id": dept_id},
    ).json()["data"]


def test_person_full_crud_by_admin(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        # 1) 创建
        r = client.post(
            "/api/v1/persons",
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "person_no": f"P{u}_01",
                "name": "张三",
                "person_type": "防护",
            },
        )
        assert r.status_code == 200, r.text
        pid = r.json()["data"]["id"]

        # 2) 列表 + 关键词搜索
        r = client.get(
            "/api/v1/persons",
            headers=_headers(admin_token),
            params={"keyword": f"P{u}", "page": 1, "size": 20},
        )
        assert r.status_code == 200, r.text
        items = r.json()["data"]["items"]
        assert any(it["id"] == pid for it in items)

        # 3) 详情
        r = client.get(f"/api/v1/persons/{pid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        assert r.json()["data"]["name"] == "张三"

        # 4) 更新
        r = client.put(
            f"/api/v1/persons/{pid}",
            headers=_headers(admin_token),
            json={"name": "李四"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["name"] == "李四"

        # 5) 软删后详情 404
        r = client.delete(f"/api/v1/persons/{pid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        r = client.get(f"/api/v1/persons/{pid}", headers=_headers(admin_token))
        assert r.status_code == 404
    finally:
        _cleanup(u)


def test_person_create_requires_permission(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        role = _make_role(client, admin_token, u, "READER", ["person:list"])
        tok = _make_user(client, admin_token, u, f"T{u}_reader", role["code"], dept["id"])

        r = client.post(
            "/api/v1/persons",
            headers=_headers(tok),
            json={
                "project_id": proj["id"],
                "person_no": f"P{u}_无权限",
                "name": "王五",
            },
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(u)


def test_person_data_isolation_by_dept(client, admin_token):
    u = _uid()
    try:
        dept_a = _make_dept(client, admin_token, u, "A")
        dept_b = _make_dept(client, admin_token, u, "B")
        proj_a = _create_project(client, admin_token, u, dept_a["id"], "A")
        proj_b = _create_project(client, admin_token, u, dept_b["id"], "B")
        role = _make_role(
            client,
            admin_token,
            u,
            "PM",
            ["person:list", "person:add", "person:edit", "person:delete"],
            data_scope=3,
        )
        tok = _make_user(client, admin_token, u, f"T{u}_pm", role["code"], dept_a["id"])

        pa = client.post(
            "/api/v1/persons",
            headers=_headers(admin_token),
            json={
                "project_id": proj_a["id"],
                "person_no": f"P{u}_A",
                "name": "甲",
            },
        ).json()["data"]
        pb = client.post(
            "/api/v1/persons",
            headers=_headers(admin_token),
            json={
                "project_id": proj_b["id"],
                "person_no": f"P{u}_B",
                "name": "乙",
            },
        ).json()["data"]

        r = client.get("/api/v1/persons", headers=_headers(tok))
        assert r.status_code == 200, r.text
        ids = {it["id"] for it in r.json()["data"]["items"]}
        assert pa["id"] in ids
        assert pb["id"] not in ids

        r = client.get(f"/api/v1/persons/{pb['id']}", headers=_headers(tok))
        assert r.status_code == 404

        r = client.post(
            "/api/v1/persons",
            headers=_headers(tok),
            json={
                "project_id": proj_a["id"],
                "person_no": f"P{u}_A2",
                "name": "丙",
            },
        )
        assert r.status_code == 200, r.text
    finally:
        _cleanup(u)
