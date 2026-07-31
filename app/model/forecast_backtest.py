"""预测回测结果表（预测模型升级 + A/B 对照）。

walk-forward 回测：对每个历史锚点（anchor_at）用截至该日的快照序列拟合各模型、
外推 horizon 天得到目标日（forecast_at），并仅保留「会越阈预警」的预测（与线上
predictive_alert 口径一致）；随后在窗口内回查实际值判定命中(hit)/误报。

该表按 (model_version, anchor_at, scope_type, ref_id, metric, horizon_days) 维度
存储多次回测结果，供 A/B 命中率报表直接聚合，不干扰线上 ``forecast`` 表（线上仍只
保留每个对象最新一条预测）。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, TimestampMixin
from app.model.project import Project


class ForecastBacktest(Base, TimestampMixin):
    __tablename__ = "forecast_backtest"

    model_version: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="预测模型版本(ols_v1/hw_v1)"
    )
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="project|device")
    ref_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="project.id 或 device_no"
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")

    metric: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="risk_index|health_score"
    )
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, comment="预测跨度(天)")

    # 锚点（拟合截止日）与目标日
    anchor_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="拟合所用的数据截止时刻"
    )
    forecast_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="预测目标时刻(anchor+horizon)"
    )

    forecast_value: Mapped[float] = mapped_column(
        Float, nullable=False, comment="该模型在 anchor_at 处外推的预测值"
    )
    forecast_lower: Mapped[float | None] = mapped_column(Float, nullable=True, comment="95% 下界")
    forecast_upper: Mapped[float | None] = mapped_column(Float, nullable=True, comment="95% 上界")

    breach: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="该预测是否触发越阈预警(始终 True，仅存越阈预测)",
    )
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="拟合样本数")

    # 验证结果（窗口结束后回填）
    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="窗口是否已结束(可验证)"
    )
    hit: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, comment="窗口内实际值是否如期越阈(命中)"
    )
    lead_hours: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="命中提前量(小时)"
    )

    __table_args__ = (
        Index("ix_fb_model_anchor", "model_version", "anchor_at"),
        Index("ix_fb_scope", "scope_type", "ref_id", "metric"),
    )
