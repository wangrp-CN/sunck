"""设备指令下发域模型：平台→设备下行指令的全生命周期记录。

将原本「发完即忘」的下发改造为可追踪的闭环：
- 每次下发落库一条 DeviceCommand（状态机：pending → sent → acked / failed）；
- 设备经 ``device/{device_no}/ack`` 回执 ``cmd_id``，平台据之更新状态；
- 周期任务对超时未回执/失败的指令自动重试（直至达到最大重试次数）。

设备身份以 ``device_type + device_no`` 持久化（与 MQTT 主题、协议层一致），
并冗余 ``project_id`` 以便数据范围过滤与运维检索。
"""

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, CreatorMixin, TimestampMixin

# 指令状态机
COMMAND_STATUS_PENDING = "pending"  # 已建记录，尚未发布
COMMAND_STATUS_SENT = "sent"  # 已发布到 MQTT（等待设备回执）
COMMAND_STATUS_ACKED = "acked"  # 设备已回执（成功）
COMMAND_STATUS_FAILED = "failed"  # 发布失败或重试耗尽


class DeviceCommand(Base, TimestampMixin, CreatorMixin):
    __tablename__ = "device_command"
    __table_args__ = (
        Index("ix_device_command_project_id", "project_id"),
        Index("ix_device_command_device_no", "device_no"),
        Index("ix_device_command_status", "status"),
        Index("ix_device_command_alarm_id", "alarm_id"),
    )

    device_id: Mapped[int | None] = mapped_column(
        Integer(), nullable=True, comment="设备行主键(三类设备各自表)"
    )
    device_no: Mapped[str] = mapped_column(String(64), nullable=False, comment="设备编号")
    device_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="设备类型")
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, comment="所属项目(数据范围)"
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, comment="指令动作")
    params_json: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="指令参数(结构化)"
    )
    payload: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="实际下发报文(含 cmd_id，便于设备回执关联)"
    )
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="下发主题")
    status: Mapped[str] = mapped_column(
        String(16), default=COMMAND_STATUS_PENDING, nullable=False, comment="指令状态"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer(), default=0, nullable=False, comment="已重试次数"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="最近错误")
    sent_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="发布时间"
    )
    acked_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="设备回执时间"
    )
    alarm_id: Mapped[int | None] = mapped_column(
        ForeignKey("alarm.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联告警(消警指令溯源)",
    )
