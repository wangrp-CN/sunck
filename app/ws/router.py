"""WebSocket 路由（骨架占位）。"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.ws.manager import manager

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/alarm")
async def alarm_ws(websocket: WebSocket, channel: str = "global") -> None:
    """实时告警通道：大屏/前端订阅后接收告警推送。

    骨架阶段：接受连接、处理心跳(ping/pong)、断开清理。广播逻辑后续接入。
    """
    await manager.connect(websocket, channel)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel)
