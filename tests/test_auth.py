"""RBAC 认证与权限控制端到端测试。

覆盖：登录鉴权、令牌校验、当前用户、权限拦截、角色拦截、登录失败锁定、刷新令牌。
测试会向开发库写入/清理专用测试账号（test_ 前缀），不影响种子数据。
"""

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
