"""风险预测模型（Phase 5 智能化预测 M1）。

对 ``RiskHealthSnapshot`` 的时序（如项目 ``risk_index`` 日序列）做趋势外推，
把「未来 N 天预测值」结构化落库，供预测列表、预测性预警（M3）与驾驶舱
预测卡（M4）复用。

每个 (scope_type, ref_id, metric, horizon_days) 只保留一条最新预测（upsert），
历史预测不留存 —— 需要回看时可由快照序列随时重算。
数据范围：经 project_id 走 VIA_PROJECT（在 app.core.data_scope 注册）。
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, TimestampMixin
from app.model.project import Project


class Forecast(Base, TimestampMixin):
    __tablename__ = "forecast"

    # 归属项目（scope_type=device 时也回填其归属项目，供数据范围过滤）
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")

    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="project|device")
    ref_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="project.id 或 device_no"
    )
    name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="项目名称 / 设备编号"
    )
    metric: Mapped[str] = mapped_column(
        String(32), nullable=False, default="risk_index", comment="预测指标(risk_index 等)"
    )

    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, comment="预测跨度(天)")
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, comment="拟合样本数")

    last_value: Mapped[float] = mapped_column(Float, nullable=False, comment="序列最新观测值")
    slope: Mapped[float] = mapped_column(Float, nullable=False, comment="OLS 斜率(每天变化量)")
    intercept: Mapped[float] = mapped_column(Float, nullable=False, comment="OLS 截距")
    forecast_value: Mapped[float] = mapped_column(
        Float, nullable=False, comment="外推预测值(截断到 0-100)"
    )
    forecast_level: Mapped[str | None] = mapped_column(
        String(8), nullable=True, comment="预测级别(risk:高/中/低; health:优/良/中/差)"
    )

    # 置信带（M2）：残差标准差 + 95% 置信上下界（均截断 0-100）
    std_resid: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="OLS 残差标准差(样本≤2 时为 0)"
    )
    forecast_lower: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="95% 置信下界"
    )
    forecast_upper: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="95% 置信上界"
    )

    forecast_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="预测目标时刻(最后观测+horizon)"
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="本次计算时刻"
    )

    __table_args__ = (
        Index("ix_forecast_project", "project_id"),
        Index("ix_forecast_key", "scope_type", "ref_id", "metric", "horizon_days", unique=True),
    )
