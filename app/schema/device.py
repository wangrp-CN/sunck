"""设备管理相关 Schema（请求/响应模型）。

三类设备（人机定位 / 大机防侵限 / 列车接近）共用一套统一结构：
- 公共字段：project_id / name / device_no / sn / status / device_type
- locate 额外：function
- anti_intrusion / train_approach 额外：longitude / latitude
- train_approach 额外：direction
响应统一为 DeviceOut（无关字段为 None）。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

_DEVICE_TYPES = ("locate", "anti_intrusion", "train_approach")


class DeviceCreate(BaseModel):
    device_type: str = Field(..., description="设备类型(locate/anti_intrusion/train_approach)")
    project_id: int = Field(..., description="归属项目ID(数据隔离依据)")
    name: str = Field(..., max_length=128, description="设备名称")
    device_no: str = Field(..., max_length=64, description="设备编号(唯一)")
    sn: str | None = Field(None, max_length=128, description="设备SN码")
    status: str = Field("在线", description="设备状态(在线/离线/低电量)")
    # locate 型
    function: str | None = Field(None, max_length=255, description="设备功能(locate)")
    # anti_intrusion / train_approach 型
    longitude: float | None = Field(None, description="经度")
    latitude: float | None = Field(None, description="纬度")
    # train_approach 型
    direction: str | None = Field(None, max_length=32, description="设备方位(train_approach)")


class DeviceUpdate(BaseModel):
    project_id: int | None = Field(None, description="归属项目ID")
    name: str | None = Field(None, max_length=128, description="设备名称")
    device_no: str | None = Field(None, max_length=64, description="设备编号")
    sn: str | None = Field(None, max_length=128, description="设备SN码")
    status: str | None = Field(None, description="设备状态")
    function: str | None = Field(None, max_length=255, description="设备功能(locate)")
    longitude: float | None = Field(None, description="经度")
    latitude: float | None = Field(None, description="纬度")
    direction: str | None = Field(None, max_length=32, description="设备方位(train_approach)")


class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_type: str | None = None
    project_id: int | None = None
    name: str
    device_no: str
    sn: str | None = None
    status: str
    function: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    direction: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None


class DevicePage(BaseModel):
    items: list[DeviceOut]
    total: int
    page: int
    size: int


def validate_device_type(dt: str) -> str:
    if dt not in _DEVICE_TYPES:
        from app.core.exceptions import BusinessError

        raise BusinessError(f"未知设备类型: {dt}", code=400)
    return dt
