"""RBAC 认证与权限控制端到端测试。

覆盖：登录鉴权、令牌校验、当前用户、权限拦截、角色拦截、登录失败锁定、刷新令牌。
测试会向开发库写入/清理专用测试账号（test_ 前缀），不影响种子数据。
"""

import secrets

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.model.system import User

BASE = "/api/v1/auth"
ADMIN = ("admin", "Admin@123456")


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _cleanup(username: str) -> None:
    db = SessionLocal()
    try:
        u = db.query(User).filter_by(username=username).first()
        if u:
            db.delete(u)
            db.commit()
    finally:
        db.close()


def _login(client: TestClient, username: str, password: str):
    return client.post(BASE + "/login", json={"username": username, "password": password})


def _admin_token(client: TestClient) -> str:
    return _login(client, *ADMIN).json()["data"]["access_token"]


def test_login_success_and_me(client):
    r = _login(client, *ADMIN)
    assert r.status_code == 200
    assert r.json()["code"] == 0
    token = r.json()["data"]["access_token"]
    # 访问受保护接口 /me
    me = client.get(BASE + "/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    data = me.json()["data"]
    assert data["username"] == "admin"
    assert "user:list" in data["permissions"]
    assert data["is_superuser"] is True


def test_no_token_401(client):
    r = client.get(BASE + "/me")
    assert r.status_code == 401
    assert r.json()["code"] == 401


def test_invalid_token_401(client):
    r = client.get(BASE + "/me", headers={"Authorization": "Bearer not.a.valid.token"})
    assert r.status_code == 401


def test_register_and_permission_denied(client):
    uname = "test_guest"
    _cleanup(uname)
    token = _admin_token(client)
    hdr = {"Authorization": f"Bearer {token}"}
    # 管理员创建 guest 角色用户
    r = client.post(
        BASE + "/register",
        json={"username": uname, "password": "Guest@123", "role_codes": ["guest"]},
        headers=hdr,
    )
    assert r.status_code == 200
    try:
        gtok = _login(client, uname, "Guest@123").json()["data"]["access_token"]
        ghr = {"Authorization": f"Bearer {gtok}"}
        # 缺少 user:list 权限 -> 403
        denied = client.get(BASE + "/users", headers=ghr)
        assert denied.status_code == 403
        # 仅需登录的接口 -> 200
        ok = client.get(BASE + "/permissions", headers=ghr)
        assert ok.status_code == 200
        assert ok.json()["code"] == 0
    finally:
        _cleanup(uname)


def test_superuser_only_endpoint(client):
    uname = "test_guest2"
    _cleanup(uname)
    token = _admin_token(client)
    hdr = {"Authorization": f"Bearer {token}"}
    r = client.post(
        BASE + "/register",
        json={"username": uname, "password": "Guest@123", "role_codes": ["guest"]},
        headers=hdr,
    )
    assert r.status_code == 200
    try:
        gtok = _login(client, uname, "Guest@123").json()["data"]["access_token"]
        # guest 访问仅超级管理员接口 -> 403
        denied = client.get(BASE + "/system-health", headers={"Authorization": f"Bearer {gtok}"})
        assert denied.status_code == 403
        # 超级管理员访问 -> 200
        ok = client.get(BASE + "/system-health", headers=hdr)
        assert ok.status_code == 200
    finally:
        _cleanup(uname)


def test_login_fail_lock(client):
    uname = "test_lock"
    _cleanup(uname)
    token = _admin_token(client)
    hdr = {"Authorization": f"Bearer {token}"}
    r = client.post(
        BASE + "/register",
        json={"username": uname, "password": "Lock@123", "role_codes": ["guest"]},
        headers=hdr,
    )
    assert r.status_code == 200
    try:
        # 连续 5 次错误密码 -> 触发账户锁定(423)
        last = None
        for _ in range(5):
            last = _login(client, uname, "wrongpass")
        assert last.status_code == 423
        # 即使密码正确，锁定期间也拒绝
        still_locked = _login(client, uname, "Lock@123")
        assert still_locked.status_code == 423
    finally:
        _cleanup(uname)


def test_refresh_token(client):
    data = _login(client, *ADMIN).json()["data"]
    r = client.post(BASE + "/refresh", json={"refresh_token": data["refresh_token"]})
    assert r.status_code == 200
    assert r.json()["data"]["access_token"]


def test_roles_page_and_batch_delete(client):
    token = _admin_token(client)
    h = {"Authorization": f"Bearer {token}"}
    created: list[int] = []

    try:
        # 建两个非系统角色（编码带随机前缀，避免与历史残留冲突）
        for i in range(2):
            suffix = secrets.token_hex(3)
            r = client.post(
                BASE + "/roles",
                headers=h,
                json={
                    "name": f"批量角色_{suffix}_{i}",
                    "code": f"batch_role_{suffix}_{i}",
                    "data_scope": 4,
                },
            )
            assert r.status_code == 200, r.text
            created.append(r.json()["data"]["id"])

        # 分页端点（保留 /roles 扁平端点供下拉消费）
        p = client.get(BASE + "/roles/page?page=1&size=2", headers=h)
        assert p.status_code == 200, p.text
        body = p.json()["data"]
        assert body["page"] == 1 and body["size"] == 2
        assert len(body["items"]) == 2
        assert body["total"] >= 2

        # 找一个系统内置角色，批量删除时应被跳过
        flat = client.get(BASE + "/roles", headers=h).json()["data"]
        sys_role = next((x for x in flat if x["is_system"]), None)
        payload = list(created) + ([sys_role["id"]] if sys_role else [])
        bd = client.post(BASE + "/roles/batch-delete", headers=h, json={"ids": payload})
        assert bd.status_code == 200, bd.text
        res = bd.json()["data"]
        assert res["deleted"] == 2
        assert res["skipped"] == (1 if sys_role else 0)
        assert res["total"] == len(payload)
    finally:
        # 清理本次创建的自定义角色（系统角色不可删，已自动跳过）
        if created:
            client.post(
                BASE + "/roles/batch-delete",
                headers=h,
                json={"ids": created},
            )
