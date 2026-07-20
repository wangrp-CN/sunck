"""大型机械管理相关 Schema（请求/响应模型）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MachineCreate(BaseModel):
    project_id: int = Field(..., description="归属项目ID(数据隔离依据)")
    machine_no: str = Field(..., max_length=64, description="大机编号")
    machine_type: str | None = Field(None, max_length=64, description="大机类型")
    spec_model: str | None = Field(None, max_length=128, description="规格及型号")
    description: str | None = Field(None, max_length=512, description="大机设备说明")


class MachineUpdate(BaseModel):
    project_id: int | None = Field(None, description="归属项目ID")
    machine_no: str | None = Field(None, max_length=64, description="大机编号")
    machine_type: str | None = Field(None, max_length=64, description="大机类型")
    spec_model: str | None = Field(None, max_length=128, description="规格及型号")
    description: str | None = Field(None, max_length=512, description="大机设备说明")


class MachineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    machine_no: str
    machine_type: str | None = None
    spec_model: str | None = None
    description: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None


class MachinePage(BaseModel):
    items: list[MachineOut]
    total: int
    page: int
    size: int
