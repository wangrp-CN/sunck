"""项目管理域模型：对应需求 §2.4。"""

from datetime import date

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, CreatorMixin, TimestampMixin


class Project(Base, TimestampMixin, CreatorMixin):
    __tablename__ = "project"

    dept_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="归属部门",
    )
    name: Mapped[str] = mapped_column(String(128), comment="项目名称")
    short_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="项目简称")
    intro: Mapped[str | None] = mapped_column(String(1024), nullable=True, comment="项目介绍")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="开工日期")
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="完工日期")
    duration: Mapped[int | None] = mapped_column(comment="项目工期(天)")
    mileage: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="里程")
    section: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="区间")
    coordinate: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="坐标")
    # 状态：在建/停工/竣工
    status: Mapped[str] = mapped_column(String(16), default="在建", comment="项目状态")
