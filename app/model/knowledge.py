"""知识库条目模型（🅱 告警治理：知识库自动检索关联链接）。

沉淀涉铁工程的规范、标准作业程序(SOP)、内训与案例，供处置预案关联、
告警处置时自动检索相关链接。

- ``project_id``：归属项目（空=全局知识，对所有项目可见）；
- ``tags``：逗号分隔标签，用于相关性匹配；
- ``content``：正文/摘要（可选，用于检索打分）。
数据范围：经 project_id 走 VIA_PROJECT；project_id 为空表示全局知识。
"""

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, SoftDeleteMixin, TimestampMixin
from app.model.project import Project


class KnowledgeArticle(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "knowledge_article"

    title: Mapped[str] = mapped_column(String(255), comment="标题")
    url: Mapped[str] = mapped_column(String(512), comment="链接")
    summary: Mapped[str] = mapped_column(Text, comment="摘要/要点")
    # 来源分类：规范库 / 内训库 / 案例库 / 手册
    source: Mapped[str] = mapped_column(String(64), default="知识库", comment="来源分类")
    # 逗号分隔标签，用于相关性匹配
    tags: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="标签(逗号分隔)")
    # 正文/检索语料（可选）
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="正文/检索语料")
    # 关联项目：空=全局知识
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用(可检索)")

    __table_args__ = (
        Index("ix_knowledge_project", "project_id"),
        Index("ix_knowledge_source", "source"),
    )
