"""处置预案（知识库）模型（🅱 告警治理与值班体系 M5：处置预案/知识库联动）。

将「告警 → 如何处置」的闭环指导沉淀为可管理的预案（Playbook），
按 项目 × 告警类型 × 告警级别 维度匹配，供告警处置时联动推荐。

- ``alarm_type``：关联告警类型（空=通用预案，对所有类型生效）；
- ``alarm_level``：关联级别（空=不限级别）；
- ``project_id``：归属项目（空=全局预案，仅全量数据用户可见）；
- ``steps`` / ``references``：以 JSON 文本存储（分步处置步骤 / 知识库链接），
  由 schema 层编解码为列表。
数据范围：经 project_id 走 VIA_PROJECT；project_id 为空表示全局预案。
"""

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, SoftDeleteMixin, TimestampMixin
from app.model.project import Project


class Playbook(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "playbook"

    name: Mapped[str] = mapped_column(String(128), comment="预案名称")
    # 关联项目：空=全局预案（对所有项目生效，被项目级预案覆盖）
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    # 关联告警类型：空=通配（所有类型）
    alarm_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="关联告警类型(空=通用)"
    )
    # 关联告警级别：空=不限级别
    alarm_level: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="关联级别(空=不限)"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")

    summary: Mapped[str] = mapped_column(String(255), comment="处置要点(一句话)")
    # 分步处置步骤：JSON 数组文本，如 ["1. 确认现场...", "2. ..."]
    steps: Mapped[str] = mapped_column(Text, default="[]", comment="处置步骤(JSON数组)")
    # 触发条件说明
    trigger_condition: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="触发条件说明"
    )
    # 知识库链接：JSON 数组文本，如 [{"title":"...","url":"..."}]
    references: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="知识库链接(JSON数组)"
    )
    # 标签：逗号分隔
    tags: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="标签(逗号分隔)")
    # 责任岗位 / 处置时限
    owner_role: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="责任岗位")
    est_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="预计处置时长(分钟)"
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    __table_args__ = (
        Index("ix_playbook_match", "project_id", "alarm_type", "alarm_level", "enabled"),
    )
