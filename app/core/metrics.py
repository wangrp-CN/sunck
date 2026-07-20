"""Prometheus 业务指标集中定义。

模块在导入时即把下列指标注册到 prometheus_client 默认 REGISTRY，
`/metrics` 端点调用 `generate_latest()` 即可一次性导出全部指标。

import 方式：
    from app.core.metrics import HTTP_REQUEST_COUNT, ALARM_CREATED_TOTAL, ...

注意：指标为模块级单例，Python import 缓存保证只注册一次；
不要在运行时反复 import 触发重复注册（会抛 DuplicateMetricError）。
"""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# HTTP 请求：计数 + 时延分布
# ---------------------------------------------------------------------------
HTTP_REQUEST_COUNT = Counter(
    "http_requests_total",
    "HTTP 请求总数（按方法/路径/状态码）",
    ["method", "path", "status"],
)

HTTP_REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP 请求时延分布（秒，按方法/路径）",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ---------------------------------------------------------------------------
# 告警产生：实时链路经规则引擎落库的告警数
# ---------------------------------------------------------------------------
ALARM_CREATED_TOTAL = Counter(
    "alarms_created_total",
    "告警产生总数（经规则引擎落库，按类型/级别）",
    ["alarm_type", "alarm_level"],
)

# ---------------------------------------------------------------------------
# MQTT 上行报文：设备上报报文数
# ---------------------------------------------------------------------------
MQTT_MESSAGES_TOTAL = Counter(
    "mqtt_messages_total",
    "MQTT 设备上行报文总数（按设备类型）",
    ["device_type"],
)

# ---------------------------------------------------------------------------
# WebSocket 在线连接数（Gauge，set 当前真实值）
# ---------------------------------------------------------------------------
WS_CONNECTIONS = Gauge(
    "ws_connections",
    "当前 WebSocket 在线连接数",
)
