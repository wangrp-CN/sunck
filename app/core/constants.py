"""全局常量：设备类型与 MQTT Topic 规范。

设备类型（对应需求 §2.7 三类设备）：
- locate           人机定位设备（接口 1 上行 / 接口 2 下行）
- anti_intrusion  大机防侵限设备（接口 3 上行 / 接口 4 下行）
- train_approach  列车接近报警设备（接口 5 上行 / 接口 6 下行）

Topic 规范（方案A：Mosquitto 匿名）：
- 上行（设备→平台）：device/{device_type}/up
- 下行（平台→设备，按设备编号单播）：device/{device_type}/{device_no}/down
- 下行（平台→某类设备广播）：device/{device_type}/down
"""

# 设备类型编码
DEVICE_TYPE_LOCATE = "locate"
DEVICE_TYPE_ANTI_INTRUSION = "anti_intrusion"
DEVICE_TYPE_TRAIN_APPROACH = "train_approach"

DEVICE_TYPES: tuple[str, ...] = (
    DEVICE_TYPE_LOCATE,
    DEVICE_TYPE_ANTI_INTRUSION,
    DEVICE_TYPE_TRAIN_APPROACH,
)

# 设备类型中文名（用于告警展示）
DEVICE_TYPE_LABELS: dict[str, str] = {
    DEVICE_TYPE_LOCATE: "人机定位",
    DEVICE_TYPE_ANTI_INTRUSION: "大机防侵限",
    DEVICE_TYPE_TRAIN_APPROACH: "列车接近",
}

# 告警类型
ALARM_TYPE_FENCE = "fence_intrusion"  # 围栏侵入
ALARM_TYPE_DISTANCE = "distance_too_close"  # 间距过近
ALARM_TYPE_DEVICE = "device_alarm"  # 设备自上报告警（大机/列车等通用自报）
ALARM_TYPE_TRAIN = "train_approach"  # 列车接近预警（train_approach 设备专项）
ALARM_TYPE_ANOMALY = "trend_anomaly"  # 趋势异常检测告警（智能核心：四类序列统计基线法异常）
ALARM_TYPE_FORECAST = "predictive_alert"  # 预测性预警（Phase 5 M3：越阈预测回灌告警流）
ALARM_TYPE_PREVENTIVE = "preventive_alert"  # 预防式预警（预测置信区间越阈提前预警）

# 电子围栏类型（原型《电子围栏列表》查询区与新增/编辑弹窗的下拉可选项）
# 说明：历史数据里 fence_type 曾用作自由文本（人员/大机/列车），因此仅作为
# 前端下拉字典与新数据的推荐取值，后端不做强枚举校验，避免旧数据更新失败。
FENCE_TYPE_NORMAL = "普通防区"
FENCE_TYPE_WARNING = "预警防区"
FENCE_TYPE_ALARM = "报警防区"

FENCE_TYPES: tuple[str, ...] = (
    FENCE_TYPE_NORMAL,
    FENCE_TYPE_WARNING,
    FENCE_TYPE_ALARM,
)

# 设备状态
DEVICE_STATUS_ONLINE = "在线"
DEVICE_STATUS_OFFLINE = "离线"
DEVICE_STATUS_LOW_BATTERY = "低电量"

# 告警状态
ALARM_STATUS_START = "告警开始"
ALARM_STATUS_END = "告警结束"
ALARM_STATUS_CLEARED = "已消警"

# 告警级别 → 隐患级别（告警一键转隐患时映射；缺省落到「一般」）
ALARM_LEVEL_TO_HAZARD_LEVEL: dict[str, str] = {
    "严重": "重大",
    "警告": "较大",
    "提示": "一般",
}

NORMAL_STATUSES = {DEVICE_STATUS_ONLINE, DEVICE_STATUS_OFFLINE, DEVICE_STATUS_LOW_BATTERY}

# ---------------------------------------------------------------------------
# 隐患治理闭环（Hazard）
# ---------------------------------------------------------------------------
# 隐患等级（按严重程度降序）
HAZARD_LEVELS: tuple[str, ...] = ("重大", "较大", "一般", "低")
# 隐患类别
HAZARD_CATEGORIES: tuple[str, ...] = (
    "施工安全",
    "设备设施",
    "环境",
    "管理",
    "其他",
)
# 隐患来源
HAZARD_SOURCES: tuple[str, ...] = ("人工", "巡检", "系统")
# 隐患状态机
HAZARD_STATUS_PENDING = "待整改"
HAZARD_STATUS_RECTIFYING = "整改中"
HAZARD_STATUS_VERIFYING = "待复核"
HAZARD_STATUS_CLOSED = "已销号"
HAZARD_STATUS_REJECTED = "已驳回"
HAZARD_STATUSES: tuple[str, ...] = (
    HAZARD_STATUS_PENDING,
    HAZARD_STATUS_RECTIFYING,
    HAZARD_STATUS_VERIFYING,
    HAZARD_STATUS_CLOSED,
    HAZARD_STATUS_REJECTED,
)
# 状态机合法流转：动作 -> (当前允许状态, 目标状态)
HAZARD_TRANSITIONS: dict[str, tuple[str, str]] = {
    "start_rectify": (HAZARD_STATUS_PENDING, HAZARD_STATUS_RECTIFYING),
    "submit_rectify": (HAZARD_STATUS_RECTIFYING, HAZARD_STATUS_VERIFYING),
    "verify_pass": (HAZARD_STATUS_VERIFYING, HAZARD_STATUS_CLOSED),
    "verify_reject": (HAZARD_STATUS_VERIFYING, HAZARD_STATUS_RECTIFYING),
    "reject": (HAZARD_STATUS_PENDING, HAZARD_STATUS_REJECTED),
    "reopen": (HAZARD_STATUS_REJECTED, HAZARD_STATUS_PENDING),
}
# 终态（不可再流转）
HAZARD_TERMINAL_STATUSES = {HAZARD_STATUS_CLOSED}

# ---------------------------------------------------------------------------
# 根因派单闭环（#80）：派单状态机 + 来源
# ---------------------------------------------------------------------------
DISPATCH_STATUS_PENDING = "待派"  # 已建单未指派/未开始处理
DISPATCH_STATUS_PROCESSING = "处理中"  # 已指派处理人，处置中
DISPATCH_STATUS_CLOSED = "已闭环"  # 处置完成、共因闭环
DISPATCH_STATUSES: tuple[str, ...] = (
    DISPATCH_STATUS_PENDING,
    DISPATCH_STATUS_PROCESSING,
    DISPATCH_STATUS_CLOSED,
)
# 状态机合法流转：动作 -> (当前允许状态, 目标状态)
DISPATCH_TRANSITIONS: dict[str, tuple[str, str]] = {
    "start": (DISPATCH_STATUS_PENDING, DISPATCH_STATUS_PROCESSING),
    "close": (DISPATCH_STATUS_PROCESSING, DISPATCH_STATUS_CLOSED),
    "reopen": (DISPATCH_STATUS_CLOSED, DISPATCH_STATUS_PROCESSING),
}
DISPATCH_TERMINAL_STATUSES = {DISPATCH_STATUS_CLOSED}
# 派单来源：跨设备共因事件组 / 单条告警 / 人工
DISPATCH_SOURCE_CORRELATION = "correlation"
DISPATCH_SOURCE_ALARM = "alarm"
DISPATCH_SOURCE_MANUAL = "manual"
DISPATCH_SOURCES: tuple[str, ...] = (
    DISPATCH_SOURCE_CORRELATION,
    DISPATCH_SOURCE_ALARM,
    DISPATCH_SOURCE_MANUAL,
)
DISPATCH_LEVELS: tuple[str, ...] = ("严重", "警告", "提示")

# ---------------------------------------------------------------------------
# 地图资源库（系统管理·⑧ 地图维护）
# ---------------------------------------------------------------------------
MAP_ASSET_TYPE_STATION_PLAN = "station_plan"  # 站点平面图
MAP_ASSET_TYPE_PLAN_IMAGE = "plan_image"  # 平面图图片
MAP_ASSET_TYPE_SATELLITE = "satellite"  # 卫星影像底图
MAP_ASSET_TYPE_CUSTOM_BASEMAP = "custom_basemap"  # 自定义底图

MAP_ASSET_TYPES: tuple[str, ...] = (
    MAP_ASSET_TYPE_STATION_PLAN,
    MAP_ASSET_TYPE_PLAN_IMAGE,
    MAP_ASSET_TYPE_SATELLITE,
    MAP_ASSET_TYPE_CUSTOM_BASEMAP,
)

MAP_ASSET_TYPE_LABELS: dict[str, str] = {
    MAP_ASSET_TYPE_STATION_PLAN: "站点平面图",
    MAP_ASSET_TYPE_PLAN_IMAGE: "平面图图片",
    MAP_ASSET_TYPE_SATELLITE: "卫星影像底图",
    MAP_ASSET_TYPE_CUSTOM_BASEMAP: "自定义底图",
}

# ---------------------------------------------------------------------------
# 地图手动绘制（系统管理·⑧ 地图维护 - 手动标注）
# ---------------------------------------------------------------------------
MAP_DRAWING_KIND_POINT = "point"  # 画点
MAP_DRAWING_KIND_LINE = "line"  # 画线

MAP_DRAWING_KINDS: tuple[str, ...] = (
    MAP_DRAWING_KIND_POINT,
    MAP_DRAWING_KIND_LINE,
)

MAP_DRAWING_KIND_LABELS: dict[str, str] = {
    MAP_DRAWING_KIND_POINT: "标注点",
    MAP_DRAWING_KIND_LINE: "标注线",
}

MAP_DRAWING_MODE_FREE = "free"  # 自由绘制（地图点击）
MAP_DRAWING_MODE_COORD = "coord"  # 坐标录入
MAP_DRAWING_MODE_ROAD = "road"  # 沿路绘制

MAP_DRAWING_MODES: tuple[str, ...] = (
    MAP_DRAWING_MODE_FREE,
    MAP_DRAWING_MODE_COORD,
    MAP_DRAWING_MODE_ROAD,
)

MAP_DRAWING_MODE_LABELS: dict[str, str] = {
    MAP_DRAWING_MODE_FREE: "自由绘制",
    MAP_DRAWING_MODE_COORD: "坐标录入",
    MAP_DRAWING_MODE_ROAD: "沿路绘制",
}

# 每种 kind 允许的绘制模式
MAP_DRAWING_KIND_MODES: dict[str, tuple[str, ...]] = {
    MAP_DRAWING_KIND_POINT: (MAP_DRAWING_MODE_FREE, MAP_DRAWING_MODE_COORD),
    MAP_DRAWING_KIND_LINE: (MAP_DRAWING_MODE_FREE, MAP_DRAWING_MODE_ROAD),
}

# ---------------------------------------------------------------------------
# 告警处置结果（处置效果闭环）
# ---------------------------------------------------------------------------
DISPOSITION_RESOLVED = "已解决"
DISPOSITION_PARTIAL = "部分解决"
DISPOSITION_UNRESOLVED = "未解决"
DISPOSITION_FALSE_ALARM = "误报"
DISPOSITION_OUTCOMES: tuple[str, ...] = (
    DISPOSITION_RESOLVED,
    DISPOSITION_PARTIAL,
    DISPOSITION_UNRESOLVED,
    DISPOSITION_FALSE_ALARM,
)


# ---------------------------------------------------------------------------
# 项目管理·项目列表（需求：项目状态枚举）
# ---------------------------------------------------------------------------
PROJECT_STATUS_IN_PROGRESS = "在建"
PROJECT_STATUS_SUSPENDED = "停工"
PROJECT_STATUS_COMPLETED = "竣工"
PROJECT_STATUSES: tuple[str, ...] = (
    PROJECT_STATUS_IN_PROGRESS,
    PROJECT_STATUS_SUSPENDED,
    PROJECT_STATUS_COMPLETED,
)
PROJECT_STATUS_LABELS: dict[str, str] = {
    PROJECT_STATUS_IN_PROGRESS: "在建",
    PROJECT_STATUS_SUSPENDED: "停工",
    PROJECT_STATUS_COMPLETED: "竣工",
}


def up_topic(device_type: str) -> str:
    """设备上行主题。"""
    return f"device/{device_type}/up"


def down_topic(device_type: str, device_no: str) -> str:
    """平台向指定设备下发指令（单播）。"""
    return f"device/{device_type}/{device_no}/down"


def down_topic_broadcast(device_type: str) -> str:
    """平台向某类设备广播指令。"""
    return f"device/{device_type}/down"


_ACK_TOPIC_RE = __import__("re").compile(r"^device/([^/]+)/ack$")


def ack_topic(device_no: str) -> str:
    """设备向平台回执指令执行结果（携带 cmd_id 关联下发记录）。"""
    return f"device/{device_no}/ack"


def parse_ack_topic(topic: str) -> str | None:
    """从回执主题解析设备编号；非回执主题返回 None。"""
    m = _ACK_TOPIC_RE.match(topic)
    return m.group(1) if m else None


def ws_channel_for_project(project_id: int | None) -> str:
    """WebSocket 推送频道：按项目分频道；project_id 为空时走全局。"""
    if project_id:
        return f"project:{project_id}"
    return "global"


def ws_channel_for_correlation(project_id: int | None) -> str:
    """WebSocket 跨设备共因事件组推送频道（与告警频道命名空间隔离）。

    订阅端 ``/ws/correlation`` 据此接入；发布端（API 进程订阅线程）向 ``corr:global``
    与 ``corr:project:N`` 双频道广播，保证全局大屏与单项目视图均能收到。
    """
    if project_id:
        return f"corr:project:{project_id}"
    return "corr:global"


def parse_up_topic(topic: str) -> str | None:
    """从上行主题解析设备类型；非法返回 None。"""
    parts = topic.split("/")
    # device/{type}/up
    if len(parts) == 3 and parts[0] == "device" and parts[2] == "up":
        dtype = parts[1]
        return dtype if dtype in DEVICE_TYPES else None
    return None
