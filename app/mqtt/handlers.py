"""MQTT 消息回调与设备协议处理入口。

对应接口需求 §3.1 的上行报文解析：
- 实时定位数据上传（接口 1）→ locate
- 大机防侵限上报（接口 3）→ anti_intrusion
- 列车接近上报（接口 5）→ train_approach

消息经协议层解析 → 实时链路编排（落库/规则/告警/推送），
见 app.service.pipeline.handle_upstream。
"""

import logging

from paho.mqtt.client import Client, MQTTMessage

from app.core.constants import parse_up_topic
from app.core.metrics import MQTT_MESSAGES_TOTAL
from app.mqtt import protocol
from app.service import pipeline

logger = logging.getLogger("rail_monitor.mqtt")


def on_connect(client: Client, userdata, flags, reason_code, properties=None) -> None:
    logger.info("MQTT 已连接，订阅设备上行主题")
    # 订阅全部设备上行：device/{type}/up
    client.subscribe("device/+/up", qos=1)


def on_disconnect(client: Client, userdata, disconnect_flags, reason_code, properties=None) -> None:
    # paho 在 loop_start 下会自动按 reconnect_delay_set 重连，此处仅记录。
    logger.warning("MQTT 连接断开 reason=%s（将自动重连）", reason_code)


def on_message(client: Client, userdata, msg: MQTTMessage) -> None:
    topic: str = msg.topic
    dtype = parse_up_topic(topic)
    if dtype is None:
        logger.debug("忽略非上行主题: %s", topic)
        return
    MQTT_MESSAGES_TOTAL.labels(device_type=dtype).inc()
    try:
        parsed = protocol.parse_up(dtype, msg.payload)
    except protocol.ProtocolError as exc:
        logger.warning("报文解析失败 topic=%s: %s", topic, exc)
        return
    try:
        result = pipeline.handle_upstream(dtype, parsed)
        logger.info(
            "上行已处理 %s/%s 告警=%d", dtype, parsed.get("device_no"), result["alarms_created"]
        )
    except Exception:  # noqa: BLE001
        logger.exception("上行处理异常 device=%s/%s", dtype, parsed.get("device_no"))
