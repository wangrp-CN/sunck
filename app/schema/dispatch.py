"""根因派单闭环 Schema（#80）：创建/动作流转/改派/详情/分页/统计。

时间字段统一以「北京时间墙钟」字符串对外（YYYY-MM-DDTHH:mm:ss），与前端
el-date-picker 的 value-format 对齐；入库存 timestamptz（约定按 Asia/Shanghai 解释）。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ
from app.core.constants import (
    DISPATCH_LEVELS,
    DISPATCH_SOURCES,
    DISPATCH_STATUSES,
)


class DispatchCreate(BaseModel):
    title: str = Field(..., description="派单标题")
    source_type: str = Field("manual", description="来源(correlation/alarm/manual)")
    source_id: int | None = Field(None, description="来源记录ID(事件组/告警)")
    project_id: int | None = Field(None, description="归属项目(manual 来源必填，其余由来源解析)")
    level: str | None = Field(None, description="级别(严重/警告/提示)")
    root_cause_hint: str | None = Field(None, description="根因提示")
    assignee_id: int | None = Field(None, description="处理人ID")
    deadline: datetime | None = Field(None, description="处理时限")
    description: str | None = Field(None, description="处置说明/要求")


class DispatchAction(BaseModel):
    """状态机动作：start(待派→处理中) / close(处理中→已闭环) / reopen(已闭环→处理中)。"""

    action: str = Field(..., description="动作(start/close/reopen)")
    note: str | None = Field(None, description="处置备注")


class DispatchReassign(BaseModel):
    assignee_id: int = Field(..., description="新处理人ID")
    note: str | None = Field(None, description="改派备注")


class DispatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    source_type: str
    source_id: int | None = None
    title: str
    root_cause_hint: str | None = None
    level: str | None = None
    status: str
    assignee_id: int | None = None
    assignee_name: str | None = None
    deadline: datetime | None = None
    description: str | None = None
    last_action_note: str | None = None
    closed_at: datetime | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("deadline", "closed_at", "created_at", "updated_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class DispatchPage(BaseModel):
    total: int
    items: list[DispatchOut]
    page: int = 1
    size: int = 20


class DispatchStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_level: dict[str, int]


# 供前端下拉复用的枚举
DISPATCH_STATUS_OPTIONS = list(DISPATCH_STATUSES)
DISPATCH_SOURCE_OPTIONS = list(DISPATCH_SOURCES)
DISPATCH_LEVEL_OPTIONS = list(DISPATCH_LEVELS)
