"""风险预测服务（Phase 5 智能化预测 M1 · 预测基座）。

对 ``RiskHealthSnapshot`` 的项目 ``risk_index`` 日序列做**纯 Python OLS
（最小二乘）线性趋势外推**，预测未来 N 天风险指数并 upsert 落 ``forecast`` 表：

- 无第三方依赖（不引 numpy/sklearn），样本量小（≤ 数十点）用解析解即可；
- 每个 (scope_type, ref_id, metric, horizon_days) 只保留最新一条预测；
- 预测值截断到 [0, 100] 并按 ``app.core.scoring`` 的分档阈值给出预测级别；
- 序列点数 < ``settings.forecast_min_points`` 时不出预测（防 1~2 点直线误导）。

服务内不 commit，由端点或 job 统一提交（项目 SOP）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.scoring import RISK_LEVEL_HIGH, RISK_LEVEL_MID
from app.model.forecast import Forecast
from app.model.project import Project
from app.model.snapshot import RiskHealthSnapshot

METRIC_RISK_INDEX = "risk_index"


def _risk_level(value: float) -> str:
    """预测值按与实时口径一致的阈值分档（app.core.scoring）。"""
    if value >= RISK_LEVEL_HIGH:
        return "高"
    if value >= RISK_LEVEL_MID:
        return "中"
    return "低"


def _ols(points: list[tuple[float, float]]) -> tuple[float, float]:
    """最小二乘拟合 y = slope*x + intercept，返回 (slope, intercept)。

    调用方保证 len(points) >= 2；x 全相等（同刻多点）时斜率视为 0。
    """
    n = float(len(points))
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, sy / n
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


def _load_series(db: Session, project_id: int, days: int) -> list[tuple[datetime, float]]:
    """项目 risk_index 快照序列（旧→新），保留 datetime 供换算天数。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(RiskHealthSnapshot.snapshot_at, RiskHealthSnapshot.risk_index)
        .where(
            RiskHealthSnapshot.scope_type == "project",
            RiskHealthSnapshot.ref_id == str(project_id),
            RiskHealthSnapshot.snapshot_at >= since,
            RiskHealthSnapshot.risk_index.is_not(None),
        )
        .order_by(RiskHealthSnapshot.snapshot_at.asc())
    ).all()
    out: list[tuple[datetime, float]] = []
    for at, val in rows:
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        out.append((at, float(val)))
    return out


def compute_forecast(
    db: Session,
    project_id: int,
    *,
    horizon_days: int | None = None,
    history_days: int | None = None,
) -> dict | None:
    """对单个项目计算 risk_index 预测；样本不足返回 None（不落库）。"""
    horizon = horizon_days or settings.forecast_horizon_days
    history = history_days or settings.forecast_history_days
    series = _load_series(db, project_id, days=history)
    if len(series) < settings.forecast_min_points:
        return None

    t0 = series[0][0]
    points = [((at - t0).total_seconds() / 86400.0, val) for at, val in series]
    slope, intercept = _ols(points)

    last_at, last_value = series[-1]
    x_target = (last_at - t0).total_seconds() / 86400.0 + horizon
    raw_pred = slope * x_target + intercept
    forecast_value = max(0.0, min(100.0, raw_pred))
    return {
        "project_id": project_id,
        "scope_type": "project",
        "ref_id": str(project_id),
        "metric": METRIC_RISK_INDEX,
        "horizon_days": horizon,
        "sample_count": len(series),
        "last_value": last_value,
        "slope": round(slope, 4),
        "intercept": round(intercept, 4),
        "forecast_value": round(forecast_value, 2),
        "forecast_level": _risk_level(forecast_value),
        "forecast_at": last_at + timedelta(days=horizon),
        "computed_at": datetime.now(timezone.utc),
    }


def upsert_forecast(db: Session, data: dict, name: str | None = None) -> Forecast:
    """按唯一键 (scope_type, ref_id, metric, horizon_days) upsert。"""
    obj = db.scalars(
        select(Forecast).where(
            Forecast.scope_type == data["scope_type"],
            Forecast.ref_id == data["ref_id"],
            Forecast.metric == data["metric"],
            Forecast.horizon_days == data["horizon_days"],
        )
    ).first()
    if obj is None:
        obj = Forecast(**data, name=name)
        db.add(obj)
    else:
        for k, v in data.items():
            setattr(obj, k, v)
        if name is not None:
            obj.name = name
    db.flush()
    return obj


def run_forecasts(db: Session, horizon_days: int | None = None) -> dict:
    """遍历全部未删除项目计算并落库预测（不 commit，由调用方提交）。"""
    projects = db.execute(
        select(Project.id, Project.name).where(Project.is_deleted.is_(False))
    ).all()
    computed = skipped = 0
    for pid, pname in projects:
        data = compute_forecast(db, pid, horizon_days=horizon_days)
        if data is None:
            skipped += 1
            continue
        upsert_forecast(db, data, name=pname)
        computed += 1
    return {"computed": computed, "skipped": skipped, "total": len(projects)}
