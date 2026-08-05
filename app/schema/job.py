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


class PersonBindingIn(BaseModel):
    """第二步·人员及设备：一行 = 人员 + 其定位设备。"""

    person_id: int
    device_no: str | None = None


class MachineBindingIn(BaseModel):
    """第二步·大型机械：一行 = 大机 + 防护/驾驶人员 + 三类车载设备。"""

    machine_id: int
    guard_person_id: int | None = None
    driver_person_id: int | None = None
    arm_device_no: str | None = None
    body_device_no: str | None = None
    voice_device_no: str | None = None


class FenceRuleIn(BaseModel):
    """第三步·电子围栏：一行 = 围栏 + 该围栏的规则四要素。"""

    fence_id: int
    monitor_target: str | None = None
    trigger_condition: str | None = None
    time_range: str | None = None
    dwell_time: int | None = 0


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
    # 结构化绑定（原型三步向导）；给出时优先于上面的 *_ids 简写
    person_bindings: list[PersonBindingIn] | None = None
    machine_bindings: list[MachineBindingIn] | None = None
    fence_rules: list[FenceRuleIn] | None = None


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
    person_bindings: list[PersonBindingIn] | None = None
    machine_bindings: list[MachineBindingIn] | None = None
    fence_rules: list[FenceRuleIn] | None = None


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


class PersonBindingOut(BaseModel):
    """人员绑定明细（含回显名称/编号，对应原型第二步人员表四列）。"""

    person_id: int
    person_name: str | None = None
    person_no: str | None = None
    device_no: str | None = None
    device_name: str | None = None


class MachineBindingOut(BaseModel):
    """大机绑定明细（对应原型第二步大机表六列）。"""

    machine_id: int
    machine_no: str | None = None
    machine_type: str | None = None
    guard_person_id: int | None = None
    guard_person_name: str | None = None
    driver_person_id: int | None = None
    driver_person_name: str | None = None
    arm_device_no: str | None = None
    arm_device_name: str | None = None
    body_device_no: str | None = None
    body_device_name: str | None = None
    voice_device_no: str | None = None
    voice_device_name: str | None = None


class FenceRuleOut(BaseModel):
    """围栏规则明细（对应原型第三步围栏表五列）。"""

    fence_id: int
    fence_name: str | None = None
    monitor_target: str | None = None
    trigger_condition: str | None = None
    time_range: str | None = None
    dwell_time: int | None = None


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
    # 结构化绑定明细（原型三步向导回显）
    person_bindings: list[PersonBindingOut] = Field(default_factory=list)
    machine_bindings: list[MachineBindingOut] = Field(default_factory=list)
    fence_rules: list[FenceRuleOut] = Field(default_factory=list)

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
