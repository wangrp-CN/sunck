"""巡检 / 打卡 / 履职域模型（P3·⑨）。

- InspectionTask：巡检任务（归属项目、责任人、巡检窗口、状态机）
  状态机：待巡检 → 巡检中 → 已完成；任一非终态可取消。
- InspectionRecord：打卡记录（任务下多次打卡，含 WGS-84 坐标与结果）
  结果=异常 时可转隐患（hazard_id 溯源），与告警转隐患同构。

数据范围：VIA_PROJECT（经 project.dept_id 过滤）。
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, SoftDeleteMixin, TimestampMixin
from app.model.person import Person
from app.model.project import Project


class InspectionTask(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "inspection_task"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")

    name: Mapped[str] = mapped_column(String(128), comment="巡检任务名称")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="巡检内容/要求")
    # 责任人（关联人员台账）
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("person.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assignee: Mapped["Person"] = relationship("Person", lazy="selectin")
    # 巡检窗口
    start_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="窗口开始(带时区)"
    )
    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="窗口结束(带时区)"
    )
    # 状态机：待巡检/巡检中/已完成/已取消
    status: Mapped[str] = mapped_column(
        String(16), default="待巡检", index=True, comment="任务状态"
    )
    # 要求打卡次数（履职考核基线）
    required_checkins: Mapped[int] = mapped_column(default=1, comment="要求打卡次数")


class InspectionRecord(Base, TimestampMixin, CreatorMixin):
    __tablename__ = "inspection_record"

    task_id: Mapped[int] = mapped_column(
        ForeignKey("inspection_task.id", ondelete="CASCADE"), index=True, comment="所属巡检任务"
    )
    task: Mapped["InspectionTask"] = relationship("InspectionTask", lazy="selectin")
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )

    checkin_by_name: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="打卡人")
    checkin_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="打卡时间(带时区)"
    )
    # 坐标：入库 WGS-84（与设备/隐患一致），对外 GCJ-02 由前端转换
    lng: Mapped[float | None] = mapped_column(Float, nullable=True, comment="经度(WGS-84)")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True, comment="纬度(WGS-84)")
    # 结果：正常/异常
    result: Mapped[str] = mapped_column(String(16), default="正常", comment="巡检结果")
    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="巡检说明")
    # 异常转隐患溯源（与告警转隐患同构）
    hazard_id: Mapped[int | None] = mapped_column(
        ForeignKey("hazard.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="转出隐患ID(异常记录转隐患溯源)",
    )
