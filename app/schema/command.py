"""设备指令下发记录对外 Schema（北京时间序列化）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer

from app.core.clock import LOCAL_TZ


class DeviceCommandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int | None = None
    device_no: str
    device_type: str
    project_id: int | None = None
    action: str
    params_json: dict | None = None
    payload: str | None = None
    topic: str | None = None
    status: str
    retry_count: int = 0
    last_error: str | None = None
    alarm_id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    sent_at: datetime | None = None
    acked_at: datetime | None = None

    @field_serializer("created_at", "updated_at", "sent_at", "acked_at")
    def _ser_dt(self, v: datetime | None):
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()
