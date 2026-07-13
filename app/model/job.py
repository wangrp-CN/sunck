"""作业计划管理域模型：对应需求 §2.6（三步式：基本信息→绑资源→绑围栏+规则）。

骨架阶段：规则以 JSON 文本存储（监控目标/触发条件/时间范围/停留时间），
后续在业务层解析为规则引擎输入；人员/设备/机械/围栏绑定通过关联表维护。
"""

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, TimestampMixin
from app.model.project import Project


class WorkPlan(Base, TimestampMixin, CreatorMixin):
    __tablename__ = "work_plan"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    name: Mapped[str] = mapped_column(String(128), comment="计划名称")
    is_start: Mapped[bool] = mapped_column(Boolean, default=False, comment="计划启动")
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True, comment="计划说明")
    plan_time: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="计划时间")
    # 状态：草稿/执行中/已完成
    status: Mapped[str] = mapped_column(String(16), default="草稿", comment="计划状态")
    # 规则 JSON：{monitor_target, trigger_condition, time_range, dwell_time}
    rule_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="规则配置(JSON)")


class WorkPlanPerson(Base):
    __tablename__ = "work_plan_person"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("work_plan.id", ondelete="CASCADE"), primary_key=True
    )
    person_id: Mapped[int] = mapped_column(
        ForeignKey("person.id", ondelete="CASCADE"), primary_key=True
    )


class WorkPlanMachine(Base):
    __tablename__ = "work_plan_machine"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("work_plan.id", ondelete="CASCADE"), primary_key=True
    )
    machine_id: Mapped[int] = mapped_column(
        ForeignKey("machine.id", ondelete="CASCADE"), primary_key=True
    )


class WorkPlanDevice(Base):
    __tablename__ = "work_plan_device"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("work_plan.id", ondelete="CASCADE"), primary_key=True
    )
    # 可绑定三类设备之一（用 device_type + device_no 关联）
    device_type: Mapped[str] = mapped_column(String(32), primary_key=True, comment="设备类型")
    device_no: Mapped[str] = mapped_column(String(64), primary_key=True, comment="设备编号")


class WorkPlanFence(Base):
    __tablename__ = "work_plan_fence"

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("work_plan.id", ondelete="CASCADE"), primary_key=True
    )
    fence_id: Mapped[int] = mapped_column(
        ForeignKey("electronic_fence.id", ondelete="CASCADE"), primary_key=True
    )
