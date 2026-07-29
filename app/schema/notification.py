"""通知中心 Schema：对外输出与分页。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer

from app.core.clock import LOCAL_TZ


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    channel: str = "in_app"
    category: str = "alarm"
    title: str
    content: str | None = None
    link: str | None = None
    is_read: bool = False
    created_at: datetime | None = None

    @field_serializer("created_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class NotificationPage(BaseModel):
    total: int
    unread: int
    items: list[NotificationOut]
    page: int = 1
    size: int = 20


class NotificationDeliveryOut(BaseModel):
    """短信/语音网关触达回执（模拟真实数据形态）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    channel: str
    provider: str
    phone: str | None = None
    content: str | None = None
    biz_id: str | None = None
    request_id: str | None = None
    code: str | None = None
    message: str | None = None
    status: str
    raw: str | None = None
    created_at: datetime | None = None

    @field_serializer("created_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()
