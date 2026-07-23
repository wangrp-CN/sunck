"""隐患治理闭环 Schema：创建/更新/详情/状态流转/分页/统计。

时间字段统一以「北京时间墙钟」字符串对外（YYYY-MM-DDTHH:mm:ss），与前端
el-date-picker 的 value-format 对齐；入库存 timestamptz（约定按 Asia/Shanghai 解释）。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ
from app.core.constants import (
    HAZARD_CATEGORIES,
    HAZARD_LEVELS,
    HAZARD_SOURCES,
    HAZARD_STATUSES,
)


class HazardCreate(BaseModel):
    project_id: int | None = None
    title: str = Field(..., description="隐患标题")
    level: str = Field("一般", description="隐患等级(重大/较大/一般/低)")
    category: str | None = Field(None, description="隐患类别")
    description: str | None = None
    location_desc: str | None = None
    lng: float | None = None
    lat: float | None = None
    discovered_by_name: str | None = None
    discovered_at: datetime | None = None
    source: str = "人工"
    assignee_id: int | None = None
    due_at: datetime | None = None


class HazardUpdate(BaseModel):
    project_id: int | None = None
    title: str | None = None
    level: str | None = None
    category: str | None = None
    description: str | None = None
    location_desc: str | None = None
    lng: float | None = None
    lat: float | None = None
    discovered_by_name: str | None = None
    discovered_at: datetime | None = None
    source: str | None = None
    assignee_id: int | None = None
    due_at: datetime | None = None


class HazardTransition(BaseModel):
    action: str = Field(
        ...,
        description="流转动作(start_rectify/submit_rectify/verify_pass/verify_reject/reject/reopen)",
    )
    note: str | None = Field(None, description="流转说明(整改说明/复核意见/驳回原因)")


class HazardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    project_name: str | None = None
    title: str
    level: str = "一般"
    category: str | None = None
    description: str | None = None
    location_desc: str | None = None
    lng: float | None = None
    lat: float | None = None
    discovered_by_name: str | None = None
    discovered_at: datetime | None = None
    source: str = "人工"
    source_alarm_id: int | None = None
    status: str = "待整改"
    assignee_id: int | None = None
    assignee_name: str | None = None
    due_at: datetime | None = None
    rectify_note: str | None = None
    rectify_at: datetime | None = None
    verify_by_name: str | None = None
    verify_at: datetime | None = None
    verify_note: str | None = None
    closed_at: datetime | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    is_overdue: bool = False

    @field_serializer(
        "discovered_at",
        "due_at",
        "rectify_at",
        "verify_at",
        "closed_at",
        "created_at",
        "updated_at",
    )
    def _serialize_dt(self, v: datetime | None) -> str | None:
        """带时区时间序列化为「北京时间墙钟」字符串（YYYY-MM-DDTHH:mm:ss）。"""
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class HazardPage(BaseModel):
    total: int
    items: list[HazardOut]
    page: int = 1
    size: int = 20


class HazardStats(BaseModel):
    total: int
    by_status: dict[str, int]
    by_level: dict[str, int]
    overdue: int


# 供前端下拉复用的枚举
HAZARD_LEVEL_OPTIONS = list(HAZARD_LEVELS)
HAZARD_CATEGORY_OPTIONS = list(HAZARD_CATEGORIES)
HAZARD_SOURCE_OPTIONS = list(HAZARD_SOURCES)
HAZARD_STATUS_OPTIONS = list(HAZARD_STATUSES)
