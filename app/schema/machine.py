"""大型机械管理相关 Schema（请求/响应模型）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ


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
    # 冗余归属项目名称，列表页「项目名称」列直接展示，免去前端二次字典查询
    project_name: str | None = None
    machine_no: str
    machine_type: str | None = None
    spec_model: str | None = None
    description: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None

    @field_serializer("created_at")
    def _serialize_created_at(self, v: datetime | None) -> str | None:
        """统一按北京时间输出 `YYYY-MM-DD HH:mm:ss`，前端直接落表格。"""
        if v is None:
            return None
        if v.tzinfo is None:
            return v.strftime("%Y-%m-%d %H:%M:%S")
        return v.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


class MachinePage(BaseModel):
    items: list[MachineOut]
    total: int
    page: int
    size: int
