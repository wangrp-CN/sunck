"""项目风险指数阈值自学习标定（智能核心深化 · #④-1）。

目标：用**历史风险指数分布**取代写死的 ``settings.risk_alert_threshold``，让阈值能随
业务态势"自学习"演进，在「告警预算」与「捕获尾风险」间取得平衡。

标定方法（分位数法）：
  取近 ``window_days`` 内所有项目风险快照的 ``risk_index`` 样本，按目标越阈率
  ``target_breach_rate`` 取 ``(1 - target)`` 分位数作为推荐阈值；该阈值使约
  ``target`` 比例的**历史观测**被判为越阈（尾部分险），从而把预警量控制在预期预算内。

  说明：以"观测样本"而非"按项目最新快照"标定，是因为快照为每日时序，单项目多样本能
  更稳健地刻画整体风险分布；其越阈率语义 = "任一观测越阈的概率"，与预警量高度相关，
  作为预算代理合理。前端 /metrics 端点会展示扫描曲线供人工复核。

闭环：``calibrate_threshold`` 落日志 → ``apply_threshold`` 写入单行覆盖 →
``evaluate_risk_alerts`` / ``alert_newly_breached`` 经 ``get_active_threshold`` 读取，
实现"学习→应用"自动生效。
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import settings
from app.model.risk_alert import (
    RiskAlertThresholdCalibration,
    RiskAlertThresholdOverride,
)
from app.model.snapshot import RiskHealthSnapshot


def collect_risk_index_samples(db, window_days: int = 90) -> list[int]:
    """收集近 ``window_days`` 内所有项目风险快照的 ``risk_index`` 样本（忽略 None）。"""
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    rows = (
        db.execute(
            select(RiskHealthSnapshot.risk_index).where(
                RiskHealthSnapshot.scope_type == "project",
                RiskHealthSnapshot.risk_index.isnot(None),
                RiskHealthSnapshot.snapshot_at >= since,
            )
        )
        .scalars()
        .all()
    )
    return [int(r) for r in rows]


def _quantile(sorted_vals: list[int], q: float) -> float:
    """线性插值分位数；q 越界时返回端点。"""
    if not sorted_vals:
        return 0.0
    if q <= 0:
        return float(sorted_vals[0])
    if q >= 1:
        return float(sorted_vals[-1])
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def calibrate_threshold(
    db,
    window_days: int = 90,
    target_breach_rate: float = 0.10,
    min_threshold: int = 40,
    max_threshold: int = 90,
) -> dict:
    """基于历史分布标定推荐阈值（详见模块 docstring）。

    返回含推荐阈值、分布统计、候选阈值扫描曲线的字典，供落库与前端展示。
    """
    samples = collect_risk_index_samples(db, window_days)
    n = len(samples)
    current = settings.risk_alert_threshold
    result: dict = {
        "window_days": window_days,
        "sample_count": n,
        "target_breach_rate": target_breach_rate,
        "current_threshold": current,
        "min_threshold": min_threshold,
        "max_threshold": max_threshold,
        "method": "quantile",
        "recommended_threshold": current,
        "actual_breach_rate": None,
        "sweep": [],
        "stats": {},
        "message": "",
    }

    if n == 0:
        result["message"] = "历史样本不足，沿用当前阈值"
        return result

    sorted_vals = sorted(samples)
    q = max(0.0, min(0.999, 1.0 - target_breach_rate))
    rec = int(round(_quantile(sorted_vals, q)))
    rec = max(min_threshold, min(max_threshold, rec))
    result["recommended_threshold"] = rec

    result["stats"] = {
        "min": sorted_vals[0],
        "max": sorted_vals[-1],
        "mean": round(statistics.mean(sorted_vals), 2),
        "median": round(_quantile(sorted_vals, 0.5), 2),
        "p75": round(_quantile(sorted_vals, 0.75), 2),
        "p90": round(_quantile(sorted_vals, 0.90), 2),
        "p95": round(_quantile(sorted_vals, 0.95), 2),
    }

    # 候选阈值扫描曲线（步长 5，供前端灵敏度可视化）
    sweep = []
    for t in range(min_threshold, max_threshold + 1, 5):
        breach = sum(1 for v in sorted_vals if v >= t)
        sweep.append({"threshold": t, "breach_rate": round(breach / n, 4)})
    result["sweep"] = sweep

    result["actual_breach_rate"] = round(sum(1 for v in sorted_vals if v >= rec) / n, 4)
    return result


def persist_calibration(db, result: dict) -> RiskAlertThresholdCalibration:
    """把标定结果落库（追加式），返回新行。"""
    row = RiskAlertThresholdCalibration(
        window_days=result["window_days"],
        sample_count=result["sample_count"],
        target_breach_rate=result["target_breach_rate"],
        current_threshold=result["current_threshold"],
        recommended_threshold=result["recommended_threshold"],
        method=result["method"],
        min_threshold=result.get("min_threshold"),
        max_threshold=result.get("max_threshold"),
        actual_breach_rate=result.get("actual_breach_rate"),
        sweep_json=json.dumps(result.get("sweep", []), ensure_ascii=False),
        stats_json=json.dumps(result.get("stats", {}), ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_latest_calibration(db) -> RiskAlertThresholdCalibration | None:
    """返回最近一条标定记录（无则 None）。"""
    return db.scalar(
        select(RiskAlertThresholdCalibration).order_by(RiskAlertThresholdCalibration.id.desc())
    )


def get_active_threshold(db) -> int:
    """当前生效阈值：优先数据库覆盖行，否则回退 ``settings``。"""
    ov = db.scalar(select(RiskAlertThresholdOverride).where(RiskAlertThresholdOverride.id == 1))
    if ov is not None:
        return ov.threshold
    return settings.risk_alert_threshold


def apply_threshold(
    db,
    threshold: int,
    source: str = "manual",
    calibration_id: int | None = None,
) -> RiskAlertThresholdOverride:
    """写入/更新单行生效阈值覆盖（id=1），返回覆盖行。"""
    threshold = max(0, min(100, int(threshold)))
    ov = db.scalar(select(RiskAlertThresholdOverride).where(RiskAlertThresholdOverride.id == 1))
    if ov is None:
        ov = RiskAlertThresholdOverride(id=1)
        db.add(ov)
    ov.threshold = threshold
    ov.source = source
    ov.calibration_id = calibration_id
    ov.applied_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(ov)
    return ov
