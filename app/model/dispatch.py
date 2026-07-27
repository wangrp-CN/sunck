"""根因派单闭环模型（#80）：把跨设备共因事件组 / 告警转为可跟踪的处置工单。

状态机（见 app.core.constants.DISPATCH_TRANSITIONS）：
- 待派(pending) → 处理中(processing) → 已闭环(closed)，已闭环可 reopen 回处理中。

派单可来源于：
- correlation：跨设备共因事件组（CorrelatedEventGroup.id），携带其 root_cause_hint；
- alarm：单条告警（Alarm.id）；
- manual：人工建单。

数据范围：经 project_id 走 VIA_PROJECT（在 app.core.data_scope 注册）。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, SoftDeleteMixin, TimestampMixin
from app.model.project import Project


class DispatchOrder(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "dispatch_order"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")

    # 来源：correlation / alarm / manual
    source_type: Mapped[str] = mapped_column(String(16), default="manual", comment="来源类型")
    source_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="来源记录ID(事件组/告警)"
    )

    title: Mapped[str] = mapped_column(String(255), comment="派单标题")
    # 根因提示：来自共因事件组 root_cause_hint 或人工填写
    root_cause_hint: Mapped[str | None] = mapped_column(Text, nullable=True, comment="根因提示")
    # 共因级别（严重/警告/提示），来自来源告警/事件组 max_level
    level: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="级别")

    status: Mapped[str] = mapped_column(
        String(16), default="待派", index=True, comment="状态(待派/处理中/已闭环)"
    )
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="处理人"
    )
    assignee_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="处理人姓名(冗余便于展示)"
    )
    deadline: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="处理时限"
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="处置说明/要求")
    # 流转备注（最近一次 start/close 的处理内容）
    last_action_note: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="最近处置备注"
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="闭环时间"
    )

    __table_args__ = (
        Index("ix_dispatch_project_status", "project_id", "status"),
        Index("ix_dispatch_source", "source_type", "source_id"),
    )
