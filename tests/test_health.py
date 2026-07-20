"""基础结构冒烟测试：验证应用可装配、接口可路由。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app

MODULES = [
    "devices",
    "persons",
    "machines",
    "fences",
    "jobs",
    "alarms",
    "dashboard",
]


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_docs(client):
    assert client.get("/docs").status_code == 200


@pytest.mark.parametrize("module", MODULES)
def test_module_ping(client, module):
    r = client.get(f"/api/v1/{module}/ping")
    assert r.status_code == 200
    assert r.json()["status"] in ("skeleton", "ready")
