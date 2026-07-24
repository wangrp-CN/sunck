"""风险预警去重状态（智能核心 v2 · 阈值预警）。

记录每个项目「最近一次为其下发站内信预警所依据的快照时刻」，用于避免定时任务
重跑 / 手动重复触发时对同一越阈快照重复轰炸（降噪）。无快照数据时无对应行。

主键沿用 Base.id；``project_id`` 以 unique 约束保证每项目一行，便于按项目查询。
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, TimestampMixin


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
