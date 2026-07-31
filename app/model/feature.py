"""外部特征表（预测特征工程：突破单序列）。

存储来自外部数据源（气象/施工进度/设备负载等）的时序特征，按项目维度落库，
供 ``hw_feat_v1`` 残差融合模型使用。数据源由 :mod:`app.service.feature_provider`
提供：当前为可插拔 Mock（确定性季节性合成），预留真实气象 API 接入（和风/OpenWeather 等）。

设计：
- 项目维度落库（``project_id`` 可空以兼容未来全局特征）；
- ``(project_id, feature_date, feature_name)`` 唯一，便于幂等 upsert；
- 数据隔离经 ``project_id`` 关联（VIA_PROJECT），与 forecast/forecast_backtest 同口径。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, TimestampMixin


class ExternalFeature(Base, TimestampMixin):
    """外部特征点：某项目某日某特征的值。"""

    __tablename__ = "external_feature"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 项目维度；可空以兼容未来全局特征
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    feature_date: Mapped[date] = mapped_column(Date, nullable=False)
    feature_name: Mapped[str] = mapped_column(String(48), nullable=False)
    feature_value: Mapped[float] = mapped_column(Float, nullable=False)
    # 数据来源：mock / qweather / openweather ...
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="mock")

    project = relationship("Project", lazy="joined")

    __table_args__ = (
        UniqueConstraint("project_id", "feature_date", "feature_name", name="uq_ext_feat"),
    )

    def __repr__(self) -> str:
        return (
            f"<ExternalFeature pid={self.project_id} {self.feature_date} "
            f"{self.feature_name}={self.feature_value} src={self.source}>"
        )
