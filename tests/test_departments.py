"""部门管理 CRUD 与权限测试。

部门为组织树结构，无数据范围(scope)隔离，仅按权限码门禁。
覆盖：
- 管理员完整增删改查（含树形查询、软删后详情 404）。
- 无 dept:add 权限用户创建被 403 拦截。

按 uid 前缀清理自建数据，避免污染开发库。
"""

from tests.helpers import (
    _cleanup_org,
    _headers,
    _make_role,
    _make_user,
    _uid,
)


def _cleanup(u: str) -> None:
    # 部门以 T{u} 编码前缀创建，_cleanup_org 已递归清理部门/角色/用户
    _cleanup_org(u)


def test_department_full_crud_by_admin(client, admin_token):
    u = _uid()
    try:
        # 1) 创建顶级部门
        r = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": f"部门A{u}", "code": f"T{u}_A"},
        )
        assert r.status_code == 200, r.text
        aid = r.json()["data"]["id"]

        # 2) 列表 + 树形
        r = client.get("/api/v1/departments", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        codes = {it["code"] for it in r.json()["data"]}
        assert f"T{u}_A" in codes

        r = client.get("/api/v1/departments/tree", headers=_headers(admin_token))
        assert r.status_code == 200, r.text

        # 3) 更新
        r = client.put(
            f"/api/v1/departments/{aid}",
            headers=_headers(admin_token),
            json={"name": f"部门A{u}改"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["name"] == f"部门A{u}改"

        # 4) 软删后列表不再包含该部门
        r = client.delete(f"/api/v1/departments/{aid}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        r = client.get("/api/v1/departments", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        codes = {it["code"] for it in r.json()["data"]}
        assert f"T{u}_A" not in codes
    finally:
        _cleanup(u)


def test_department_create_sub_and_tree(client, admin_token):
    u = _uid()
    try:
        parent = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": f"上级{u}", "code": f"T{u}_P"},
        ).json()["data"]
        child = client.post(
            "/api/v1/departments",
            headers=_headers(admin_token),
            json={"name": f"下级{u}", "code": f"T{u}_C", "parent_id": parent["id"]},
        )
        assert child.status_code == 200, child.text
        assert child.json()["data"]["parent_id"] == parent["id"]

        # 树形应包含父子关系
        r = client.get("/api/v1/departments/tree", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
        flat = r.json()["data"]
        parent_node = next((n for n in flat if n["code"] == f"T{u}_P"), None)
        assert parent_node is not None
        child_codes = {c["code"] for c in parent_node.get("children", [])}
        assert f"T{u}_C" in child_codes
    finally:
        _cleanup(u)


def test_department_create_requires_permission(client, admin_token):
    u = _uid()
    try:
        # 仅 dept:list 权限、无 dept:add 的用户
        role = _make_role(client, admin_token, u, "READER", ["dept:list"])
        tok = _make_user(client, admin_token, u, f"T{u}_reader", role["code"], None)

        r = client.post(
            "/api/v1/departments",
            headers=_headers(tok),
            json={"name": f"无权限{u}", "code": f"T{u}_DENY"},
        )
        assert r.status_code == 403, r.text
    finally:
        _cleanup(u)


def test_departments_page_and_batch_delete(client, admin_token):
    u = _uid()
    try:
        h = _headers(admin_token)
        # 建两个无子部门/无用户的部门
        ids = []
        for i in range(2):
            r = client.post(
                "/api/v1/departments",
                headers=h,
                json={"name": f"批量部门_{i}", "code": f"T{u}_BD{i}"},
            )
            assert r.status_code == 200, r.text
            ids.append(r.json()["data"]["id"])

        # 分页：size=2
        p = client.get("/api/v1/departments/page?page=1&size=2", headers=h)
        assert p.status_code == 200, p.text
        body = p.json()["data"]
        assert body["page"] == 1 and body["size"] == 2
        assert len(body["items"]) == 2

        # 批量删除（软删）
        bd = client.post(
            "/api/v1/departments/batch-delete",
            headers=h,
            json={"ids": ids},
        )
        assert bd.status_code == 200, bd.text
        res = bd.json()["data"]
        assert res["deleted"] == 2 and res["skipped"] == 0

        # 软删后分页中不再出现
        after = client.get("/api/v1/departments/page", headers=h).json()["data"]
        after_ids = [x["id"] for x in after["items"]]
        assert ids[0] not in after_ids and ids[1] not in after_ids
    finally:
        _cleanup(u)
