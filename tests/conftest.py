"""pytest 公共夹具（骨架）。"""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

# 测试环境默认关闭登录验证码，避免影响现有登录用例；
# 验证码专项测试（test_captcha.py）会临时开启并自行恢复。
settings.captcha_enabled = False

# 关闭响应级短 TTL 缓存：避免跨用例缓存命中破坏测试隔离
# （同一键在用例间复用会返回陈旧响应，导致断言随机失败）。
settings.resp_cache_enabled = False

# 关闭操作审计中间件：避免用例间审计行累积干扰断言（审计逻辑由专项测试覆盖）。
settings.audit_enabled = False

# 关闭 API 限流中间件：避免并发/重试用例被限流干扰；限流逻辑由专项测试覆盖。
settings.rate_limit_enabled = False


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_token(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin@123456"})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]
