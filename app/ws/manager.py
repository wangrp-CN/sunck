"""WebSocket 连接管理器（内存版，按项目/部门分频道）。

后续接入 Redis Pub/Sub 以支持多实例广播（见《开发计划》难点 2）。
"""

import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger("rail_monitor.ws")


class ConnectionManager:
    def __init__(self) -> None:
        # channel -> set of websockets
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, ws: WebSocket, channel: str = "global") -> None:
        await ws.accept()
        self._channels[channel].add(ws)
        logger.info("WS 已连接 channel=%s total=%d", channel, len(self._channels[channel]))

    def disconnect(self, ws: WebSocket, channel: str = "global") -> None:
        self._channels[channel].discard(ws)

    async def send_personal(self, ws: WebSocket, message: str) -> None:
        await ws.send_text(message)

    async def broadcast(self, channel: str, message: str) -> None:
        """向某频道广播消息。"""
        dead = []
        for ws in list(self._channels.get(channel, set())):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append((channel, ws))
        for ch, ws in dead:
            self.disconnect(ws, ch)


manager = ConnectionManager()
