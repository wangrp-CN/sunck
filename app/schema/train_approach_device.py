"""列车接近报警设备列表相关 Schema（请求/响应模型）。

对应 train_approach_device 表（模型 TrainApproachDevice，即「列车接近报警设备」）。
原型《列车接近报警设备列表》+《新增设备》弹窗字段：
项目名称 / 设备名称 / 设备编号(唯一) / 设备SN码 / 设备方位(必填,仅限上行/下行) / 经度 / 纬度 / 设备状态。
status 取自 TRAIN_APPROACH_DEVICE_STATUSES；created_at 按北京时间输出。
经纬度沿用系统约定：入库 WGS-84，展示层转 GCJ-02。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ

# 设备方位可选项（新增/编辑表单固定下拉，不允许手动输入其它值）
TRAIN_APPROACH_DEVICE_DIRECTIONS = ("上行", "下行")
Direction = Literal["上行", "下行"]


class TrainApproachDeviceCreate(BaseModel):
    project_id: int = Field(..., description="归属项目ID(数据隔离依据)")
    name: str = Field(..., max_length=128, description="设备名称")
    device_no: str = Field(..., max_length=64, description="设备编号(唯一)")
    sn: str | None = Field(None, max_length=128, description="设备SN码")
    direction: Direction = Field(..., description="设备方位(上行/下行，必填)")

    longitude: float | None = Field(None, ge=-180, le=180, description="经度(WGS-84)")
    latitude: float | None = Field(None, ge=-90, le=90, description="纬度(WGS-84)")
    status: str = Field("在线", max_length=16, description="设备状态")


class TrainApproachDeviceUpdate(BaseModel):
    project_id: int | None = Field(None, description="归属项目ID")
    name: str | None = Field(None, max_length=128, description="设备名称")
    device_no: str | None = Field(None, max_length=64, description="设备编号")
    sn: str | None = Field(None, max_length=128, description="设备SN码")
    direction: Direction | None = Field(None, description="设备方位(上行/下行)")

    longitude: float | None = Field(None, ge=-180, le=180, description="经度(WGS-84)")
    latitude: float | None = Field(None, ge=-90, le=90, description="纬度(WGS-84)")
    status: str | None = Field(None, max_length=16, description="设备状态")


class TrainApproachDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    # 冗余归属项目名称，列表页「项目名称」列直接展示，免去前端二次字典查询
    project_name: str | None = None
    name: str
    device_no: str
    sn: str | None = None
    direction: str | None = None
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


class TrainApproachDevicePage(BaseModel):
    items: list[TrainApproachDeviceOut]
    total: int
    page: int
    size: int
