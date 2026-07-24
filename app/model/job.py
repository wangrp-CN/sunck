"""作业计划管理域模型：对应需求 §2.6（三步式：基本信息→绑资源→绑围栏+规则）。

v2 增强：新增 plan_start/plan_end 结构化时间窗（用于规则引擎时间范围门控），
规则以 JSON 文本存储（监控目标/触发条件/时间范围/停留时间），在规则引擎 v2
中解析为判定输入；人员/设备/机械/围栏绑定通过关联表维护。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, SoftDeleteMixin, TimestampMixin
from app.model.project import Project


class WorkPlan(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "work_plan"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    name: Mapped[str] = mapped_column(String(128), comment="计划名称")
    is_start: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="计划是否激活(规则引擎据此判定)"
    )
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True, comment="计划说明")
    plan_time: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="计划时间(展示用文本)"
    )
    # 结构化时间窗（规则引擎时间范围门控）：空表示不限制
    # #11 深化：改为带时区 timestamptz，配合 engine session timezone=Asia/Shanghai，
    # 使 naive 写入按北京解释、读取为 aware 北京，消除 locale 漂移。
    plan_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划生效开始(空=不限制, 带时区)"
    )
    plan_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="计划生效结束(空=不限制, 带时区)"
    )
    # 实际执行时间窗（甘特进度联动用）：启动/完成时回填，由 jobs 路由写入
    actual_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际开始(空=未启动, 带时区)"
    )
    actual_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际结束(空=未完成, 带时区)"
    )
    # 状态：草稿/执行中/已完成
    status: Mapped[str] = mapped_column(String(16), default="草稿", comment="计划状态")
    # 模板标记：模板不参与执行/规则判定，仅作为克隆蓝本（P3·⑩）
    is_template: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, comment="是否模板(模板仅作克隆蓝本)"
    )
    # 规则 JSON：{monitor_target, trigger_conditions, time_range, dwell_time}
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
