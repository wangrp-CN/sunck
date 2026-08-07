"""大机防侵限设备列表相关 Schema（请求/响应模型）。

对应 anti_intrusion_device 表（模型 AntiIntrusionDevice，即「大机防侵限设备」）。
原型《大机防侵限设备列表》+《新增设备》弹窗字段：
项目名称 / 设备名称 / 设备编号(唯一) / 设备SN码 / 经度 / 纬度 / 设备状态。
status 取自 ANTI_INTRUSION_DEVICE_STATUSES；created_at 按北京时间输出。
经纬度沿用系统约定：入库 WGS-84，展示层转 GCJ-02。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ


class AntiIntrusionDeviceCreate(BaseModel):
    project_id: int = Field(..., description="归属项目ID(数据隔离依据)")
    name: str = Field(..., max_length=128, description="设备名称")
    device_no: str = Field(..., max_length=64, description="设备编号(唯一)")
    sn: str | None = Field(None, max_length=128, description="设备SN码")
    longitude: float | None = Field(None, ge=-180, le=180, description="经度(WGS-84)")
    latitude: float | None = Field(None, ge=-90, le=90, description="纬度(WGS-84)")
    status: str = Field("在线", max_length=16, description="设备状态")


class AntiIntrusionDeviceUpdate(BaseModel):
    project_id: int | None = Field(None, description="归属项目ID")
    name: str | None = Field(None, max_length=128, description="设备名称")
    device_no: str | None = Field(None, max_length=64, description="设备编号")
    sn: str | None = Field(None, max_length=128, description="设备SN码")
    longitude: float | None = Field(None, ge=-180, le=180, description="经度(WGS-84)")
    latitude: float | None = Field(None, ge=-90, le=90, description="纬度(WGS-84)")
    status: str | None = Field(None, max_length=16, description="设备状态")


class AntiIntrusionDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    # 冗余归属项目名称，列表页「项目名称」列直接展示，免去前端二次字典查询
    project_name: str | None = None
    name: str
    device_no: str
    sn: str | None = None
    longitude: float | None = None
    latitude: float | None = None
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


class AntiIntrusionDevicePage(BaseModel):
    items: list[AntiIntrusionDeviceOut]
    total: int
    page: int
    size: int
