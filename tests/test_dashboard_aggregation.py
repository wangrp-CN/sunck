"""大屏 /stats 聚合下推测试（优化项 #5）。

验证新增的 ``aggregate_alarms_sql``（GROUP BY 下推，零内存拉取）与原有
``query_alarms_for_report(50000) + aggregate_alarms``（内存聚合）在**同一查询范围**
下产出逐字段完全一致的结果（Golden Master 对比）：total / by_period(含堆叠子维)
/ by_level / by_handle_status。

这直接证明性能改造（不再拉 5 万条完整对象进内存）不改变大屏任何数字与趋势图联动
语义。bogus 粒度应安全回退 day，与显式 day 结果一致。
"""

from datetime import datetime

import pytest

from app.core.data_scope import DataScope
from app.core.database import SessionLocal
from app.service.alarm_service import (
    aggregate_alarms,
    aggregate_alarms_sql,
    query_alarms_for_report,
)

# 宽窗口覆盖全库，确保 old/new 在同一查询范围内对比
_S = datetime(2000, 1, 1)
_E = datetime(2100, 12, 31, 23, 59, 59)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _compare(old: dict, new: dict):
    assert new["total"] == old["total"], "total 不一致"
    assert {p["period"]: p["count"] for p in old["by_period"]} == {
        p["period"]: p["count"] for p in new["by_period"]
    }, "by_period 计数不一致"
    assert {d["key"]: d["count"] for d in old["by_level"]} == {
        d["key"]: d["count"] for d in new["by_level"]
    }, "by_level 不一致"
    assert {d["key"]: d["count"] for d in old["by_handle_status"]} == {
        d["key"]: d["count"] for d in new["by_handle_status"]
    }, "by_handle_status 不一致"
    # 趋势图堆叠子维度（by_type/by_level）也必须逐桶一致
    for po, pn in zip(
        sorted(old["by_period"], key=lambda x: x["period"]),
        sorted(new["by_period"], key=lambda x: x["period"]),
    ):
        assert po["period"] == pn["period"]
        assert po["count"] == pn["count"]
        assert po["by_type"] == pn["by_type"], f"周期 {po['period']} by_type 不一致"
        assert po["by_level"] == pn["by_level"], f"周期 {po['period']} by_level 不一致"


def test_day_aggregation_matches(db_session):
    scope = DataScope(is_all=True)
    old = aggregate_alarms(
        query_alarms_for_report(db_session, scope, start=_S, end=_E, limit=50000), "day"
    )
    new = aggregate_alarms_sql(db_session, scope, start=_S, end=_E, granularity="day")
    _compare(old, new)


def test_month_aggregation_matches(db_session):
    scope = DataScope(is_all=True)
    old = aggregate_alarms(
        query_alarms_for_report(db_session, scope, start=_S, end=_E, limit=50000), "month"
    )
    new = aggregate_alarms_sql(db_session, scope, start=_S, end=_E, granularity="month")
    _compare(old, new)


def test_week_aggregation_matches(db_session):
    scope = DataScope(is_all=True)
    old = aggregate_alarms(
        query_alarms_for_report(db_session, scope, start=_S, end=_E, limit=50000), "week"
    )
    new = aggregate_alarms_sql(db_session, scope, start=_S, end=_E, granularity="week")
    _compare(old, new)


def test_granularity_bogus_falls_back_to_day(db_session):
    """非法粒度应安全回退 day，与显式 day 结果一致（容错，不报错）。"""
    scope = DataScope(is_all=True)
    new_bogus = aggregate_alarms_sql(db_session, scope, start=_S, end=_E, granularity="bogus")
    new_day = aggregate_alarms_sql(db_session, scope, start=_S, end=_E, granularity="day")
    _compare(new_bogus, new_day)
    assert len(new_day["by_period"]) > 0, "聚合应返回非空周期分布"
