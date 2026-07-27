"""闭环效能度量：量化「监测 → 异常 → 告警 → 派单 → 治理」全链路的有效性。

供大屏「闭环效能」卡使用，回答四类问题：
- 风暴抑制到底压掉了多少同源重复告警（抑制率）；
- 告警平均多久被处置掉（MTTR，近似口径）；
- 派单是否在时限内闭环（SLA 达成率 + 平均闭环周期）；
- 隐患治理闭环率，以及趋势异常引擎对告警流的贡献占比。

所有查询经 ``apply_data_scope`` 数据范围隔离，只读（由调用方传 read 会话）。
软删除模型（dispatch_order / hazard）额外过滤 ``is_deleted``；alarm 无软删列。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.clock import day_end_local, day_start_local
from app.core.data_scope import DataScope, apply_data_scope
from app.model.alarm import Alarm
from app.model.dispatch import DispatchOrder
from app.model.hazard import Hazard

# 视为「已处置」的告警处理状态（用于 MTTR / 处置率分母）
_RESOLVED_STATUSES = ("已处理", "已忽略", "已确认")
_DISPATCH_CLOSED = "已闭环"
_HAZARD_CLOSED = "已销号"


def _range(days: int) -> tuple[datetime, datetime]:
    """返回 [start, end] aware 区间：end=今日北京日界末，start=end 前 days-1 天（含今日共 days 天）。"""
    end = day_end_local()
    start = day_start_local() - timedelta(days=max(days - 1, 0))
    return start, end


def _scalar_int(db, stmt) -> int:
    return int(db.scalar(stmt) or 0)


def _scalar_float(db, stmt) -> float:
    return float(db.scalar(stmt) or 0.0)


def compute_effectiveness(db, scope: DataScope, days: int = 30) -> dict:
    """计算闭环效能指标，返回结构化的 dict（数值已四舍五入）。"""
    start, end = _range(days)

    # 1) 告警风暴抑制率：区间内被合并掉的重复告警数 / (实际告警 + 被抑制)
    suppressed = _scalar_int(
        db,
        apply_data_scope(
            select(func.coalesce(func.sum(Alarm.suppressed_count), 0))
            .select_from(Alarm)
            .where(Alarm.alarm_time >= start),
            Alarm,
            scope,
        ),
    )
    alarms = _scalar_int(
        db,
        apply_data_scope(
            select(func.count()).select_from(Alarm).where(Alarm.alarm_time >= start),
            Alarm,
            scope,
        ),
    )
    denom = alarms + suppressed
    storm_rate = round(suppressed / denom * 100, 1) if denom else 0.0

    # 2) 告警处置 MTTR（近似）：updated_at - alarm_time（仅已处置类，且 updated_at>=alarm_time）
    #    Alarm 无独立 handle_time，updated_at 近似最后处置时间，属保守估算，已在口径文档标注。
    mttr_hours = _scalar_float(
        db,
        apply_data_scope(
            select(func.avg(func.extract("epoch", Alarm.updated_at - Alarm.alarm_time)) / 3600.0)
            .select_from(Alarm)
            .where(
                Alarm.alarm_time >= start,
                Alarm.handle_status.in_(_RESOLVED_STATUSES),
                Alarm.alarm_time.isnot(None),
                Alarm.updated_at.isnot(None),
                Alarm.updated_at >= Alarm.alarm_time,
            ),
            Alarm,
            scope,
        ),
    )
    resolved = _scalar_int(
        db,
        apply_data_scope(
            select(func.count())
            .select_from(Alarm)
            .where(Alarm.alarm_time >= start, Alarm.handle_status.in_(_RESOLVED_STATUSES)),
            Alarm,
            scope,
        ),
    )
    resolution_rate = round(resolved / alarms * 100, 1) if alarms else 0.0

    # 3) 派单 SLA：已闭环工单中，闭环时间 <= 处理时限 的比例 + 平均闭环周期
    closed = _scalar_int(
        db,
        apply_data_scope(
            select(func.count())
            .select_from(DispatchOrder)
            .where(
                DispatchOrder.is_deleted.is_(False),
                DispatchOrder.closed_at >= start,
                DispatchOrder.status == _DISPATCH_CLOSED,
            ),
            DispatchOrder,
            scope,
        ),
    )
    on_time = _scalar_int(
        db,
        apply_data_scope(
            select(func.count())
            .select_from(DispatchOrder)
            .where(
                DispatchOrder.is_deleted.is_(False),
                DispatchOrder.closed_at >= start,
                DispatchOrder.status == _DISPATCH_CLOSED,
                DispatchOrder.closed_at <= DispatchOrder.deadline,
                DispatchOrder.deadline.isnot(None),
            ),
            DispatchOrder,
            scope,
        ),
    )
    closed_with_deadline = _scalar_int(
        db,
        apply_data_scope(
            select(func.count())
            .select_from(DispatchOrder)
            .where(
                DispatchOrder.is_deleted.is_(False),
                DispatchOrder.closed_at >= start,
                DispatchOrder.status == _DISPATCH_CLOSED,
                DispatchOrder.deadline.isnot(None),
            ),
            DispatchOrder,
            scope,
        ),
    )
    sla_rate = round(on_time / closed_with_deadline * 100, 1) if closed_with_deadline else 0.0
    cycle_hours = _scalar_float(
        db,
        apply_data_scope(
            select(
                func.avg(func.extract("epoch", DispatchOrder.closed_at - DispatchOrder.created_at))
                / 3600.0
            )
            .select_from(DispatchOrder)
            .where(
                DispatchOrder.is_deleted.is_(False),
                DispatchOrder.closed_at >= start,
                DispatchOrder.status == _DISPATCH_CLOSED,
            ),
            DispatchOrder,
            scope,
        ),
    )

    # 4) 隐患治理闭环率 + 按期销号率
    hz_total = _scalar_int(
        db,
        apply_data_scope(
            select(func.count())
            .select_from(Hazard)
            .where(Hazard.is_deleted.is_(False), Hazard.created_at >= start),
            Hazard,
            scope,
        ),
    )
    hz_closed = _scalar_int(
        db,
        apply_data_scope(
            select(func.count())
            .select_from(Hazard)
            .where(
                Hazard.is_deleted.is_(False),
                Hazard.created_at >= start,
                Hazard.status == _HAZARD_CLOSED,
            ),
            Hazard,
            scope,
        ),
    )
    closure_rate = round(hz_closed / hz_total * 100, 1) if hz_total else 0.0
    hz_ontime = _scalar_int(
        db,
        apply_data_scope(
            select(func.count())
            .select_from(Hazard)
            .where(
                Hazard.is_deleted.is_(False),
                Hazard.created_at >= start,
                Hazard.status == _HAZARD_CLOSED,
                Hazard.closed_at <= Hazard.due_at,
                Hazard.due_at.isnot(None),
            ),
            Hazard,
            scope,
        ),
    )
    hz_with_due = _scalar_int(
        db,
        apply_data_scope(
            select(func.count())
            .select_from(Hazard)
            .where(
                Hazard.is_deleted.is_(False),
                Hazard.created_at >= start,
                Hazard.status == _HAZARD_CLOSED,
                Hazard.due_at.isnot(None),
            ),
            Hazard,
            scope,
        ),
    )
    hz_ontime_rate = round(hz_ontime / hz_with_due * 100, 1) if hz_with_due else 0.0

    # 5) 异常贡献：趋势异常告警占告警流比例 + 由跨设备共因发起的派单数
    anomaly_alarms = _scalar_int(
        db,
        apply_data_scope(
            select(func.count())
            .select_from(Alarm)
            .where(Alarm.alarm_time >= start, Alarm.alarm_type == "trend_anomaly"),
            Alarm,
            scope,
        ),
    )
    anomaly_share = round(anomaly_alarms / alarms * 100, 1) if alarms else 0.0
    corr_dispatch = _scalar_int(
        db,
        apply_data_scope(
            select(func.count())
            .select_from(DispatchOrder)
            .where(
                DispatchOrder.is_deleted.is_(False),
                DispatchOrder.created_at >= start,
                DispatchOrder.source_type == "correlation",
            ),
            DispatchOrder,
            scope,
        ),
    )

    return {
        "days": days,
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "storm": {
            "suppressed": suppressed,
            "alarms": alarms,
            "rate_pct": storm_rate,
        },
        "mttr": {
            "avg_hours": round(mttr_hours, 1),
            "resolved": resolved,
            "resolution_rate_pct": resolution_rate,
        },
        "dispatch_sla": {
            "closed": closed,
            "on_time": on_time,
            "sla_rate_pct": sla_rate,
            "avg_cycle_hours": round(cycle_hours, 1),
        },
        "hazard": {
            "total": hz_total,
            "closed": hz_closed,
            "closure_rate_pct": closure_rate,
            "on_time_rate_pct": hz_ontime_rate,
        },
        "anomaly": {
            "alarms": anomaly_alarms,
            "share_pct": anomaly_share,
            "correlation_dispatches": corr_dispatch,
        },
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
