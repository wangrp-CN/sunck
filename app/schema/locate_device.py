"""人机定位设备列表相关 Schema（请求/响应模型）。

对应 locate_device 表（模型 LocateDevice，即「人机定位设备」）。
device_type 为自由文本子类型（人员手持机/工牌/手环定位设备、大机机械定位设备），
status 取自 LOCATE_DEVICE_STATUSES。created_at 按北京时间输出。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ


class LocateDeviceCreate(BaseModel):
    project_id: int = Field(..., description="归属项目ID(数据隔离依据)")
    name: str = Field(..., max_length=128, description="设备名称")
    device_no: str = Field(..., max_length=64, description="设备编号(唯一)")
    device_type: str | None = Field(None, max_length=32, description="设备类型")
    function: str | None = Field(None, max_length=255, description="设备功能")
    sn: str | None = Field(None, max_length=128, description="设备SN码")
    status: str = Field("在线", max_length=16, description="设备状态")


class LocateDeviceUpdate(BaseModel):
    project_id: int | None = Field(None, description="归属项目ID")
    name: str | None = Field(None, max_length=128, description="设备名称")
    device_no: str | None = Field(None, max_length=64, description="设备编号")
    device_type: str | None = Field(None, max_length=32, description="设备类型")
    function: str | None = Field(None, max_length=255, description="设备功能")
    sn: str | None = Field(None, max_length=128, description="设备SN码")
    status: str | None = Field(None, max_length=16, description="设备状态")


class LocateDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    # 冗余归属项目名称，列表页「项目名称」列直接展示，免去前端二次字典查询
    project_name: str | None = None
    name: str
    device_no: str
    device_type: str | None = None
    function: str | None = None
    sn: str | None = None
    status: str
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


class LocateDevicePage(BaseModel):
    items: list[LocateDeviceOut]
    total: int
    page: int
    size: int
