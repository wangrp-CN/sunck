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

# 视频 AI 可识别能力清单（与前端分析选项/推理服务对齐，单一事实来源）。
# 其中 intrusion/no_helmet/smoke_fire 与回推事件类型一一对应；idle_person/region_breach
# 为更细的算法能力，回推时若带此类 event_type 将归入「其他」标签（见 VIDEO_EVENT_TYPE_LABELS 兜底）。
VIDEO_AI_CAPABILITIES = (
    {"type": "intrusion", "label": "区域入侵"},
    {"type": "no_helmet", "label": "未戴安全帽"},
    {"type": "smoke_fire", "label": "烟火"},
    {"type": "idle_person", "label": "人员滞留"},
    {"type": "region_breach", "label": "越界离开"},
)
VIDEO_AI_CAPABILITY_TYPES = tuple(c["type"] for c in VIDEO_AI_CAPABILITIES)
VIDEO_AI_CAPABILITY_LABELS = {c["type"]: c["label"] for c in VIDEO_AI_CAPABILITIES}


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
