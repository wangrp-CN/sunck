"""MQTT 消息回调与设备协议处理入口（骨架）。

各 `on_message_*` 对应接口需求 §3.1 的上行报文解析：
- 实时定位数据上传（接口 1）
- 大机防侵限上报（接口 3）
- 列车接近上报（接口 5）

骨架阶段仅打印/记录，后续接入：落库、规则判定、WebSocket 推送。
"""

import logging

from paho.mqtt.client import Client, MQTTMessage

logger = logging.getLogger("rail_monitor.mqtt")


def on_connect(client: Client, userdata, flags, reason_code, properties=None) -> None:
    logger.info("MQTT 已连接，订阅设备上行主题")
    client.subscribe("device/+/up", qos=1)


def on_disconnect(client: Client, userdata, disconnect_flags, reason_code, properties=None) -> None:
    logger.warning("MQTT 连接断开：%s", reason_code)


def on_message(client: Client, userdata, msg: MQTTMessage) -> None:
    topic: str = msg.topic
    payload = msg.payload
    logger.debug("MQTT 收到消息 topic=%s size=%s", topic, len(payload))
    # TODO(阶段1): 按 topic 路由到对应 on_message_* 解析并落库/判定/推送


# ---- 设备协议解析入口（后续实现） ----
def on_message_locate(payload: bytes) -> None:
    """接口 1：实时定位数据上传。TODO"""


def on_message_anti_intrusion(payload: bytes) -> None:
    """接口 3：大机防侵限上报。TODO"""


def on_message_train_approach(payload: bytes) -> None:
    """接口 5：列车接近上报。TODO"""
