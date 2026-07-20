"""WebSocket 桥接：将 MQTT 消费线程中的推送事件投递到主事件循环。

MQTT(paho) 在独立网络线程中回调；WebSocket 管理器为 async。桥接在应用启动时
捕获主事件循环，后续在任意线程调用 emit() 即可跨线程安全推送。
"""

import asyncio
import json
import logging
from typing import Any

from app.ws.manager import manager

logger = logging.getLogger("rail_monitor.ws.bridge")

_loop = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """由应用 lifespan 注入运行中的事件循环。"""
    global _loop
    _loop = loop
    logger.info("WS 桥接事件循环已绑定")


def emit(channel: str, payload: dict[str, Any]) -> None:
    """向指定频道广播一条消息（自动 JSON 序列化）。"""
    message = json.dumps(payload, ensure_ascii=False, default=str)
    if _loop is None:
        logger.warning("WS 桥接未绑定事件循环，丢弃消息 channel=%s", channel)
        return
    try:
        asyncio.run_coroutine_threadsafe(manager.broadcast(channel, message), _loop)
    except Exception as exc:  # noqa: BLE001
        logger.warning("WS 推送失败 channel=%s: %s", channel, exc)
