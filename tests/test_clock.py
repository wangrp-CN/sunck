"""时区治理（#11）回归测试。

守护：时间语义显式绑定业务时区（Asia/Shanghai），消除对服务器 locale 时区的隐式依赖。
- clock.now_naive_local 返回「北京时间的 naive」（无 tzinfo），供与 naive 列比较；
- clock 的日边界为 aware（业务时区），供与 timestamptz 列比较；
- rule_engine_v2 计划时间窗判定用 naive 北京时间（与 naive 的 plan_start/plan_end 同侧）；
- dashboard 的 _resolve_trend_window 边界为 aware（不依赖 PG session tz）。
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.api.v1.dashboard import _resolve_trend_window
from app.core import clock
from app.core.rule_engine_v2 import is_plan_active_now


def test_now_naive_local_is_naive_and_beijing():
    """now_naive_local 无 tzinfo，且等于当前北京墙上时间（不受服务器 locale 影响）。"""
    n = clock.now_naive_local()
    assert n.tzinfo is None, "与 naive 列比较需 naive"
    # 与 aware 北京时间的墙上时间对齐（容忍 5s 执行漂移）
    beijing_wall = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    assert abs((beijing_wall - n).total_seconds()) < 5


def test_now_local_and_day_bounds_are_aware():
    """now_local / 日边界均为 aware（业务时区），供与 timestamptz 列比较。"""
    assert clock.now_local().tzinfo is not None
    ds = clock.day_start_local()
    de = clock.day_end_local()
    assert ds.tzinfo is not None and de.tzinfo is not None
    assert ds.hour == 0 and ds.minute == 0
    assert de.hour == 23 and de.minute == 59
    # 同一日的起止（同一 UTC 偏移下）应约相差 1 天
    assert de > ds


def test_ensure_aware_local_backfills_naive():
    """ensure_aware_local 把 naive 视作业务时区补全；已 aware 原样返回。"""
    naive = datetime(2026, 7, 20, 8, 0, 0)
    aware = clock.ensure_aware_local(naive)
    assert aware.tzinfo is not None
    already = datetime(2026, 7, 20, 8, 0, 0, tzinfo=timezone.utc)
    assert clock.ensure_aware_local(already) is already


def test_resolve_trend_window_returns_aware_bounds():
    """dashboard 默认趋势窗边界应为 aware（消除对 PG session tz 的隐式依赖）。"""
    for gran in ("day", "week", "month"):
        s, e = _resolve_trend_window(gran, None, None)
        assert s.tzinfo is not None, f"{gran} start 应为 aware"
        assert e.tzinfo is not None, f"{gran} end 应为 aware"
        assert s <= e


def test_resolve_trend_window_backfills_user_naive_iso():
    """用户传入缺时区的 ISO 时间窗，应按业务时区补全为 aware。"""
    s, e = _resolve_trend_window("day", "2026-07-01T00:00:00", "2026-07-20T23:59:59")
    assert s.tzinfo is not None and e.tzinfo is not None


class _Plan:
    """轻量计划桩：仅承载 is_plan_active_now 读取的属性。"""

    def __init__(self, is_start, status, plan_start=None, plan_end=None):
        self.is_start = is_start
        self.status = status
        self.plan_start = plan_start
        self.plan_end = plan_end


def test_is_plan_active_now_uses_naive_beijing_default():
    """默认 now 为 naive 北京时间：与 naive 的 plan_start/plan_end 比较不抛 TypeError。"""
    now_naive = clock.now_naive_local()
    plan = _Plan(
        is_start=True,
        status="执行中",
        plan_start=now_naive - timedelta(hours=1),
        plan_end=now_naive + timedelta(hours=1),
    )
    # 不显式传 now，走内部 now_naive_local 默认值
    assert is_plan_active_now(plan) is True

    expired = _Plan(
        is_start=True,
        status="执行中",
        plan_start=now_naive - timedelta(hours=2),
        plan_end=now_naive - timedelta(hours=1),
    )
    assert is_plan_active_now(expired) is False
