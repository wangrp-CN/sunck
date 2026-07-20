"""Prometheus 业务指标埋点验证。

覆盖四类业务指标是否在 /metrics 暴露，以及 HTTP 中间件是否正确
计数、是否排除自监控端点（/metrics、/health）。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_metrics_exposes_business_metrics(client):
    """/metrics 应暴露 HTTP/告警/MQTT/WS 四类业务指标（含进程指标）。"""
    # 触发一个会被统计的 HTTP 请求（/openapi.json 非排除端点）
    client.get("/openapi.json")
    resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.content
    for name in (
        b"http_requests_total",
        b"http_request_duration_seconds",
        b"alarms_created_total",
        b"mqtt_messages_total",
        b"ws_connections",
    ):
        assert name in body, f"指标缺失: {name}"


def test_http_middleware_counts_requests(client):
    """HTTP 中间件应把 /openapi.json 计入 http_requests_total。"""
    client.get("/openapi.json")
    body = client.get("/metrics").content
    assert b'path="/openapi.json"' in body


def test_metrics_excludes_self_scrape(client):
    """/metrics 与 /health 自身不应被计入 http_requests_total。"""
    body = client.get("/metrics").content
    assert b'path="/metrics"' not in body
    assert b'path="/health"' not in body
