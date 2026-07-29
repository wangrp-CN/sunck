"""值班排班模型（🅱 告警治理与值班体系）。

把「谁在什么时间、哪个项目当班」结构化，供告警自动派单、升级通知当班人复用。
数据范围：经 project_id 走 VIA_PROJECT（在 app.core.data_scope 注册）。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, SoftDeleteMixin, TimestampMixin
from app.model.project import Project


class DutyRoster(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "duty_roster"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")

    # 当班人（用户）
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # 班次：白班 / 夜班（自由串，前端下拉可选）
    shift: Mapped[str] = mapped_column(String(16), default="白班", comment="班次(白班/夜班)")
    # 值班角色：值班长 / 值班员（可选）
    duty_role: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="值班角色")
    # 值班时间窗（带时区，UTC 存储；前端按本地时区展示）
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="值班开始")
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), comment="值班结束")
    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    __table_args__ = (
        Index("ix_duty_project", "project_id"),
        Index("ix_duty_user", "user_id"),
        Index("ix_duty_window", "project_id", "start_time", "end_time"),
    )
