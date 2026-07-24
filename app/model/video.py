"""视频 AI 分析接入骨架（P3·⑧ PoC）。

重推理不在本平台落地：外部推理服务（或摄像头厂商 AI 盒子）通过
`POST /v1/video/events` 回推结构化事件，平台负责通道台账、事件留痕与
可选的告警联动（alarm_id 溯源）。

- VideoChannel：视频通道登记（流地址/位置/归属项目/状态）
- VideoEvent：AI 事件（类型/置信度/截图/发生时间/是否已处理）

数据范围：VIA_PROJECT（经 project.dept_id 过滤）。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, SoftDeleteMixin, TimestampMixin
from app.model.project import Project


class VideoChannel(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "video_channel"

    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")

    name: Mapped[str] = mapped_column(String(128), comment="通道名称")
    channel_no: Mapped[str] = mapped_column(String(64), unique=True, comment="通道编号(唯一)")
    stream_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="拉流地址(RTSP/HLS/FLV)"
    )
    vendor: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="厂商/型号")
    location_desc: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="安装位置描述"
    )
    lng: Mapped[float | None] = mapped_column(Float, nullable=True, comment="经度(WGS-84)")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True, comment="纬度(WGS-84)")
    status: Mapped[str] = mapped_column(String(16), default="在线", comment="通道状态")
    ai_enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用AI分析")


class VideoEvent(Base, TimestampMixin):
    __tablename__ = "video_event"

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("video_channel.id", ondelete="CASCADE"), index=True, comment="所属通道"
    )
    channel: Mapped["VideoChannel"] = relationship("VideoChannel", lazy="selectin")
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # 事件类型：intrusion(区域入侵)/no_helmet(未戴安全帽)/smoke_fire(烟火)/other
    event_type: Mapped[str] = mapped_column(String(32), index=True, comment="AI事件类型")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True, comment="置信度0-1")
    snapshot_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True, comment="事件截图URL"
    )
    event_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True, comment="事件发生时间(带时区)"
    )
    detail: Mapped[str | None] = mapped_column(Text, nullable=True, comment="事件详情(JSON文本)")
    handled: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已处理")
    # 联动告警溯源（预留：事件升级为平台告警时回填）
    alarm_id: Mapped[int | None] = mapped_column(
        ForeignKey("alarm.id", ondelete="SET NULL"), nullable=True, index=True
    )
