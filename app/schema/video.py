"""视频通道 / AI 事件 Schema（P3·⑧ PoC）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ

VIDEO_EVENT_TYPES = ("intrusion", "no_helmet", "smoke_fire", "other")
VIDEO_EVENT_TYPE_LABELS = {
    "intrusion": "区域入侵",
    "no_helmet": "未戴安全帽",
    "smoke_fire": "烟火",
    "other": "其他",
}


class VideoChannelCreate(BaseModel):
    project_id: int | None = None
    name: str = Field(..., description="通道名称")
    channel_no: str = Field(..., description="通道编号(唯一)")
    stream_url: str | None = None
    vendor: str | None = None
    location_desc: str | None = None
    lng: float | None = None
    lat: float | None = None
    status: str = "在线"
    ai_enabled: bool = True


class VideoChannelUpdate(BaseModel):
    project_id: int | None = None
    name: str | None = None
    stream_url: str | None = None
    vendor: str | None = None
    location_desc: str | None = None
    lng: float | None = None
    lat: float | None = None
    status: str | None = None
    ai_enabled: bool | None = None


class VideoChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    project_name: str | None = None
    name: str
    channel_no: str
    stream_url: str | None = None
    vendor: str | None = None
    location_desc: str | None = None
    lng: float | None = None
    lat: float | None = None
    status: str = "在线"
    ai_enabled: bool = True
    created_at: datetime | None = None

    @field_serializer("created_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class VideoEventIngest(BaseModel):
    """外部推理服务回推的结构化事件（重推理不在平台落地）。"""

    channel_no: str = Field(..., description="通道编号")
    event_type: str = Field(..., description="事件类型(intrusion/no_helmet/smoke_fire/other)")
    confidence: float | None = Field(None, ge=0, le=1, description="置信度0-1")
    snapshot_url: str | None = None
    event_time: datetime | None = None
    detail: str | None = Field(None, description="事件详情(JSON文本)")


class VideoEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel_id: int
    channel_name: str | None = None
    channel_no: str | None = None
    project_id: int | None = None
    event_type: str
    event_type_label: str | None = None
    confidence: float | None = None
    snapshot_url: str | None = None
    event_time: datetime | None = None
    detail: str | None = None
    handled: bool = False
    alarm_id: int | None = None
    created_at: datetime | None = None

    @field_serializer("event_time", "created_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()
