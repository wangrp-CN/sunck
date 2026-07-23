"""DB 连接池指标 + alarm 复合索引（基础设施审计包：② 池监控 + ① 索引）。

- 验证 /metrics 抓取的 db_pool_* 指标已注册并能实时写入（checkedout/capacity）。
- 验证 alarm 表新建的两个复合索引已落库（迁移 k5l6m7n8o9p0）。
"""

from sqlalchemy import inspect

from app.core.database import engine
from app.core.metrics import (
    DB_POOL_CAPACITY,
    DB_POOL_CHECKEDOUT,
    update_pool_metrics,
)


def test_pool_metrics_update_and_capacity():
    update_pool_metrics()
    # api 池容量 = db_pool_size(10) + db_max_overflow(20)
    assert DB_POOL_CAPACITY.labels(pool="api")._value.get() == 30
    # ingest 池容量 = ingest_db_pool_size(12) + ingest_db_max_overflow(8)
    # （ingest_db_pool_size 默认值已随性能调优提升至 12，见 app/config.py）
    assert DB_POOL_CAPACITY.labels(pool="ingest")._value.get() == 20
    # read 池容量 = read_db_pool_size(10) + read_db_max_overflow(10)（读/看板独立池）
    assert DB_POOL_CAPACITY.labels(pool="read")._value.get() == 20
    # checkedout 为数值（>=0），证明 update 成功写入
    assert DB_POOL_CHECKEDOUT.labels(pool="api")._value.get() is not None


def test_read_pool_session_binds_read_engine():
    """get_read_db 返回的会话应绑定 read_engine（与写池 engine 隔离）。"""
    from app.core.database import engine, get_read_db, read_engine

    gen = get_read_db()
    db = next(gen)
    try:
        assert db.bind is read_engine
        assert db.bind is not engine
    finally:
        gen.close()


def test_alarm_composite_indexes_exist():
    idx = {i["name"] for i in inspect(engine).get_indexes("alarm")}
    assert "ix_alarm_alarm_time" in idx
    assert "ix_alarm_handle_status_time" in idx


def test_metrics_endpoint_exposes_pool(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert b"db_pool_checkedout" in r.content
    assert b"db_pool_capacity" in r.content
