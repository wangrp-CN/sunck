"""风险预警去重状态（智能核心 v2 · 阈值预警）。

记录每个项目「最近一次为其下发站内信预警所依据的快照时刻」，用于避免定时任务
重跑 / 手动重复触发时对同一越阈快照重复轰炸（降噪）。无快照数据时无对应行。

主键沿用 Base.id；``project_id`` 以 unique 约束保证每项目一行，便于按项目查询。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, TimestampMixin


def _parse_json(text: str | None) -> Any:
    if not text:
        return None
    import json

    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


class RiskAlertState(Base, TimestampMixin):
    __tablename__ = "risk_alert_state"

    # id / created_at / updated_at 由 Base + TimestampMixin 提供（Integer 自增主键）

    project_id: Mapped[int] = mapped_column(
        Integer, nullable=False, unique=True, index=True, comment="项目ID（每项目一行）"
    )
    last_alerted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次为其下发预警所依据的快照时刻（同值即视为已预警，降噪）",
    )
    last_risk_index: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="最近一次下发预警时的风险指数"
    )


class RiskAlertThresholdCalibration(Base, TimestampMixin):
    """阈值自学习标定日志（智能核心深化 · #④-1，追加式不可变）。

    每次``calibrate_threshold``依据近 window_days 的项目风险快照分布，按目标越阈率
    标定推荐阈值，并落一条记录供回溯与一键应用。只读、不更新，便于审计阈值演进。
    """

    __tablename__ = "risk_alert_threshold_calibration"

    window_days: Mapped[int] = mapped_column(Integer, nullable=False, comment="标定回溯窗口（天）")
    sample_count: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="参与标定的历史 risk_index 样本数"
    )
    target_breach_rate: Mapped[float] = mapped_column(
        Float, nullable=False, comment="目标越阈率（标定目标）"
    )
    current_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="标定时的 settings.risk_alert_threshold"
    )
    recommended_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="推荐阈值（分位数法，截断到 [min,max]）"
    )
    method: Mapped[str] = mapped_column(
        String(16), nullable=False, default="quantile", comment="标定方法(quantile)"
    )
    min_threshold: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="推荐阈值下界"
    )
    max_threshold: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="推荐阈值上界"
    )
    actual_breach_rate: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="推荐阈值在历史样本上的实际越阈率"
    )
    # 诊断信息（JSON 文本）：分布分位数 + 候选阈值扫描曲线
    sweep_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="候选阈值→实际越阈率扫描曲线(JSON)"
    )
    stats_json: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="分布统计(min/max/mean/median/p75/p90/p95)(JSON)"
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "window_days": self.window_days,
            "sample_count": self.sample_count,
            "target_breach_rate": self.target_breach_rate,
            "current_threshold": self.current_threshold,
            "recommended_threshold": self.recommended_threshold,
            "method": self.method,
            "min_threshold": self.min_threshold,
            "max_threshold": self.max_threshold,
            "actual_breach_rate": self.actual_breach_rate,
            "sweep": _parse_json(self.sweep_json) or [],
            "stats": _parse_json(self.stats_json) or {},
        }


class RiskAlertThresholdOverride(Base, TimestampMixin):
    """生效中的预警阈值覆盖（智能核心深化 · #④-1，单行 id=1）。

    存在即覆盖``settings.risk_alert_threshold``，实现"自学习→一键应用"闭环。
    ``source``标记来源（auto=标定应用 / manual=人工设定），便于追溯。
    """

    __tablename__ = "risk_alert_threshold_override"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment="固定为 1（单行）")
    threshold: Mapped[int] = mapped_column(Integer, nullable=False, comment="当前生效的预警阈值")
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", comment="来源(auto/manual)"
    )
    calibration_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="来源标定记录 id（auto 时关联）"
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近一次应用时刻"
    )
