"""统一时钟工具：把「当前时间/当日边界」的时区语义显式绑定业务时区（默认 Asia/Shanghai）。

背景（#11 时区混杂治理）：
项目此前散落 ``datetime.now()`` / ``datetime.combine(date.today(), ...)`` 等**依赖服务器
本地 locale 时区**的写法，与 PG timestamptz(aware) 列混比。只要部署机 locale 时区不是
Asia/Shanghai（云主机常默认 UTC），"今日告警""计划时间窗判定"就会整体漂移 8 小时。

本模块提供**显式绑定业务时区**的时间入口，消除对运行环境 locale 的隐式依赖：

- :func:`now_local` / :func:`day_start_local` / :func:`day_end_local` 返回 **aware** 值，
  用于与 ``DateTime(timezone=True)`` 列（如 ``Alarm.alarm_time``）比较——psycopg2 传 aware
  给 timestamptz 时按**绝对时刻**比较，与 PG session 时区无关，健壮。
- :func:`now_naive_local` / :func:`today_local` 用于与**仍为 naive 的列**（如
  ``WorkPlan.plan_start/plan_end``）比较，保证两侧同为「北京时间的 naive」，避免
  naive↔aware 混比 TypeError；同时不再依赖服务器 locale。

注：``WorkPlan.plan_start/plan_end`` 彻底 aware 化（列类型 naive→timestamptz + 数据迁移）
属更大改动，另行立项；本模块先消除 locale 依赖这一活跃风险源。
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

#: 业务时区（涉铁监控平台运营地）。集中一处，便于将来配置化。
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def now_local() -> datetime:
    """当前时刻（aware，绑定业务时区）。用于与 timestamptz 列比较/写入。"""
    return datetime.now(LOCAL_TZ)


def now_naive_local() -> datetime:
    """当前时刻的 naive 表示（业务时区的墙上时间，去掉 tzinfo）。

    用于与仍为 naive 的列（``WorkPlan.plan_start/plan_end``）比较，保证两侧
    同为「北京时间的 naive」，且不依赖服务器 locale 时区。
    """
    return datetime.now(LOCAL_TZ).replace(tzinfo=None)


def today_local() -> date:
    """业务时区下的今天（date）。替代依赖 locale 的 ``date.today()``。"""
    return datetime.now(LOCAL_TZ).date()


def day_start_local(d: date | None = None) -> datetime:
    """某日 00:00:00 的 aware 边界（业务时区）；缺省取今天。"""
    d = d or today_local()
    return datetime.combine(d, time.min, tzinfo=LOCAL_TZ)


def day_end_local(d: date | None = None) -> datetime:
    """某日 23:59:59.999999 的 aware 边界（业务时区）；缺省取今天。"""
    d = d or today_local()
    return datetime.combine(d, time.max, tzinfo=LOCAL_TZ)


def ensure_aware_local(dt: datetime | None) -> datetime | None:
    """把可能为 naive 的 datetime 视作业务时区补全为 aware；已 aware 原样返回。

    用于稳健处理外部传入（如用户 ISO 字符串）可能缺时区的时间边界；
    传入 ``None``（表示「无时间窗」）时原样返回 ``None``。
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TZ)
    return dt
