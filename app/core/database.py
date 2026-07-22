"""数据库引擎与会话（SQLAlchemy 2.0，同步驱动）。

说明：
- 引擎在导入时创建，但**不会主动连接数据库**，应用可在无 DB 环境下启动。
- 业务代码通过 `Depends(get_db)` 获取会话；迁移由 Alembic 基于 `app.model` 的
  `Base.metadata` 生成（见 alembic/env.py）。
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

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
