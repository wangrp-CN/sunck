"""作业计划管理 Schema：三步式（基本信息 → 绑资源 → 绑围栏+规则）。

v2 增强：规则结构化（monitor_target / trigger_conditions / dwell_time），
并新增结构化时间窗 plan_start / plan_end（用于规则引擎时间范围门控）。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ


class DeviceBinding(BaseModel):
    device_type: str = Field(..., description="设备类型(locate/anti_intrusion/train_approach)")
    device_no: str = Field(..., description="设备编号")


class WorkPlanRule(BaseModel):
    """规则配置（规则引擎 v2 解析为判定输入）。

    - monitor_target：主要监控对象（展示/分组用，如 person/machine/train/all）。
    - trigger_conditions：权威触发条件列表，值域为
      {fence_intrusion, distance_too_close, device_alarm}，空/None 表示不限制。
    - time_range：展示用时间范围文本（具体门控由 plan_start/plan_end 承担）。
    - dwell_time：停留时长(秒)，设备须持续违规该时长后才产生告警（0/None 表示立即）。
    """

    monitor_target: str | None = None
    trigger_conditions: list[str] | None = None
    time_range: str | None = None
    dwell_time: int | None = None


class WorkPlanCreate(BaseModel):
    project_id: int | None = None
    name: str = Field(..., description="计划名称")
    is_start: bool = False
    description: str | None = None
    plan_time: str | None = None
    plan_start: datetime | None = None
    plan_end: datetime | None = None
    status: str = "草稿"
    rule: WorkPlanRule | None = None
    person_ids: list[int] = Field(default_factory=list)
    machine_ids: list[int] = Field(default_factory=list)
    device_bindings: list[DeviceBinding] = Field(default_factory=list)
    fence_ids: list[int] = Field(default_factory=list)


class WorkPlanUpdate(BaseModel):
    project_id: int | None = None
    name: str | None = None
    is_start: bool | None = None
    description: str | None = None
    plan_time: str | None = None
    plan_start: datetime | None = None
    plan_end: datetime | None = None
    status: str | None = None
    rule: WorkPlanRule | None = None
    person_ids: list[int] | None = None
    machine_ids: list[int] | None = None
    device_bindings: list[DeviceBinding] | None = None
    fence_ids: list[int] | None = None


class BoundPerson(BaseModel):
    id: int
    name: str


class BoundMachine(BaseModel):
    id: int
    name: str


class BoundDevice(BaseModel):
    device_type: str
    device_no: str
    name: str | None = None


class BoundFence(BaseModel):
    id: int
    name: str | None = None


class WorkPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    project_name: str | None = None
    name: str
    is_start: bool = False
    description: str | None = None
    plan_time: str | None = None
    plan_start: datetime | None = None
    plan_end: datetime | None = None
    actual_start: datetime | None = None
    actual_end: datetime | None = None
    status: str = "草稿"
    is_template: bool = False
    active: bool = False
    rule: WorkPlanRule | None = None
    created_by: int | None = None
    created_at: str | None = None
    persons: list[BoundPerson] = Field(default_factory=list)
    machines: list[BoundMachine] = Field(default_factory=list)
    devices: list[BoundDevice] = Field(default_factory=list)
    fences: list[BoundFence] = Field(default_factory=list)

    @field_serializer("plan_start", "plan_end", "actual_start", "actual_end")
    def _serialize_plan_dt(self, v: datetime | None) -> str | None:
        """带时区时间序列化为「北京时间墙钟」字符串（YYYY-MM-DDTHH:mm:ss），
        与前端 el-date-picker 的 value-format 对齐；读取为 aware 后按北京截去时区。
        """
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class WorkPlanPage(BaseModel):
    total: int
    items: list[WorkPlanOut]
