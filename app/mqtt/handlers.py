"""MQTT 消息回调与设备协议处理入口。

对应接口需求 §3.1 的上行报文解析：
- 实时定位数据上传（接口 1）→ locate
- 大机防侵限上报（接口 3）→ anti_intrusion
- 列车接近上报（接口 5）→ train_approach

消息经协议层解析 → 实时链路编排（落库/规则/告警/推送），
见 app.service.pipeline.handle_upstream。
"""

import json
import logging

from paho.mqtt.client import Client, MQTTMessage

from app.core.constants import parse_ack_topic, parse_up_topic
from app.core.database import SessionLocal
from app.core.ingest import enqueue as ingest_enqueue
from app.core.metrics import MQTT_MESSAGES_TOTAL
from app.mqtt import protocol
from app.service import command_service

logger = logging.getLogger("rail_monitor.mqtt")


def on_connect(client: Client, userdata, flags, reason_code, properties=None) -> None:
    logger.info("MQTT 已连接，订阅设备上行/回执主题")
    # 订阅全部设备上行：device/{type}/up
    client.subscribe("device/+/up", qos=1)
    # 订阅设备指令回执：device/{device_no}/ack（用于闭环状态追踪）
    client.subscribe("device/+/ack", qos=1)


def on_disconnect(client: Client, userdata, disconnect_flags, reason_code, properties=None) -> None:
    # paho 在 loop_start 下会自动按 reconnect_delay_set 重连，此处仅记录。
    logger.warning("MQTT 连接断开 reason=%s（将自动重连）", reason_code)


def _handle_ack(topic: str, payload: bytes) -> None:
    """处理设备指令回执：解析 cmd_id，更新下发记录状态。"""
    device_no = parse_ack_topic(topic)
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("指令回执 JSON 解析失败 device=%s: %s", device_no, exc)
        return
    cmd_id = data.get("cmd_id")
    if cmd_id is None:
        logger.debug("指令回执缺少 cmd_id，忽略 device=%s", device_no)
        return
    ok = data.get("status", "ok") not in ("fail", "failed", "error", False)
    detail = data.get("detail")
    # MQTT 回调线程需独立会话；用完即关，避免连接泄漏。
    db = SessionLocal()
    try:
        command_service.ack_command(db, int(cmd_id), ok=ok, detail=detail)
    except Exception:  # noqa: BLE001
        logger.exception("指令回执处理异常 cmd_id=%s device=%s", cmd_id, device_no)
    finally:
        db.close()


def on_message(client: Client, userdata, msg: MQTTMessage) -> None:
    topic: str = msg.topic
    if parse_ack_topic(topic) is not None:
        _handle_ack(topic, msg.payload)
        return
    dtype = parse_up_topic(topic)
    if dtype is None:
        logger.debug("忽略非上行/回执主题: %s", topic)
        return
    MQTT_MESSAGES_TOTAL.labels(device_type=dtype).inc()
    try:
        parsed = protocol.parse_up(dtype, msg.payload)
    except protocol.ProtocolError as exc:
        logger.warning("报文解析失败 topic=%s: %s", topic, exc)
        return
    try:
        # 入队由工作线程池异步处理（解耦接收与落库，提升洪泛吞吐、避免池争用）。
        # 未启用/队列满时 enqueue 内部自动回退同步处理，不丢报文。
        ingest_enqueue(dtype, parsed)
    except Exception:  # noqa: BLE001
        logger.exception("上行入队异常 device=%s/%s", dtype, parsed.get("device_no"))
