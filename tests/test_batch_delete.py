"""批量删除（POST {资源}/batch-delete）集成测试。

统一约定：
- 请求体 `{"ids": [...]}`，响应 data 为 `{deleted, total, skipped}`；
- 软删实体走 `batch_soft_delete`（含数据隔离、已删跳过）；
- 字典项为物理删除；系统用户批量删除跳过超管。

覆盖：
1. 围栏：超管批量软删、重复删除幂等（skipped）、数据隔离下越权 id 被跳过、无权限 403；
2. 字典项：物理删除后类型详情不再返回该项；
3. 系统用户：超管账号被跳过（受保护）。

按 uid 前缀清理自建数据，避免污染开发库。
"""

import uuid

import pytest
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.model.dict import DictType
from app.model.fence import ElectronicFence
from app.model.project import Project
from app.model.system import User
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


def _create_fence(client, token, u, project_id, suffix):
    r = client.post(
        "/api/v1/fences",
        headers=_headers(token),
        json={"project_id": project_id, "name": f"F{u}_{suffix}"},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _batch_delete(client, token, url, ids):
    r = client.post(url, headers=_headers(token), json={"ids": ids})
    return r


def test_batch_delete_fences_by_admin(client, admin_token):
    """超管批量软删：deleted 计数正确，被删记录不再出现在列表中。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        f1 = _create_fence(client, admin_token, u, proj["id"], "1")
        f2 = _create_fence(client, admin_token, u, proj["id"], "2")
        f3 = _create_fence(client, admin_token, u, proj["id"], "3")

        r = _batch_delete(client, admin_token, "/api/v1/fences/batch-delete", [f1["id"], f2["id"]])
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data == {"deleted": 2, "total": 2, "skipped": 0}

        r = client.get("/api/v1/fences", headers=_headers(admin_token), params={"keyword": f"F{u}"})
        ids = {it["id"] for it in r.json()["data"]["items"]}
        assert ids == {f3["id"]}

        # 详情 404（确认软删生效）
        assert (
            client.get(f"/api/v1/fences/{f1['id']}", headers=_headers(admin_token)).status_code
            == 404
        )
    finally:
        _cleanup(u)


def test_batch_delete_is_idempotent(client, admin_token):
    """重复删除已删记录不报错，计入 skipped。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        proj = _create_project(client, admin_token, u, dept["id"], "项目")
        f1 = _create_fence(client, admin_token, u, proj["id"], "1")

        first = _batch_delete(
            client, admin_token, "/api/v1/fences/batch-delete", [f1["id"]]
        ).json()["data"]
        assert first["deleted"] == 1

        second = _batch_delete(
            client, admin_token, "/api/v1/fences/batch-delete", [f1["id"], 99999999]
        ).json()["data"]
        assert second == {"deleted": 0, "total": 2, "skipped": 2}
    finally:
        _cleanup(u)


def test_batch_delete_respects_data_scope(client, admin_token):
    """数据隔离：越权 id 被静默跳过，只删自己可见的记录。"""
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
            ["fence:list", "fence:add", "fence:delete"],
            data_scope=3,
        )
        tok = _make_user(client, admin_token, u, f"T{u}_fm", role["code"], dept_a["id"])

        fa = _create_fence(client, admin_token, u, proj_a["id"], "A")
        fb = _create_fence(client, admin_token, u, proj_b["id"], "B")

        r = _batch_delete(client, tok, "/api/v1/fences/batch-delete", [fa["id"], fb["id"]])
        assert r.status_code == 200, r.text
        assert r.json()["data"] == {"deleted": 1, "total": 2, "skipped": 1}

        # B 部门围栏仍在（未被越权删除）
        r = client.get(f"/api/v1/fences/{fb['id']}", headers=_headers(admin_token))
        assert r.status_code == 200, r.text
    finally:
        _cleanup(u)


def test_batch_delete_requires_permission(client, admin_token):
    """无 fence:delete 权限 → 403。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        role = _make_role(client, admin_token, u, "READER", ["fence:list"])
        tok = _make_user(client, admin_token, u, f"T{u}_r", role["code"], dept["id"])

        r = _batch_delete(client, tok, "/api/v1/fences/batch-delete", [1, 2])
        assert r.status_code == 403, r.text
    finally:
        _cleanup(u)


def test_batch_delete_rejects_oversized_payload(client, admin_token):
    """ids 上限 200，超出被请求体校验拦截（项目约定：HTTP 200 + body code=422）。"""
    r = _batch_delete(client, admin_token, "/api/v1/fences/batch-delete", list(range(1, 500)))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 422, body


_CREATED_CODES: list[str] = []


@pytest.fixture(autouse=True)
def _cleanup_dicts():
    yield
    if _CREATED_CODES:
        db = SessionLocal()
        db.query(DictType).filter(DictType.code.in_(_CREATED_CODES)).delete(
            synchronize_session=False
        )
        db.commit()
        db.close()
        _CREATED_CODES.clear()


def test_batch_delete_dict_items_hard_delete(client, admin_token):
    """字典项为物理删除：批量删除后类型详情不再返回。"""
    code = f"test_dict_{uuid.uuid4().hex[:8]}"
    r = client.post(
        "/api/v1/dicts",
        headers=_headers(admin_token),
        json={
            "code": code,
            "name": "批量删除测试字典",
            "items": [
                {"label": "A", "value": "a", "sort": 1},
                {"label": "B", "value": "b", "sort": 2},
                {"label": "C", "value": "c", "sort": 3},
            ],
        },
    )
    assert r.status_code == 200, r.text
    _CREATED_CODES.append(code)
    items = r.json()["data"]["items"]
    assert len(items) == 3

    ids = [items[0]["id"], items[1]["id"]]
    r = client.post(
        "/api/v1/dicts/items/batch-delete", headers=_headers(admin_token), json={"ids": ids}
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["deleted"] == 2

    r = client.get(f"/api/v1/dicts/{code}", headers=_headers(admin_token))
    left = {it["value"] for it in r.json()["data"]["items"]}
    assert left == {"c"}


def test_batch_delete_users_skips_superuser(client, admin_token):
    """系统用户批量删除：超管账号受保护被跳过。"""
    u = _uid()
    try:
        dept = _make_dept(client, admin_token, u, "A")
        role = _make_role(client, admin_token, u, "OP", ["user:list"])
        _make_user(client, admin_token, u, f"T{u}_a", role["code"], dept["id"])

        db = SessionLocal()
        try:
            target = db.query(User).filter(User.username == f"T{u}_a").one()
            target_id = target.id
            su = db.query(User).filter(User.is_superuser.is_(True)).first()
            su_id = su.id if su else None
        finally:
            db.close()

        ids = [target_id] + ([su_id] if su_id else [])
        r = client.post(
            "/api/v1/auth/users/batch-delete",
            headers=_headers(admin_token),
            json={"ids": ids},
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["deleted"] == 1
        assert data["skipped"] == len(ids) - 1

        # 超管账号仍存在且未被软删
        db = SessionLocal()
        try:
            if su_id:
                su_after = db.query(User).filter(User.id == su_id).one()
                assert su_after.is_deleted is False
            assert db.query(User).filter(User.id == target_id).one().is_deleted is True
        finally:
            db.close()
    finally:
        _cleanup_org(u)
