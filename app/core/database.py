"""数据库引擎与会话（SQLAlchemy 2.0，同步驱动）。

说明：
- 引擎在导入时创建，但**不会主动连接数据库**，应用可在无 DB 环境下启动。
- 业务代码通过 `Depends(get_db)` 获取会话；迁移由 Alembic 基于 `app.model` 的
  `Base.metadata` 生成（见 alembic/env.py）。
"""

import time

from sqlalchemy import create_engine
from sqlalchemy import event as _sa_event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.core import metrics as _metrics

# 会话时区固定为业务时区 Asia/Shanghai（#11 时区治理）：
# - naive 的写入（如前端 YYYY-MM-DDTHH:mm:ss）按北京解释，避免部署到 UTC 机整体漂移；
# - timestamptz 读取为北京 aware，与 clock.now_local() 同侧比较，消除 locale 依赖；
# - date_trunc 等聚合按北京切桶，与已上线趋势/计数语义一致。
_SESSION_TZ = "Asia/Shanghai"

engine = create_engine(
    settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=True,
    future=True,
    echo=settings.debug,
    connect_args={"options": f"-c timezone={_SESSION_TZ}"},
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)

# ---------------------------------------------------------------------------
# ingestion 专用连接池（阶段3 待办收敛：维度⑥）
# MQTT 上行落库走独立池，与 HTTP API 流量隔离，避免千台设备洪泛时
# ingestion 抢占 API 连接（配合 app.core.ingest 异步调度层）。
# 总连接估算：N 个 API worker × (db_pool_size+溢出) + 1 个 ingest 池，
# 取较小值并预留 PG max_connections=100 余量。
# ---------------------------------------------------------------------------
ingest_engine = create_engine(
    settings.database_url,
    pool_size=settings.ingest_db_pool_size,
    max_overflow=settings.ingest_db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_recycle=settings.db_pool_recycle,
    pool_pre_ping=True,
    future=True,
    echo=settings.debug,
    connect_args={"options": f"-c timezone={_SESSION_TZ}"},
)

IngestSessionLocal = sessionmaker(
    bind=ingest_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)

# ---------------------------------------------------------------------------
# 读 / 看板独立连接池（基础设施审计 · ③）
# dashboard 大屏聚合 + realtime 实时只读端点走独立池，与 API 写事务池（engine）
# 隔离，避免重查询在高并发下挤占写连接。连接同一 PostgreSQL 实例、同步复制，
# 读池立即可见已提交写，无复制滞后（非只读副本）。
# ---------------------------------------------------------------------------
read_engine = create_engine(
    settings.database_url,
    pool_size=settings.read_db_pool_size,
    max_overflow=settings.read_db_max_overflow,
    pool_timeout=settings.read_db_pool_timeout,
    pool_recycle=settings.read_db_pool_recycle,
    pool_pre_ping=True,
    future=True,
    echo=settings.debug,
    connect_args={"options": f"-c timezone={_SESSION_TZ}"},
)

ReadSessionLocal = sessionmaker(
    bind=read_engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


def get_db() -> Session:
    """FastAPI 依赖：提供数据库会话，异常时统一回滚，请求结束后关闭。

    说明：仅捕获 yield 期间的异常做兜底回滚；已在业务层显式 commit 的固化状态
    不会被回滚，而未提交的挂起改动在异常时回滚，避免半提交脏数据。
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_read_db() -> Session:
    """只读会话依赖：dashboard / realtime 等重读端点使用独立读池，与写事务池隔离。

    说明：读池连接同一 PG 实例，已提交写立即可见；仅用于纯只读查询。
    若后续端点内存在写操作，应使用 get_db（写池）。
    """
    db = ReadSessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 连接池事件（基础设施审计 · pool 监控盲区补齐）
# - checkout：每次借出连接计数（按池区分），反映连接获取频率。
# - do_connect/connect：配对测量「新建物理连接」时延（池溢出被迫新建连接时上升）。
#   注意：池饱和（请求排队等连接）的主信号是 /metrics 中的
#   db_pool_checkedout 接近 db_pool_capacity，而非本时延。
# ---------------------------------------------------------------------------
_connect_starts: dict[int, float] = {}


def _register_pool_events(engine_obj, label: str) -> None:
    # do_connect/connect 是引擎级事件（新建物理连接前后）；
    # checkout 是池级事件（每次从池借出，含复用）。
    def _on_do_connect(dialect, conn_rec, cargs, cparams):
        _connect_starts[id(conn_rec)] = time.perf_counter()

    def _on_connect(dbapi_connection, connection_record):
        start = _connect_starts.pop(id(connection_record), None)
        if start is not None:
            _metrics.DB_POOL_CONNECT_LATENCY.labels(pool=label).observe(time.perf_counter() - start)

    def _on_checkout(dbapi_connection, connection_record, anchor):
        _metrics.DB_POOL_CHECKOUT_TOTAL.labels(pool=label).inc()

    _sa_event.listens_for(engine_obj, "do_connect")(_on_do_connect)
    _sa_event.listens_for(engine_obj, "connect")(_on_connect)
    _sa_event.listens_for(engine_obj.pool, "checkout")(_on_checkout)


_register_pool_events(engine, "api")
_register_pool_events(ingest_engine, "ingest")
_register_pool_events(read_engine, "read")
