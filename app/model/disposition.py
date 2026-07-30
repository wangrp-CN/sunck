"""告警处置记录（处置效果闭环）。

将「告警 → 如何处置 → 处置结果」沉淀为可审计、可度量的记录，闭合
「感知 → 规则 → 预测 → 处置 → 验证」主链路：

- ``alarm_id``：关联告警；
- ``playbook_id`` / ``knowledge_refs``：本次处置依据（采用的处置预案、知识库链接快照）；
- ``outcome``：处置结果（已解决 / 部分解决 / 未解决 / 误报）；
- ``action_taken`` / ``note``：处置动作与备注；
- ``resolved_at``：解决时刻（outcome=已解决 时填充），用于闭环时长统计。

数据范围：经 project_id 走 VIA_PROJECT；支持软删除。
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, SoftDeleteMixin, TimestampMixin
from app.model.project import Project


class AlarmDisposition(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "alarm_disposition"

    # 关联告警（告警删除时级联清理处置记录）
    alarm_id: Mapped[int] = mapped_column(
        ForeignKey("alarm.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联告警ID",
    )
    # 归属项目：空=全局（仅全量数据用户可见）；用于 VIA_PROJECT 数据隔离
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")

    # 本次处置采用的预案（空=未采用预案）
    playbook_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="采用的处置预案ID"
    )
    # 采用的知识库链接快照：JSON 数组文本 [{"title","url"}]
    knowledge_refs: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="采用的知识库链接(JSON数组)"
    )
    # 处置结果：已解决/部分解决/未解决/误报
    outcome: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="处置结果")
    # 处置动作（自由文本，记录实际采取的操作）
    action_taken: Mapped[str | None] = mapped_column(Text, nullable=True, comment="处置动作")
    # 处置备注
    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="处置备注")
    # 解决时刻（outcome=已解决 时填充），用于闭环时长统计
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="解决时刻"
    )

    __table_args__ = (
        Index("ix_disposition_alarm", "alarm_id"),
        Index("ix_disposition_project", "project_id"),
        Index("ix_disposition_outcome", "outcome"),
    )
