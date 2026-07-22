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

# 设备状态
DEVICE_STATUS_ONLINE = "在线"
DEVICE_STATUS_OFFLINE = "离线"
DEVICE_STATUS_LOW_BATTERY = "低电量"

# 告警状态
ALARM_STATUS_START = "告警开始"
ALARM_STATUS_END = "告警结束"
ALARM_STATUS_CLEARED = "已消警"

NORMAL_STATUSES = {DEVICE_STATUS_ONLINE, DEVICE_STATUS_OFFLINE, DEVICE_STATUS_LOW_BATTERY}


def up_topic(device_type: str) -> str:
    """设备上行主题。"""
    return f"device/{device_type}/up"


def down_topic(device_type: str, device_no: str) -> str:
    """平台向指定设备下发指令（单播）。"""
    return f"device/{device_type}/{device_no}/down"


def down_topic_broadcast(device_type: str) -> str:
    """平台向某类设备广播指令。"""
    return f"device/{device_type}/down"


def ws_channel_for_project(project_id: int | None) -> str:
    """WebSocket 推送频道：按项目分频道；project_id 为空时走全局。"""
    if project_id:
        return f"project:{project_id}"
    return "global"


def parse_up_topic(topic: str) -> str | None:
    """从上行主题解析设备类型；非法返回 None。"""
    parts = topic.split("/")
    # device/{type}/up
    if len(parts) == 3 and parts[0] == "device" and parts[2] == "up":
        dtype = parts[1]
        return dtype if dtype in DEVICE_TYPES else None
    return None
