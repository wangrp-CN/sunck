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


def test_person_list_filters_and_sort(client, admin_token):
    """列表按 project_id / name(精确) / person_type 过滤，并按创建时间倒序。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj_a = _create_project(client, admin_token, u, dept["id"], "A")
        proj_b = _create_project(client, admin_token, u, dept["id"], "B")
        h = _headers(admin_token)

        # 依次创建三条（用于验证创建时间倒序）
        r1 = client.post(
            "/api/v1/persons",
            headers=h,
            json={
                "project_id": proj_a["id"],
                "person_no": f"P{u}_1",
                "name": "甲",
                "person_type": "防护人员",
            },
        )
        r2 = client.post(
            "/api/v1/persons",
            headers=h,
            json={
                "project_id": proj_a["id"],
                "person_no": f"P{u}_2",
                "name": "乙",
                "person_type": "施工人员",
            },
        )
        r3 = client.post(
            "/api/v1/persons",
            headers=h,
            json={
                "project_id": proj_b["id"],
                "person_no": f"P{u}_3",
                "name": "丙",
                "person_type": "防护人员",
            },
        )
        assert {r1.status_code, r2.status_code, r3.status_code} == {200}, (
            r1.text,
            r2.text,
            r3.text,
        )
        id1, id2, id3 = r1.json()["data"]["id"], r2.json()["data"]["id"], r3.json()["data"]["id"]

        # 按 project_id 过滤：仅返回该项目下人员
        r = client.get(
            "/api/v1/persons", headers=h, params={"project_id": proj_a["id"], "size": 50}
        )
        got = {it["id"] for it in r.json()["data"]["items"]}
        assert id1 in got and id2 in got and id3 not in got, got

        # 按 name 精确过滤
        r = client.get("/api/v1/persons", headers=h, params={"name": "乙", "size": 50})
        items = r.json()["data"]["items"]
        assert len(items) == 1 and items[0]["id"] == id2, items

        # 按 person_type 过滤
        r = client.get("/api/v1/persons", headers=h, params={"person_type": "防护人员", "size": 50})
        got = {it["id"] for it in r.json()["data"]["items"]}
        assert id1 in got and id3 in got and id2 not in got, got

        # 创建时间倒序：最后创建的 id3 应排在最前
        r = client.get("/api/v1/persons", headers=h, params={"size": 50})
        ids_order = [it["id"] for it in r.json()["data"]["items"]]
        assert ids_order.index(id3) < ids_order.index(id2) < ids_order.index(id1), ids_order
    finally:
        _cleanup(u)


def test_person_create_boundary_and_invalid(client, admin_token):
    """边界值（字段长度 64/65）与异常（缺项目 / 项目不存在）。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        h = _headers(admin_token)

        # 边界：person_no / name 恰好 64 字符 -> 创建成功
        exact64 = "x" * 64
        r = client.post(
            "/api/v1/persons",
            headers=h,
            json={"project_id": proj["id"], "person_no": exact64, "name": exact64},
        )
        assert r.status_code == 200, r.text

        # 边界越界：person_no 65 字符 -> 参数校验失败（HTTP 200 + code 422）
        over65 = "x" * 65
        r = client.post(
            "/api/v1/persons",
            headers=h,
            json={"project_id": proj["id"], "person_no": over65, "name": "越界"},
        )
        assert r.status_code == 200 and r.json()["code"] == 422, r.text

        # 边界越界：name 65 字符 -> 422
        r = client.post(
            "/api/v1/persons",
            headers=h,
            json={"project_id": proj["id"], "person_no": "PNO", "name": over65},
        )
        assert r.status_code == 200 and r.json()["code"] == 422, r.text

        # 异常：缺 project_id -> 422
        r = client.post("/api/v1/persons", headers=h, json={"person_no": "PNO2", "name": "缺项目"})
        assert r.status_code == 200 and r.json()["code"] == 422, r.text

        # 异常：project_id 不存在 -> 业务错误（HTTP 200 + code 400）
        r = client.post(
            "/api/v1/persons",
            headers=h,
            json={"project_id": 9_999_999, "person_no": "PNO3", "name": "幽灵项目"},
        )
        assert r.status_code == 200 and r.json()["code"] == 400, r.text
    finally:
        _cleanup(u)


def test_person_batch_delete(client, admin_token):
    """批量软删：范围内记录删除，范围外 / 不存在 id 计入 skipped。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        h = _headers(admin_token)
        id1 = client.post(
            "/api/v1/persons",
            headers=h,
            json={"project_id": proj["id"], "person_no": f"P{u}_b1", "name": "批删1"},
        ).json()["data"]["id"]
        id2 = client.post(
            "/api/v1/persons",
            headers=h,
            json={"project_id": proj["id"], "person_no": f"P{u}_b2", "name": "批删2"},
        ).json()["data"]["id"]

        r = client.post(
            "/api/v1/persons/batch-delete", headers=h, json={"ids": [id1, id2, 9_999_999]}
        )
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["deleted"] == 2 and d["total"] == 3 and d["skipped"] == 1, d

        # 已删除不可见
        assert client.get(f"/api/v1/persons/{id1}", headers=h).status_code == 404
        assert client.get(f"/api/v1/persons/{id2}", headers=h).status_code == 404
    finally:
        _cleanup(u)
