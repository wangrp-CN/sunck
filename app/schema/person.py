"""人员管理相关 Schema（请求/响应模型）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PersonCreate(BaseModel):
    project_id: int = Field(..., description="归属项目ID(数据隔离依据)")
    person_no: str = Field(..., max_length=64, description="人员工号")
    name: str = Field(..., max_length=64, description="姓名")
    gender: str | None = Field(None, max_length=8, description="性别")
    phone: str | None = Field(None, max_length=32, description="电话")
    person_type: str | None = Field(None, max_length=32, description="人员类型(防护/施工/管理)")
    device_no: str | None = Field(None, max_length=64, description="绑定定位设备编号")


class PersonUpdate(BaseModel):
    project_id: int | None = Field(None, description="归属项目ID")
    person_no: str | None = Field(None, max_length=64, description="人员工号")
    name: str | None = Field(None, max_length=64, description="姓名")
    gender: str | None = Field(None, max_length=8, description="性别")
    phone: str | None = Field(None, max_length=32, description="电话")
    person_type: str | None = Field(None, max_length=32, description="人员类型")
    device_no: str | None = Field(None, max_length=64, description="绑定定位设备编号")


class PersonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    person_no: str
    name: str
    gender: str | None = None
    phone: str | None = None
    person_type: str | None = None
    icon: str | None = None
    device_no: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None


class PersonPage(BaseModel):
    items: list[PersonOut]
    total: int
    page: int
    size: int
