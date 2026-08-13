"""大型机械 CRUD 与权限/数据隔离测试。

覆盖：
- 管理员完整增删改查（含关键词搜索、软删后详情 404）。
- 无 machine:add 权限用户创建被 403 拦截。
- 数据范围隔离：本部门及以下(scope=3)用户仅可见其部门内项目下的大机。

按 uid 前缀清理自建数据，避免污染开发库。
"""

from sqlalchemy import delete

from app.core.database import SessionLocal
from app.model.person import Machine
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
        db.execute(delete(Machine).where(Machine.machine_no.like(f"M{u}%")))
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


def test_machine_full_crud_by_admin(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        # 1) 创建
        r = client.post(
            "/api/v1/machines",
            headers=_headers(admin_token),
            json={
                "project_id": proj["id"],
                "machine_no": f"M{u}_01",
                "machine_type": "挖掘机",
                "spec_model": "XL-200",
            },
        )
        assert r.status_code == 200, r.text
        mid = r.json()["data"]["id"]

        # 2) 列表 + 关键词搜索
        r = client.get(
            "/api/v1/machines",
            headers=_headers(admin_token),
            params={"keyword": f"M{u}", "page": 1, "size": 20},
        )
        assert r.status_code == 200, r.text
        items = r.json()["data"]["items"]
        assert any(it["id"] == mid for it in items)

        # 3) 详情
        r = client.get(f"/api/v1/machines/{mid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        assert r.json()["data"]["machine_type"] == "挖掘机"

        # 4) 更新
        r = client.put(
            f"/api/v1/machines/{mid}",
            headers=_headers(admin_token),
            json={"machine_type": "推土机"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["machine_type"] == "推土机"

        # 5) 软删后详情 404
        r = client.delete(f"/api/v1/machines/{mid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        r = client.get(f"/api/v1/machines/{mid}", headers=_headers(admin_token))
        assert r.status_code == 404
    finally:
        _cleanup(u)


def test_machine_list_filters(client, admin_token):
    """列表过滤：project_id 精确、machine_no 精确、machine_type 精确。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        h = _headers(admin_token)

        r = client.post(
            "/api/v1/machines",
            headers=h,
            json={"project_id": proj["id"], "machine_no": f"M{u}_EX", "machine_type": "挖掘机"},
        )
        assert r.status_code == 200, r.text
        r = client.post(
            "/api/v1/machines",
            headers=h,
            json={"project_id": proj["id"], "machine_no": f"M{u}_PI", "machine_type": "打桩机"},
        )
        assert r.status_code == 200, r.text

        # project_id 精确过滤
        r = client.get(
            "/api/v1/machines", headers=h, params={"project_id": proj["id"], "page": 1, "size": 20}
        )
        assert r.status_code == 200, r.text
        items = r.json()["data"]["items"]
        assert all(it["project_id"] == proj["id"] for it in items)

        # machine_no 精确过滤
        r = client.get(
            "/api/v1/machines", headers=h, params={"machine_no": f"M{u}_EX", "page": 1, "size": 20}
        )
        assert r.status_code == 200, r.text
        items = r.json()["data"]["items"]
        assert len(items) == 1 and items[0]["machine_no"] == f"M{u}_EX"

        # machine_type 精确过滤
        r = client.get(
            "/api/v1/machines", headers=h, params={"machine_type": "打桩机", "page": 1, "size": 20}
        )
        assert r.status_code == 200, r.text
        items = r.json()["data"]["items"]
        assert all(it["machine_type"] == "打桩机" for it in items)
        assert any(it["machine_no"] == f"M{u}_PI" for it in items)

        # 冗余 project_name 随列表返回
        r = client.get(
            "/api/v1/machines", headers=h, params={"machine_no": f"M{u}_EX", "page": 1, "size": 20}
        )
        assert r.json()["data"]["items"][0]["project_name"] == proj["name"]
    finally:
        _cleanup(u)


def test_machine_create_requires_permission(client, admin_token):
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        role = _make_role(client, admin_token, u, "READER", ["machine:list"])
        tok = _make_user(client, admin_token, u, f"T{u}_reader", role["code"], dept["id"])

        r = client.post(
            "/api/v1/machines",
            headers=_headers(tok),
            json={"project_id": proj["id"], "machine_no": f"M{u}_无权限"},
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(u)


def test_machine_data_isolation_by_dept(client, admin_token):
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
            "MM",
            ["machine:list", "machine:add", "machine:edit", "machine:delete"],
            data_scope=3,
        )
        tok = _make_user(client, admin_token, u, f"T{u}_mm", role["code"], dept_a["id"])

        ma = client.post(
            "/api/v1/machines",
            headers=_headers(admin_token),
            json={"project_id": proj_a["id"], "machine_no": f"M{u}_A"},
        ).json()["data"]
        mb = client.post(
            "/api/v1/machines",
            headers=_headers(admin_token),
            json={"project_id": proj_b["id"], "machine_no": f"M{u}_B"},
        ).json()["data"]

        r = client.get("/api/v1/machines", headers=_headers(tok))
        assert r.status_code == 200, r.text
        ids = {it["id"] for it in r.json()["data"]["items"]}
        assert ma["id"] in ids
        assert mb["id"] not in ids

        r = client.get(f"/api/v1/machines/{mb['id']}", headers=_headers(tok))
        assert r.status_code == 404

        r = client.post(
            "/api/v1/machines",
            headers=_headers(tok),
            json={"project_id": proj_a["id"], "machine_no": f"M{u}_A2"},
        )
        assert r.status_code == 200, r.text
    finally:
        _cleanup(u)


def test_machine_create_boundary_and_invalid(client, admin_token):
    """边界值（machine_no 64/65）与异常（缺项目 / 项目不存在）。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        h = _headers(admin_token)

        # 边界：machine_no 恰好 64 字符 -> 创建成功
        r = client.post(
            "/api/v1/machines",
            headers=h,
            json={"project_id": proj["id"], "machine_no": "x" * 64},
        )
        assert r.status_code == 200, r.text

        # 边界越界：machine_no 65 字符 -> 参数校验失败（HTTP 200 + code 422）
        r = client.post(
            "/api/v1/machines",
            headers=h,
            json={"project_id": proj["id"], "machine_no": "x" * 65},
        )
        assert r.status_code == 200 and r.json()["code"] == 422, r.text

        # 异常：缺 project_id -> 422
        r = client.post("/api/v1/machines", headers=h, json={"machine_no": "MNO"})
        assert r.status_code == 200 and r.json()["code"] == 422, r.text

        # 异常：project_id 不存在 -> 业务错误（HTTP 200 + code 400）
        r = client.post(
            "/api/v1/machines",
            headers=h,
            json={"project_id": 9_999_999, "machine_no": "MNO2"},
        )
        assert r.status_code == 200 and r.json()["code"] == 400, r.text
    finally:
        _cleanup(u)


def test_machine_batch_delete(client, admin_token):
    """批量软删：范围内记录删除，不存在 id 计入 skipped。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        h = _headers(admin_token)
        id1 = client.post(
            "/api/v1/machines",
            headers=h,
            json={"project_id": proj["id"], "machine_no": f"M{u}_b1"},
        ).json()["data"]["id"]
        id2 = client.post(
            "/api/v1/machines",
            headers=h,
            json={"project_id": proj["id"], "machine_no": f"M{u}_b2"},
        ).json()["data"]["id"]

        r = client.post(
            "/api/v1/machines/batch-delete", headers=h, json={"ids": [id1, id2, 9_999_999]}
        )
        assert r.status_code == 200, r.text
        d = r.json()["data"]
        assert d["deleted"] == 2 and d["total"] == 3 and d["skipped"] == 1, d

        assert client.get(f"/api/v1/machines/{id1}", headers=h).status_code == 404
    finally:
        _cleanup(u)
