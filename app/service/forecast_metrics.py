"""预测指标注册表（预测可解释化 + 多指标解耦）。

集中定义每个可预测指标的元数据，消除 ``forecast_service`` / ``backtest_service`` /
``forecast_models`` 中分散的 metric→列、方向、阈值、分档常量。新增指标只需在此登记，
服务层 / 回测 / A-B 报表自动覆盖，无需逐个改动。

设计要点：
- ``column_attr`` 指向 ``RiskHealthSnapshot`` 的取值列（目前所有指标均来自该表）；
- ``direction`` 区分「高好 / 低好」，决定预防式告警区间越阈的方向（上界 / 下界）；
- ``breach_levels`` 为点预测越阈回灌 predictive_alert 的（预测级别, 告警级别）映射；
- ``preventive_threshold`` + ``preventive_alarm_level`` 为置信区间越阈时的提前预警口径。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.scoring import (
    HEALTH_LEVEL_MID,
    RISK_LEVEL_HIGH,
    RISK_LEVEL_MID,
    device_health_level,
)
from app.model.snapshot import RiskHealthSnapshot

#: 指标方向：值越高越好（high_good，如 health_score）或越低越好（low_good，如 risk_index）
DIRECTION_HIGH_GOOD = "high_good"
DIRECTION_LOW_GOOD = "low_good"

#: 指标键常量（与注册表 key 保持一致，供跨模块引用）
METRIC_RISK_INDEX = "risk_index"
METRIC_HEALTH_SCORE = "health_score"


@dataclass(frozen=True)
class MetricMeta:
    """单个可预测指标的元数据。"""

    key: str
    label: str
    scope_type: str  # 该指标所属的 scope：project / device
    column_attr: str  # RiskHealthSnapshot 中取值列名
    direction: str  # DIRECTION_HIGH_GOOD / DIRECTION_LOW_GOOD
    unit: str
    description: str
    # 点预测越阈回灌 predictive_alert 的（预测级别, 告警级别）映射；空格级别不触发
    breach_levels: tuple[tuple[str, str], ...] = ()
    # 预防式告警：置信区间越过该值即提前预警（区间越阈判据）
    preventive_threshold: float | None = None
    preventive_alarm_level: str | None = None


METRIC_REGISTRY: dict[str, MetricMeta] = {
    METRIC_RISK_INDEX: MetricMeta(
        key=METRIC_RISK_INDEX,
        label="项目风险指数",
        scope_type="project",
        column_attr="risk_index",
        direction=DIRECTION_LOW_GOOD,
        unit="分",
        description="项目综合风险指数(0-100)，越低越好",
        breach_levels=(("高", "警告"),),
        preventive_threshold=float(RISK_LEVEL_HIGH),  # 60
        preventive_alarm_level="警告",
    ),
    METRIC_HEALTH_SCORE: MetricMeta(
        key=METRIC_HEALTH_SCORE,
        label="设备健康分",
        scope_type="device",
        column_attr="health_score",
        direction=DIRECTION_HIGH_GOOD,
        unit="分",
        description="设备健康分(0-100)，越高越好",
        breach_levels=(("中", "警告"), ("差", "严重")),
        preventive_threshold=float(HEALTH_LEVEL_MID),  # 60（健康分<60 即差→严重）
        preventive_alarm_level="严重",
    ),
}


def get_metric_meta(metric: str) -> MetricMeta | None:
    return METRIC_REGISTRY.get(metric)


def all_metrics() -> list[MetricMeta]:
    return list(METRIC_REGISTRY.values())


def metrics_for_scope(scope_type: str) -> list[MetricMeta]:
    return [m for m in METRIC_REGISTRY.values() if m.scope_type == scope_type]


def metric_column(metric: str):
    """返回 RiskHealthSnapshot 取值列（SQLAlchemy 列对象）。"""
    meta = METRIC_REGISTRY.get(metric)
    if meta is None:
        raise KeyError(f"未知指标: {metric}")
    return getattr(RiskHealthSnapshot, meta.column_attr)


def direction_of(metric: str) -> str:
    meta = METRIC_REGISTRY.get(metric)
    return meta.direction if meta else DIRECTION_LOW_GOOD


def level_for(metric: str, value: float) -> str:
    """预测值按与实时口径一致的阈值分档（risk 高/中/低，health 优/良/中/差）。"""
    meta = METRIC_REGISTRY.get(metric)
    if meta is None:
        return _fallback_level(value)
    if meta.direction == DIRECTION_HIGH_GOOD:
        return device_health_level(int(round(value)))
    return _fallback_level(value)


def _fallback_level(value: float) -> str:
    if value >= RISK_LEVEL_HIGH:
        return "高"
    if value >= RISK_LEVEL_MID:
        return "中"
    return "低"


def breach_for(
    metric: str, forecast_value: float, forecast_level: str | None
) -> tuple[bool, str | None]:
    """点预测越阈判据：返回 (是否触发预警, 告警级别)。

    - risk_index：预测级别「高」触发，级别「警告」；
    - health_score：预测级别「中」→「警告」、「差」→「严重」；优/良不触发。
    """
    meta = METRIC_REGISTRY.get(metric)
    if meta is None or forecast_level is None:
        return False, None
    for lvl, alarm_lvl in meta.breach_levels:
        if forecast_level == lvl:
            return True, alarm_lvl
    return False, None


def preventive_breach(
    metric: str, forecast_lower: float | None, forecast_upper: float | None
) -> tuple[bool, str | None]:
    """置信区间越阈判据（预防式告警）：返回 (是否触发, 告警级别)。

    - low_good（如 risk_index）：上界越过阈值即最坏情况会越阈 → 提前预警；
    - high_good（如 health_score）：下界越过阈值即最坏情况会越阈 → 提前预警。
    """
    meta = METRIC_REGISTRY.get(metric)
    if meta is None or meta.preventive_threshold is None:
        return False, None
    if meta.direction == DIRECTION_LOW_GOOD:
        if forecast_upper is not None and forecast_upper >= meta.preventive_threshold:
            return True, meta.preventive_alarm_level
    else:
        if forecast_lower is not None and forecast_lower <= meta.preventive_threshold:
            return True, meta.preventive_alarm_level
    return False, None
