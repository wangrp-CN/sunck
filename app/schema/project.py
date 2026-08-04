"""项目管理相关 Schema（请求/响应模型）。"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import PROJECT_STATUSES


class ProjectCreate(BaseModel):
    name: str = Field(..., max_length=128, description="项目名称")
    dept_id: int | None = Field(None, description="归属部门ID(数据隔离依据，可留空)")
    short_name: str | None = Field(None, max_length=64, description="项目简称")
    intro: str | None = Field(None, max_length=1024, description="项目介绍")
    start_date: date | None = Field(None, description="开工日期")
    end_date: date | None = Field(None, description="完工日期")
    duration: int | None = Field(None, description="项目工期(天)")
    mileage: str | None = Field(None, max_length=64, description="里程")
    section: str | None = Field(None, max_length=128, description="区间")
    coordinate: str | None = Field(None, max_length=128, description="坐标")
    status: str = Field("在建", description="项目状态(在建/停工/竣工)")

    @field_validator("status")
    @classmethod
    def _validate_status_create(cls, v):
        if v not in PROJECT_STATUSES:
            raise ValueError("项目状态必须为：在建 / 停工 / 竣工")
        return v


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, max_length=128, description="项目名称")
    dept_id: int | None = Field(None, description="归属部门ID")
    short_name: str | None = Field(None, max_length=64, description="项目简称")
    intro: str | None = Field(None, max_length=1024, description="项目介绍")
    start_date: date | None = Field(None, description="开工日期")
    end_date: date | None = Field(None, description="完工日期")
    duration: int | None = Field(None, description="项目工期(天)")
    mileage: str | None = Field(None, max_length=64, description="里程")
    section: str | None = Field(None, max_length=128, description="区间")
    coordinate: str | None = Field(None, max_length=128, description="坐标")
    status: str | None = Field(None, description="项目状态")

    @field_validator("status")
    @classmethod
    def _validate_status_update(cls, v):
        if v is not None and v not in PROJECT_STATUSES:
            raise ValueError("项目状态必须为：在建 / 停工 / 竣工")
        return v


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    dept_id: int | None = None
    name: str
    short_name: str | None = None
    intro: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    duration: int | None = None
    mileage: str | None = None
    section: str | None = None
    coordinate: str | None = None
    status: str
    created_by: int | None = None
    created_at: datetime | None = None


class ProjectPage(BaseModel):
    items: list[ProjectOut]
    total: int
    page: int
    size: int
