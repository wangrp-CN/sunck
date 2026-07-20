"""MQTT 设备协议适配层（对应接口需求 §3.1 的 6 个接口）。

上行（设备→平台，接口 1/3/5）：
- parse_up(device_type, payload) → 归一化字典，非法报文抛 ValueError。
下行（平台→设备，接口 2/4/6）：
- build_command(device_type, action, params) → 下发报文 dict，动作非法抛 ValueError。

设计：协议适配器模式，新增设备类型只需在此扩展字段与动作，
不改动 handler 主流程。
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.constants import (
    DEVICE_STATUS_LOW_BATTERY,
    DEVICE_STATUS_OFFLINE,
    DEVICE_STATUS_ONLINE,
    DEVICE_TYPE_ANTI_INTRUSION,
    DEVICE_TYPE_LOCATE,
    DEVICE_TYPE_TRAIN_APPROACH,
)

logger = logging.getLogger("rail_monitor.mqtt.protocol")

_VALID_STATUS = {DEVICE_STATUS_ONLINE, DEVICE_STATUS_OFFLINE, DEVICE_STATUS_LOW_BATTERY}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_float(v: Any, field: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"字段 {field} 必须为数值")


class ProtocolError(ValueError):
    """报文协议错误（解析/封装失败）。"""


def _decode(payload: bytes) -> dict:
    if not payload:
        raise ProtocolError("空报文")
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"JSON 解析失败: {exc}")
    if not isinstance(data, dict):
        raise ProtocolError("报文顶层必须为 JSON 对象")
    return data


def _require(data: dict, field: str) -> Any:
    if field not in data or data[field] in (None, ""):
        raise ProtocolError(f"缺少必填字段: {field}")
    return data[field]


def _parse_common(data: dict) -> dict:
    out: dict[str, Any] = {}
    out["device_no"] = str(_require(data, "device_no"))
    status = data.get("status")
    if status is not None and status not in _VALID_STATUS:
        raise ProtocolError(f"非法设备状态: {status}")
    out["status"] = status or DEVICE_STATUS_ONLINE
    ts = data.get("timestamp")
    if ts:
        try:
            if isinstance(ts, (int, float)):
                out["report_time"] = datetime.fromtimestamp(ts, tz=timezone.utc)
            else:
                out["report_time"] = datetime.fromisoformat(str(ts))
        except (ValueError, OSError) as exc:
            raise ProtocolError(f"非法时间戳: {exc}")
    else:
        out["report_time"] = None
    return out


def parse_up(device_type: str, payload: bytes) -> dict:
    """解析上行报文，返回归一化 dict（含 device_type 字段）。"""
    data = _decode(payload)
    out = _parse_common(data)
    out["device_type"] = device_type

    if device_type == DEVICE_TYPE_LOCATE:
        # 接口 1：实时定位数据上传
        out["longitude"] = _as_float(_require(data, "longitude"), "longitude")
        out["latitude"] = _as_float(_require(data, "latitude"), "latitude")
        if data.get("accuracy") is not None:
            out["accuracy"] = _as_float(data["accuracy"], "accuracy")
        if data.get("speed") is not None:
            out["speed"] = _as_float(data["speed"], "speed")
        if data.get("bearing") is not None:
            out["bearing"] = _as_float(data["bearing"], "bearing")
    elif device_type in (DEVICE_TYPE_ANTI_INTRUSION, DEVICE_TYPE_TRAIN_APPROACH):
        # 接口 3 / 接口 5：大机防侵限 / 列车接近上报
        # 坐标可选（设备侧可能携带）
        if data.get("longitude") is not None and data.get("latitude") is not None:
            out["longitude"] = _as_float(data["longitude"], "longitude")
            out["latitude"] = _as_float(data["latitude"], "latitude")
        out["alarm_status"] = data.get("alarm_status")
        out["alarm_info"] = data.get("alarm_info")
        if data.get("speed") is not None:
            out["speed"] = _as_float(data["speed"], "speed")
        # 设备专属字段
        if device_type == DEVICE_TYPE_ANTI_INTRUSION:
            out["image"] = data.get("image")
            out["video"] = data.get("video")
        else:  # train_approach
            out["lane"] = data.get("lane")
            out["direction"] = data.get("direction")
    else:
        raise ProtocolError(f"未知设备类型: {device_type}")
    return out


# ---------------------------------------------------------------------------
# 下行指令封装（接口 2/4/6）
# ---------------------------------------------------------------------------

# 各设备类型支持的指令动作
_DOWNLINK_ACTIONS: dict[str, set[str]] = {
    DEVICE_TYPE_LOCATE: {"upload_interval", "alarm", "sound", "light", "restart"},
    DEVICE_TYPE_ANTI_INTRUSION: {
        "camera",
        "capture",
        "radar_sensitivity",
        "arm",
        "barrier",
        "alarm",
        "restart",
    },
    DEVICE_TYPE_TRAIN_APPROACH: {"radar_sensitivity", "alarm", "sound", "restart"},
}


def build_command(device_type: str, action: str, params: dict | None) -> dict:
    """封装平台→设备下发指令报文。

    返回形如 {"action": ..., "params": ..., "ts": <iso>} 的 dict（由调用方序列化并发布）。
    """
    if device_type not in _DOWNLINK_ACTIONS:
        raise ProtocolError(f"未知设备类型: {device_type}")
    allowed = _DOWNLINK_ACTIONS[device_type]
    if action not in allowed:
        raise ProtocolError(f"设备类型 {device_type} 不支持动作 {action}，可选：{sorted(allowed)}")
    params = params or {}
    # 简单参数校验（布尔/数值）
    for k, v in params.items():
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            continue
        if isinstance(v, str) and v != "":
            continue
        raise ProtocolError(f"参数 {k} 取值非法")
    return {"action": action, "params": params, "ts": _now_iso()}
