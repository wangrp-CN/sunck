"""登录验证码：生成、Redis 存储、登录校验的端到端测试。

默认 conftest 已关闭验证码；本测试临时开启以覆盖真实校验链路。
"""

import base64

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.redis import get_redis_client
from app.main import app

BASE = "/api/v1/auth"


@pytest.fixture
def client():
    # 临时开启验证码，验证后再恢复
    saved = settings.captcha_enabled
    settings.captcha_enabled = True
    with TestClient(app) as c:
        yield c
    settings.captcha_enabled = saved


def _fetch_captcha(client: TestClient):
    r = client.get(BASE + "/captcha")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body["captcha_key"]
    # 校验 base64 PNG 前缀
    assert body["captcha_image"].startswith("data:image/png;base64,")
    # 解码校验图片体积合理
    raw = base64.b64decode(body["captcha_image"].split(",", 1)[1])
    assert len(raw) > 100
    # 校验 Redis 已存储答案
    stored = get_redis_client().get(f"captcha:{body['captcha_key']}")
    assert stored
    return body["captcha_key"], stored


def test_captcha_generated_and_stored(client):
    key, stored = _fetch_captcha(client)
    assert len(stored) == settings.captcha_length


def test_login_requires_captcha(client):
    # 未带验证码 -> 400
    r = client.post(
        BASE + "/login",
        json={"username": "admin", "password": "Admin@123456"},
    )
    assert r.status_code == 400
    assert "验证码" in r.json()["message"]


def test_login_wrong_captcha_rejected(client):
    key, _ = _fetch_captcha(client)
    r = client.post(
        BASE + "/login",
        json={
            "username": "admin",
            "password": "Admin@123456",
            "captcha": "ZZZZ",
            "captcha_key": key,
        },
    )
    assert r.status_code == 400
    assert "验证码" in r.json()["message"]


def test_login_with_correct_captcha(client):
    key, stored = _fetch_captcha(client)
    r = client.post(
        BASE + "/login",
        json={
            "username": "admin",
            "password": "Admin@123456",
            "captcha": stored,  # 大小写不敏感
            "captcha_key": key,
        },
    )
    assert r.status_code == 200
    assert r.json()["data"]["access_token"]
