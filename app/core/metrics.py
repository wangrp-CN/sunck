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
# 智能核心 v2：项目风险指数（Grafana 可据此配置阈值告警规则）
# ---------------------------------------------------------------------------
PROJECT_RISK_INDEX = Gauge(
    "project_risk_index",
    "项目最新风险指数(0-100)，供 Grafana 阈值告警；由快照任务按最新快照刷新",
    ["project_id", "project_name"],
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

# ---------------------------------------------------------------------------
# 上行 ingestion 异步调度（阶段3 待办收敛）
# ---------------------------------------------------------------------------
INGEST_ENQUEUED_TOTAL = Counter(
    "ingest_enqueued_total",
    "上行报文进入异步队列的总数",
)

INGEST_PROCESSED_TOTAL = Counter(
    "ingest_processed_total",
    "上行报文经工作线程处理完成的总数（含同步回退）",
)

INGEST_ERRORS_TOTAL = Counter(
    "ingest_errors_total",
    "上行报文处理异常总数（落库/规则/告警失败，已记日志）",
)

INGEST_INLINE_TOTAL = Counter(
    "ingest_inline_total",
    "队列满时回退同步处理的总数（背压触发）",
)

INGEST_QUEUE_SIZE = Gauge(
    "ingest_queue_size",
    "当前异步 ingestion 队列积压长度",
)

INGEST_PROCESS_LATENCY = Histogram(
    "ingest_process_duration_seconds",
    "单条上行报文处理时延（秒，含落库/规则/告警/推送）",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ---------------------------------------------------------------------------
# 数据库连接池（基础设施审计 · pool 监控盲区补齐）
# 饱和度主信号：db_pool_checkedout 接近 db_pool_capacity 即池将耗尽（请求开始排队）。
# 数值在 /metrics 抓取时由 update_pool_metrics() 从 engine.pool 实时写入；
# checkout 计数与物理连接建立时延经 database.py 注册的 PoolEvents 采集。
# ---------------------------------------------------------------------------
DB_POOL_CHECKEDOUT = Gauge(
    "db_pool_checkedout",
    "当前已借出的数据库连接数（按池 api/ingest 区分）",
    ["pool"],
)

DB_POOL_CHECKEDIN = Gauge(
    "db_pool_checkedin",
    "当前池中空闲的数据库连接数",
    ["pool"],
)

DB_POOL_SIZE = Gauge(
    "db_pool_size",
    "连接池基线大小（pool_size）",
    ["pool"],
)

DB_POOL_OVERFLOW = Gauge(
    "db_pool_overflow",
    "连接池溢出数（SQLAlchemy 原生：空闲时为负值，表示尚未用满基线）",
    ["pool"],
)

DB_POOL_CAPACITY = Gauge(
    "db_pool_capacity",
    "连接池总容量（pool_size + max_overflow），饱和度 = checkedout / capacity",
    ["pool"],
)

DB_POOL_CHECKOUT_TOTAL = Counter(
    "db_pool_checkout_total",
    "连接借出总次数（按池区分，反映连接获取频率）",
    ["pool"],
)

DB_POOL_CONNECT_LATENCY = Histogram(
    "db_pool_connect_latency_seconds",
    "新建物理数据库连接时延（秒，按池区分；池溢出被迫新建连接时上升）",
    ["pool"],
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5),
)


def update_pool_metrics() -> None:
    """抓取 /metrics 前刷新连接池实时指标（懒加载引擎，避免循环导入）。"""
    from app.core.database import engine, ingest_engine, read_engine, settings

    def _set(label: str, pool, capacity: int) -> None:
        try:
            DB_POOL_CHECKEDOUT.labels(pool=label).set(pool.checkedout())
            DB_POOL_CHECKEDIN.labels(pool=label).set(pool.checkedin())
            DB_POOL_SIZE.labels(pool=label).set(pool.size())
            DB_POOL_OVERFLOW.labels(pool=label).set(pool.overflow())
            DB_POOL_CAPACITY.labels(pool=label).set(capacity)
        except Exception:  # noqa: BLE001
            pass

    _set("api", engine.pool, settings.db_pool_size + settings.db_max_overflow)
    _set(
        "ingest",
        ingest_engine.pool,
        settings.ingest_db_pool_size + settings.ingest_db_max_overflow,
    )
    _set(
        "read",
        read_engine.pool,
        settings.read_db_pool_size + settings.read_db_max_overflow,
    )
