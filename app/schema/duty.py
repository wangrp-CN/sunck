"""值班排班 schema（🅱 告警治理与值班体系）。

时间统一序列化为北京时间（本地 naive ISO），与项目既有 schema 约定一致。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer

from app.core.clock import LOCAL_TZ


def _ser_dt(v: datetime | None) -> str | None:
    if v is None:
        return None
    return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class DutyRosterBase(BaseModel):
    project_id: int | None = None
    user_id: int | None = None
    shift: str = "白班"
    duty_role: str | None = None
    start_time: datetime
    end_time: datetime
    note: str | None = None


class DutyRosterCreate(DutyRosterBase):
    pass


class DutyRosterUpdate(BaseModel):
    project_id: int | None = None
    user_id: int | None = None
    shift: str | None = None
    duty_role: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    note: str | None = None


class DutyRosterOut(DutyRosterBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_name: str | None = None
    project_name: str | None = None
    is_current: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("start_time", "end_time", "created_at", "updated_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        return _ser_dt(v)
