"""API 限流中间件专项测试（不依赖真实 Redis）。"""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core import ratelimit
from app.main import app


class _FakeRedis:
    """极简内存 Redis：仅实现限流所需的 incr/expire。"""

    def __init__(self):
        self._data: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self._data[key] = self._data.get(key, 0) + 1
        return self._data[key]

    def expire(self, key: str, ttl: int) -> bool:  # noqa: ARG002
        return True


@pytest.fixture
def client(monkeypatch):
    # 启用限流，并注入内存假 Redis（与真实代码解耦，结果确定）。
    # 全部经 monkeypatch，用例结束后自动还原，避免污染其他测试。
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_window_seconds", 60)
    monkeypatch.setattr(settings, "rate_limit_login", 3)
    monkeypatch.setattr(settings, "rate_limit_captcha", 2)
    monkeypatch.setattr(settings, "rate_limit_default", 5)
    fake = _FakeRedis()
    monkeypatch.setattr(ratelimit, "get_redis_client", lambda: fake)
    with TestClient(app) as c:
        yield c


def test_login_rate_limit_blocks_after_threshold(client):
    # 前 3 次应被放行（返回非 429，具体由 login 端点决定）
    for _ in range(3):
        r = client.post(
            "/api/v1/auth/login",
            json={"username": "x", "password": "y"},
            headers={"X-Forwarded-For": "203.0.113.99"},
        )
        assert r.status_code != 429, r.text
    # 第 4 次起触发限流
    r = client.post(
        "/api/v1/auth/login",
        json={"username": "x", "password": "y"},
        headers={"X-Forwarded-For": "203.0.113.99"},
    )
    assert r.status_code == 429
    assert r.json()["code"] == 429


def test_exempt_paths_not_limited(client):
    # /health 不受限，连续多次仍 200
    for _ in range(10):
        r = client.get("/health", headers={"X-Forwarded-For": "203.0.113.98"})
        assert r.status_code == 200
    # /metrics 同样豁免
    r = client.get("/metrics", headers={"X-Forwarded-For": "203.0.113.98"})
    assert r.status_code == 200


def test_captcha_endpoint_stricter_limit(client):
    # captcha 限额=2：前 2 次放行，第 3 次限流
    ip = "203.0.113.97"
    for _ in range(2):
        r = client.get("/api/v1/auth/captcha", headers={"X-Forwarded-For": ip})
        assert r.status_code != 429
    r = client.get("/api/v1/auth/captcha", headers={"X-Forwarded-For": ip})
    assert r.status_code == 429


def test_distinct_ips_isolated(client):
    # 不同 IP 互不干扰：IP-A 已耗尽，IP-B 仍可放行
    ip_a = "203.0.113.10"
    for _ in range(3):
        client.post(
            "/api/v1/auth/login",
            json={"username": "x", "password": "y"},
            headers={"X-Forwarded-For": ip_a},
        )
    r_a = client.post(
        "/api/v1/auth/login",
        json={"username": "x", "password": "y"},
        headers={"X-Forwarded-For": ip_a},
    )
    assert r_a.status_code == 429
    r_b = client.post(
        "/api/v1/auth/login",
        json={"username": "x", "password": "y"},
        headers={"X-Forwarded-For": "203.0.113.11"},
    )
    assert r_b.status_code != 429
