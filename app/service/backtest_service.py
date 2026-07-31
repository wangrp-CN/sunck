"""walk-forward 回测引擎 + A/B 命中率聚合（预测模型升级 + A/B 对照）。

设计：
- ``run_backtest``：对每个历史锚点（anchor_at）用截至该日的快照序列拟合各模型、
  外推 horizon 天得到目标日（forecast_at），**仅保留「会越阈预警」的预测**（与线上
  ``predictive_alert`` 口径一致），回查窗口内实际值判定命中(hit)/误报，落
  ``forecast_backtest`` 表。锚点限定 ``anchor_at <= now - horizon``，保证窗口已结束、
  全部可验证，A/B 分母无歧义。
- ``compute_ab_hitrate``：直接聚合 ``forecast_backtest`` 表，按 model_version 输出命中率 /
  误报率 / 平均提前量，并给出 baseline(challenger) 增量对比。

所有查询经 ``apply_data_scope`` 数据隔离；服务层不 commit，由端点统一提交。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select

from app.config import settings
from app.core.data_scope import DataScope, apply_data_scope
from app.model.forecast_backtest import ForecastBacktest
from app.model.snapshot import RiskHealthSnapshot
from app.service import forecast_models as models_mod
from app.service import forecast_service as svc

METRIC_RISK_INDEX = "risk_index"
METRIC_HEALTH_SCORE = "health_score"

_METRIC_COLUMNS = {
    METRIC_RISK_INDEX: RiskHealthSnapshot.risk_index,
    METRIC_HEALTH_SCORE: RiskHealthSnapshot.health_score,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _verify(
    db, scope_type: str, ref_id: str, metric: str, forecast_at: datetime, horizon: int, value: float
) -> tuple[bool, float | None]:
    """窗口内回查实际值是否如期越阈，返回 (命中, 提前量小时数|None)。"""
    col = _METRIC_COLUMNS.get(metric)
    if col is None or forecast_at is None:
        return False, None
    window_end = forecast_at + timedelta(days=horizon)
    rows = db.execute(
        select(RiskHealthSnapshot.snapshot_at, col)
        .where(
            RiskHealthSnapshot.scope_type == scope_type,
            RiskHealthSnapshot.ref_id == ref_id,
            RiskHealthSnapshot.snapshot_at >= forecast_at,
            RiskHealthSnapshot.snapshot_at <= window_end,
            col.is_not(None),
        )
        .order_by(RiskHealthSnapshot.snapshot_at.asc())
    ).all()
    for snap_at, val in rows:
        if val is None:
            continue
        breach = (val >= value) if metric == METRIC_RISK_INDEX else (val <= value)
        if breach:
            lead = max(0.0, (snap_at - forecast_at).total_seconds() / 3600.0)
            return True, lead
    return False, None


def run_backtest(
    db,
    *,
    days: int | None = None,
    models: tuple[str, ...] | None = None,
    horizon: int | None = None,
) -> dict[str, Any]:
    """walk-forward 回测：填充 ``forecast_backtest`` 表，返回摘要（不 commit）。"""
    models = models or models_mod.AB_MODELS
    horizon = horizon or settings.forecast_horizon_days
    min_pts = settings.forecast_min_points
    days = days or settings.forecast_backtest_days
    now = _now()
    since = now - timedelta(days=days)
    anchor_max = now - timedelta(days=horizon)  # 锚点须使窗口结束，方可验证

    # 全量刷新：清掉同模型/跨度的旧回测
    db.execute(
        delete(ForecastBacktest).where(
            ForecastBacktest.model_version.in_(models),
            ForecastBacktest.horizon_days == horizon,
        )
    )

    proj_series = svc._load_series_bulk(db, "project", METRIC_RISK_INDEX, days=days)
    dev_series = svc._load_series_bulk(db, "device", METRIC_HEALTH_SCORE, days=days)

    tasks: list[tuple[str, str, str, int | None, list[tuple[datetime, float]]]] = []
    for ref_id, series in proj_series.items():
        pid = int(ref_id) if ref_id.isdigit() else None
        tasks.append(("project", ref_id, METRIC_RISK_INDEX, pid, series))
    for ref_id, series in dev_series.items():
        pid = svc._device_project_id(db, ref_id)
        tasks.append(("device", ref_id, METRIC_HEALTH_SCORE, pid, series))

    total_rows = 0
    anchors_used = 0
    by_model: dict[str, dict[str, int]] = {
        m: {"rows": 0, "hits": 0, "false_positives": 0} for m in models
    }

    for scope_type, ref_id, metric, pid, series in tasks:
        for a, _ in series:
            if a < since or a > anchor_max:
                continue
            upto = [(t, v) for (t, v) in series if t <= a]
            if len(upto) < min_pts:
                continue
            anchors_used += 1
            for mv in models:
                data = models_mod.forecast_by_model(mv, upto, metric, horizon)
                if data is None:
                    continue
                breach, _ = svc._breach_for(metric, data["forecast_value"], data["forecast_level"])
                if not breach:
                    continue
                f_at = data["forecast_at"]
                hit, lead = _verify(
                    db, scope_type, ref_id, metric, f_at, horizon, data["forecast_value"]
                )
                db.add(
                    ForecastBacktest(
                        model_version=mv,
                        scope_type=scope_type,
                        ref_id=ref_id,
                        project_id=pid,
                        metric=metric,
                        horizon_days=horizon,
                        anchor_at=a,
                        forecast_at=f_at,
                        forecast_value=data["forecast_value"],
                        forecast_lower=data.get("forecast_lower"),
                        forecast_upper=data.get("forecast_upper"),
                        breach=True,
                        sample_count=len(upto),
                        verified=True,
                        hit=hit,
                        lead_hours=lead,
                    )
                )
                total_rows += 1
                by_model[mv]["rows"] += 1
                if hit:
                    by_model[mv]["hits"] += 1
                else:
                    by_model[mv]["false_positives"] += 1
    db.flush()
    return {
        "models": list(models),
        "anchors": anchors_used,
        "rows": total_rows,
        "by_model": by_model,
        "horizon_days": horizon,
    }


def _build_comparison(out_models: list[dict], models: tuple[str, ...]) -> dict | None:
    """baseline=models[0]、challenger=models[-1] 的增量对比。"""
    base = next((m for m in out_models if m["model_version"] == models[0]), None)
    chal = next((m for m in out_models if m["model_version"] == models[-1]), None)
    if base is None or chal is None:
        return None

    def _delta(a, b):
        return (a - b) if (a is not None and b is not None) else None

    hit_delta = _delta(chal["hit_rate"], base["hit_rate"])
    hit_delta_pct = (
        (hit_delta / base["hit_rate"] * 100.0)
        if (hit_delta is not None and base["hit_rate"])
        else None
    )
    fp_delta = _delta(chal["false_positive_rate"], base["false_positive_rate"])
    lead_delta = _delta(chal["avg_lead_hours"], base["avg_lead_hours"])
    better = (hit_delta is not None and hit_delta >= 0) and (fp_delta is None or fp_delta <= 0)

    parts = []
    if hit_delta is not None:
        arrow = "提升" if hit_delta >= 0 else "下降"
        parts.append(f"命中率{hit_delta>=0 and '+' or ''}{hit_delta*100:.0f}pp（{arrow}）")
    if fp_delta is not None:
        arrow = "下降" if fp_delta <= 0 else "上升"
        parts.append(f"误报率{fp_delta<=0 and '' or '+'}{fp_delta*100:.0f}pp（{arrow}）")
    if lead_delta is not None:
        parts.append(f"平均提前量{lead_delta>=0 and '+' or ''}{lead_delta:.1f}h")
    summary = "；".join(parts) if parts else "暂无足够数据对比"

    return {
        "baseline": models[0],
        "baseline_label": base["label"],
        "challenger": models[-1],
        "challenger_label": chal["label"],
        "hit_rate_baseline": base["hit_rate"],
        "hit_rate_challenger": chal["hit_rate"],
        "hit_rate_delta": hit_delta,
        "hit_rate_delta_pct": hit_delta_pct,
        "false_positive_rate_baseline": base["false_positive_rate"],
        "false_positive_rate_challenger": chal["false_positive_rate"],
        "false_positive_rate_delta": fp_delta,
        "avg_lead_hours_baseline": base["avg_lead_hours"],
        "avg_lead_hours_challenger": chal["avg_lead_hours"],
        "lead_delta_hours": lead_delta,
        "better": better,
        "summary": summary,
    }


def compute_ab_hitrate(
    db,
    scope: DataScope,
    *,
    days: int = 30,
    project_id: int | None = None,
    metric: str | None = None,
    models: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """聚合 A/B 命中率报表：按 model_version 输出命中率/误报率/平均提前量 + 增量对比。"""
    models = models or models_mod.AB_MODELS
    now = _now()
    since = now - timedelta(days=days)

    stmt = select(ForecastBacktest).where(
        ForecastBacktest.model_version.in_(models),
        ForecastBacktest.anchor_at >= since,
    )
    if project_id is not None:
        stmt = stmt.where(ForecastBacktest.project_id == project_id)
    if metric:
        stmt = stmt.where(ForecastBacktest.metric == metric)
    stmt = apply_data_scope(stmt, ForecastBacktest, scope)
    rows = db.scalars(stmt).all()

    out_models: list[dict] = []
    for mv in models:
        mrows = [r for r in rows if r.model_version == mv]
        verifiable = len(mrows)
        hits = sum(1 for r in mrows if r.hit is True)
        fps = sum(1 for r in mrows if r.hit is False)
        hit_rate = (hits / verifiable) if verifiable else None
        fp_rate = (fps / verifiable) if verifiable else None
        leads = [r.lead_hours for r in mrows if r.lead_hours is not None]
        avg_lead = (sum(leads) / len(leads)) if leads else None

        by_metric: dict[str, dict] = {}
        for r in mrows:
            bm = by_metric.setdefault(
                r.metric,
                {
                    "metric": r.metric,
                    "verifiable": 0,
                    "hits": 0,
                    "false_positives": 0,
                    "pending": 0,
                    "hit_rate": None,
                },
            )
            bm["verifiable"] += 1
            if r.hit is True:
                bm["hits"] += 1
            else:
                bm["false_positives"] += 1
        for bm in by_metric.values():
            bm["hit_rate"] = (bm["hits"] / bm["verifiable"]) if bm["verifiable"] else None

        out_models.append(
            {
                "model_version": mv,
                "label": models_mod.MODEL_LABELS.get(mv, mv),
                "verifiable": verifiable,
                "hits": hits,
                "false_positives": fps,
                "pending": 0,
                "hit_rate": hit_rate,
                "false_positive_rate": fp_rate,
                "avg_lead_hours": avg_lead,
                "by_metric": by_metric,
            }
        )

    return {
        "period_days": days,
        "generated_at": now.isoformat(),
        "models": out_models,
        "comparison": _build_comparison(out_models, models),
    }
