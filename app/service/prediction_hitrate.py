"""预测命中率度量（预测性预警闭环验证）。

回答「Phase 5 预测性预警到底准不准」：对每条**实际触发了 predictive_alert 的预测**
（越阈判据复用 ``forecast_service._predictive_breach``），在其预测窗口
``[forecast_at, forecast_at + horizon_days]`` 内回查 ``risk_health_snapshot`` 实际序列，
判定是否如期越阈：

- 命中(hit)：窗口内实际值越阈（risk_index ≥ 预测值 / health_score ≤ 预测值）；
- 误报(false_positive)：窗口已结束但从未越阈；
- 待验证(pending)：窗口尚未结束，暂不计入命中率分母。

聚合命中率、平均提前量(lead time)、按指标/项目分布。所有查询经 ``apply_data_scope``
数据隔离，只读（由调用方传 read 会话）。

事实源：``Forecast``（预测值/目标时刻/跨度/指标/对象）+ ``RiskHealthSnapshot``（每日实际读数）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.core.data_scope import DataScope, apply_data_scope
from app.model.forecast import Forecast
from app.model.snapshot import RiskHealthSnapshot
from app.service import forecast_metrics as fm
from app.service.forecast_service import _predictive_breach


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _zero_metric(metric: str) -> dict[str, Any]:
    return {
        "metric": metric,
        "verifiable": 0,
        "hits": 0,
        "false_positives": 0,
        "pending": 0,
        "hit_rate": None,
    }


def _zero_project(project_id: int) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "verifiable": 0,
        "hits": 0,
        "false_positives": 0,
        "pending": 0,
        "hit_rate": None,
    }


def _verify(fc: Forecast, db) -> tuple[bool, float | None]:
    """在预测窗口内回查实际序列，返回 (是否命中, 提前量小时数|None)。"""
    col = fm.metric_column(fc.metric)
    if col is None or fc.forecast_at is None or fc.forecast_value is None:
        return False, None
    window_end = fc.forecast_at + timedelta(days=fc.horizon_days)
    rows = db.execute(
        select(RiskHealthSnapshot.snapshot_at, col)
        .where(
            RiskHealthSnapshot.scope_type == fc.scope_type,
            RiskHealthSnapshot.ref_id == fc.ref_id,
            RiskHealthSnapshot.snapshot_at >= fc.forecast_at,
            RiskHealthSnapshot.snapshot_at <= window_end,
            col.is_not(None),
        )
        .order_by(RiskHealthSnapshot.snapshot_at.asc())
    ).all()
    low_good = fm.direction_of(fc.metric) == fm.DIRECTION_LOW_GOOD
    for snap_at, val in rows:
        if val is None:
            continue
        if (val >= fc.forecast_value) if low_good else (val <= fc.forecast_value):
            lead = (snap_at - fc.forecast_at).total_seconds() / 3600.0
            if lead < 0:
                lead = 0.0
            return True, lead
    return False, None


def compute_prediction_hitrate(
    db,
    scope: DataScope,
    *,
    days: int = 30,
    project_id: int | None = None,
    metric: str | None = None,
) -> dict[str, Any]:
    """计算预测命中率报表。

    仅统计「实际触发预测性预警的预测」（越阈），窗口已结束者计入命中率分母，
    窗口未结束者列为 pending。
    """
    now = _now()
    stmt = select(Forecast)
    if project_id is not None:
        stmt = stmt.where(Forecast.project_id == project_id)
    if metric:
        stmt = stmt.where(Forecast.metric == metric)
    stmt = apply_data_scope(stmt, Forecast, scope)
    forecasts = db.scalars(stmt).all()

    verifiable = hits = false_positives = pending = 0
    lead_times: list[float] = []
    by_metric: dict[str, dict] = {}
    by_project: dict[int, dict] = {}

    for fc in forecasts:
        if fc.forecast_value is None or fc.forecast_level is None or fc.forecast_at is None:
            continue
        breach, _ = _predictive_breach(fc)
        if not breach:
            continue  # 只统计真正预警了的预测

        is_verifiable = (fc.forecast_at + timedelta(days=fc.horizon_days)) <= now
        bm = by_metric.setdefault(fc.metric, _zero_metric(fc.metric))
        pid = fc.project_id or 0
        bp = by_project.setdefault(pid, _zero_project(pid))

        if not is_verifiable:
            pending += 1
            bm["pending"] += 1
            bp["pending"] += 1
            continue

        verifiable += 1
        bm["verifiable"] += 1
        bp["verifiable"] += 1
        hit, lead = _verify(fc, db)
        if hit:
            hits += 1
            bm["hits"] += 1
            bp["hits"] += 1
            if lead is not None:
                lead_times.append(lead)
        else:
            false_positives += 1
            bm["false_positives"] += 1
            bp["false_positives"] += 1

    hit_rate = (hits / verifiable) if verifiable else None
    avg_lead_hours = (sum(lead_times) / len(lead_times)) if lead_times else None
    for m in by_metric.values():
        m["hit_rate"] = (m["hits"] / m["verifiable"]) if m["verifiable"] else None
    for p in by_project.values():
        p["hit_rate"] = (p["hits"] / p["verifiable"]) if p["verifiable"] else None

    return {
        "verifiable": verifiable,
        "hits": hits,
        "false_positives": false_positives,
        "pending": pending,
        "hit_rate": hit_rate,
        "avg_lead_hours": avg_lead_hours,
        "by_metric": by_metric,
        "by_project": list(by_project.values()),
        "period_days": days,
        "generated_at": now.isoformat(),
    }
