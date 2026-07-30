"""告警策略 schema（🅱 M4 告警收敛/抑制/升级）。

时间统一序列化为北京时间（本地 naive ISO），与项目既有 schema 约定一致。
"""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from app.core.clock import LOCAL_TZ

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _ser_dt(v: datetime | None) -> str | None:
    if v is None:
        return None
    return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


def _check_hhmm(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    if not _HHMM.match(v):
        raise ValueError("时间格式须为 HH:MM（如 22:00）")
    return v


class AlarmPolicyBase(BaseModel):
    name: str
    project_id: int | None = None
    alarm_type: str | None = None
    enabled: bool = True
    suppress_window_seconds: int | None = None
    silence_start: str | None = None
    silence_end: str | None = None
    escalate_after_minutes: int | None = None
    escalate_to_level: str = "严重"
    escalate_channels: str = "in_app"
    note: str | None = None

    @field_validator("silence_start", "silence_end")
    @classmethod
    def _v_hhmm(cls, v: str | None) -> str | None:
        return _check_hhmm(v)


class AlarmPolicyCreate(AlarmPolicyBase):
    pass


class AlarmPolicyUpdate(BaseModel):
    name: str | None = None
    project_id: int | None = None
    alarm_type: str | None = None
    enabled: bool | None = None
    suppress_window_seconds: int | None = None
    silence_start: str | None = None
    silence_end: str | None = None
    escalate_after_minutes: int | None = None
    escalate_to_level: str | None = None
    escalate_channels: str | None = None
    note: str | None = None

    @field_validator("silence_start", "silence_end")
    @classmethod
    def _v_hhmm(cls, v: str | None) -> str | None:
        # 编辑语义：空串 "" 表示「清除该时段」，None 表示「不修改该字段」
        if v is None or v == "":
            return v
        if not _HHMM.match(v):
            raise ValueError("时间格式须为 HH:MM（如 22:00）")
        return v


class AlarmPolicyOut(AlarmPolicyBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_name: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("created_at", "updated_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        return _ser_dt(v)
