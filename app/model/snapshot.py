"""风险/健康分时序快照（智能核心 v2）。

每日（或按需）把「项目风险分」「设备健康分」落库为时间序列，供对比大屏趋势线、
阈值预警与跨周期对比使用。

单表 + ``scope_type`` 判别（``project`` / ``device``），避免多表散落；聚合口径与
``devices/health``、``dashboard/project-compare`` 两个端点**完全一致**（见
``app/service/metrics_snapshot.py``），保证快照数字与前端大屏同源。
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, TimestampMixin


class RiskHealthSnapshot(Base, TimestampMixin):
    __tablename__ = "risk_health_snapshot"

    # id / created_at / updated_at 由 Base + TimestampMixin 提供（Integer 自增主键）

    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, comment="project|device")
    ref_id: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="project.id 或 device_no"
    )
    name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="项目名称 / 设备编号"
    )

    # 项目风险（scope_type=project）
    risk_index: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="0-100 风险指数")
    risk_level: Mapped[str | None] = mapped_column(String(8), nullable=True, comment="高/中/低")
    raw_score: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="归一化前原始分")

    # 设备健康（scope_type=device）
    health_score: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="0-100 健康分")
    health_level: Mapped[str | None] = mapped_column(
        String(8), nullable=True, comment="优/良/中/差"
    )
    online_state: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="fresh/stale/offline"
    )

    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="快照时刻"
    )

    __table_args__ = (
        Index("ix_rhs_scope_ref", "scope_type", "ref_id"),
        Index("ix_rhs_snapshot_at", "snapshot_at"),
    )
