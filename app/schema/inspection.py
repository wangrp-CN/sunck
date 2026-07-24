"""巡检/打卡 Schema：任务创建/更新/流转、打卡、输出与分页。

时间字段统一以「北京时间墙钟」字符串对外；打卡坐标对外 GCJ-02 由前端转换。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ


class InspectionTaskCreate(BaseModel):
    project_id: int | None = None
    name: str = Field(..., description="巡检任务名称")
    content: str | None = None
    assignee_id: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    required_checkins: int = Field(1, ge=1, description="要求打卡次数")


class InspectionTaskUpdate(BaseModel):
    project_id: int | None = None
    name: str | None = None
    content: str | None = None
    assignee_id: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    required_checkins: int | None = None


class InspectionCheckin(BaseModel):
    checkin_by_name: str | None = Field(None, description="打卡人(缺省为当前用户昵称)")
    lng: float | None = Field(None, description="经度(WGS-84)")
    lat: float | None = Field(None, description="纬度(WGS-84)")
    result: str = Field("正常", description="巡检结果(正常/异常)")
    note: str | None = None


class InspectionRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    project_id: int | None = None
    checkin_by_name: str | None = None
    checkin_at: datetime | None = None
    lng: float | None = None
    lat: float | None = None
    result: str = "正常"
    note: str | None = None
    hazard_id: int | None = None
    created_at: datetime | None = None

    @field_serializer("checkin_at", "created_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class InspectionTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    project_name: str | None = None
    name: str
    content: str | None = None
    assignee_id: int | None = None
    assignee_name: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: str = "待巡检"
    required_checkins: int = 1
    checkin_count: int = 0
    abnormal_count: int = 0
    created_by: int | None = None
    created_at: datetime | None = None
    records: list[InspectionRecordOut] = Field(default_factory=list)

    @field_serializer("start_time", "end_time", "created_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class InspectionTaskPage(BaseModel):
    total: int
    items: list[InspectionTaskOut]
    page: int = 1
    size: int = 20
