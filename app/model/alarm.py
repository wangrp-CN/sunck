"""告警管理域模型：对应需求 §2.9（设备告警/前端设备告警/告警配置）。

v2 增强：告警归属到触发它的作业计划（work_plan_id），实现告警→业务溯源。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, TimestampMixin
from app.model.project import Project

if TYPE_CHECKING:
    from app.model.job import WorkPlan


class Alarm(Base, TimestampMixin, CreatorMixin):
    __tablename__ = "alarm"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    # 归属作业计划：v2 起由计划感知的规则引擎写入，用于告警→业务溯源
    work_plan_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("work_plan.id", ondelete="SET NULL"), nullable=True, index=True
    )
    work_plan: Mapped["WorkPlan"] = relationship("WorkPlan", lazy="selectin")
    alarm_type: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="告警类型")
    device_type: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="设备类型")
    device_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="设备名称")
    device_no: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="设备编号")
    alarm_info: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="告警信息")
    # 告警状态：告警开始/告警结束/已消警
    alarm_status: Mapped[str] = mapped_column(String(16), default="告警开始", comment="告警状态")
    # 告警级别：严重/警告/提示（影响前端弹窗配色）
    alarm_level: Mapped[str] = mapped_column(
        String(16), default="警告", comment="告警级别(严重/警告/提示)"
    )
    # 处理状态：待处理/已处理/已忽略/已确认
    handle_status: Mapped[str] = mapped_column(String(16), default="待处理", comment="处理状态")
    handle_content: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="处理内容"
    )
    alarm_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="告警时间"
    )
    # 关联围栏/图片/视频（骨架预留）
    fence_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="围栏名称")
    media_urls: Mapped[str | None] = mapped_column(
        String(1024), nullable=True, comment="图片/视频URL"
    )
    # 关联隐患（告警一键转隐患时回填，形成监测→治理闭环）
    hazard_id: Mapped[int | None] = mapped_column(
        ForeignKey("hazard.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联隐患ID(告警转隐患)",
    )


class AlarmConfig(Base, TimestampMixin):
    """平台告警配置与定位设备告警间距配置，对应需求 §2.9.2。"""

    __tablename__ = "alarm_config"

    enable_popup: Mapped[bool] = mapped_column(default=True, comment="是否弹窗")
    enable_voice: Mapped[bool] = mapped_column(default=True, comment="是否语音")
    voice_file: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="语音文件")
    # 间距阈值（米）：大机/人员手持机/人员工牌/人员手环
    distance_machine: Mapped[int] = mapped_column(default=50, comment="大机告警间距")
    distance_handheld: Mapped[int] = mapped_column(default=20, comment="人员手持机告警间距")
    distance_badge: Mapped[int] = mapped_column(default=20, comment="人员工牌告警间距")
    distance_band: Mapped[int] = mapped_column(default=20, comment="人员手环告警间距")
