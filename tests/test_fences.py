"""电子围栏 CRUD 与权限/数据隔离测试。

覆盖：
- 管理员完整增删改查（含关键词搜索、软删后详情 404）。
- 无 fence:add 权限用户创建被 403 拦截。
- 数据范围隔离：本部门及以下(scope=3)用户仅可见其部门内项目下的围栏。

按 uid 前缀清理自建数据，避免污染开发库。
"""

from sqlalchemy import delete

from app.core.database import SessionLocal
from app.model.fence import ElectronicFence
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
        db.execute(delete(ElectronicFence).where(ElectronicFence.name.like(f"F{u}%")))
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


def test_fence_full_crud_by_admin(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        # 1) 创建
        r = client.post(
            "/api/v1/fences",
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "name": f"F{u}_围栏",
                "fence_type": "人员",
                "geometry_wkt": "POLYGON((0 0,0 1,1 1,1 0,0 0))",
            },
        )
        assert r.status_code == 200, r.text
        fid = r.json()["data"]["id"]

        # 2) 列表 + 关键词搜索
        r = client.get(
            "/api/v1/fences",
            headers=_headers(admin_token),
            params={"keyword": f"F{u}", "page": 1, "size": 20},
        )
        assert r.status_code == 200, r.text
        ids = {it["id"] for it in r.json()["data"]["items"]}
        assert fid in ids

        # 3) 详情
        r = client.get(f"/api/v1/fences/{fid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        assert r.json()["data"]["fence_type"] == "人员"

        # 4) 更新
        r = client.put(
            f"/api/v1/fences/{fid}",
            headers=_headers(admin_token),
            json={"name": f"F{u}_围栏改", "enabled": False},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["enabled"] is False

        # 5) 软删后详情 404
        r = client.delete(f"/api/v1/fences/{fid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        r = client.get(f"/api/v1/fences/{fid}", headers=_headers(admin_token))
        assert r.status_code == 404
    finally:
        _cleanup(u)


def test_fence_create_requires_permission(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        role = _make_role(client, admin_token, u, "READER", ["fence:list"])
        tok = _make_user(client, admin_token, u, f"T{u}_reader", role["code"], dept["id"])

        r = client.post(
            "/api/v1/fences",
            headers=_headers(tok),
            json={"project_id": proj["id"], "name": f"F{u}_无权限"},
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(u)


def test_fence_data_isolation_by_dept(client, admin_token):
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
            "FM",
            ["fence:list", "fence:add", "fence:edit", "fence:delete"],
            data_scope=3,
        )
        tok = _make_user(client, admin_token, u, f"T{u}_fm", role["code"], dept_a["id"])

        # 管理员在 A、B 各建一个围栏
        fa = client.post(
            "/api/v1/fences",
            headers=_headers(admin_token),
            json={"project_id": proj_a["id"], "name": f"F{u}_A"},
        ).json()["data"]
        fb = client.post(
            "/api/v1/fences",
            headers=_headers(admin_token),
            json={"project_id": proj_b["id"], "name": f"F{u}_B"},
        ).json()["data"]

        # 该用户仅应见到 A 部门项目下的围栏
        r = client.get("/api/v1/fences", headers=_headers(tok))
        assert r.status_code == 200, r.text
        ids = {it["id"] for it in r.json()["data"]["items"]}
        assert fa["id"] in ids
        assert fb["id"] not in ids

        # 越权访问 B 围栏详情 → 404
        r = client.get(f"/api/v1/fences/{fb['id']}", headers=_headers(tok))
        assert r.status_code == 404

        # 该用户在 A 部门项目下创建围栏应成功
        r = client.post(
            "/api/v1/fences",
            headers=_headers(tok),
            json={"project_id": proj_a["id"], "name": f"F{u}_A2"},
        )
        assert r.status_code == 200, r.text
    finally:
        _cleanup(u)
