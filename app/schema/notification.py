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
