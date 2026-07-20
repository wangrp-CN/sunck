"""MQTT 客户端封装（paho-mqtt v2）。

职责：
- 管理 Broker 连接与断线重连（由调用方在启动时触发，不在导入时连接）。
- 提供 `publish` 用于平台向设备下发指令（接口 2/4/6）。
- 注册 `handlers` 中的回调处理设备上行报文（接口 1/3/5）。

Topic 约定（骨架，后续细化）：
- 上行：device/{device_type}/up
- 下行：device/{device_type}/down
"""

from paho.mqtt.client import CallbackAPIVersion, Client

from app.config import settings
from app.mqtt import handlers

_client: Client | None = None


def get_client() -> Client:
    """返回（懒创建）的 MQTT 客户端单例。"""
    global _client
    if _client is None:
        _client = Client(callback_api_version=CallbackAPIVersion.VERSION2)
        _client.on_connect = handlers.on_connect
        _client.on_message = handlers.on_message
        _client.on_disconnect = handlers.on_disconnect
        # 断线重连策略：指数退避，1~30s
        _client.reconnect_delay_set(min_delay=1, max_delay=30)
        if settings.mqtt_username:
            _client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
    return _client


def connect() -> Client:
    """连接 Broker 并启动网络循环（阻塞前请确保在独立线程/loop_start）。"""
    cli = get_client()
    cli.connect(host=settings.mqtt_broker, port=settings.mqtt_port, keepalive=60)
    cli.loop_start()
    return cli


def publish(topic: str, payload: str | bytes, qos: int = 1) -> None:
    """向设备下发指令。"""
    get_client().publish(topic, payload, qos=qos)
