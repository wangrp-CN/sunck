"""WebSocket 路由：实时告警/位置推送通道。

鉴权：连接时通过 ?token= 携带访问令牌（JWT），非法/缺失直接关闭(4401)。
分频道：?project_id=N 仅订阅该项目频道；否则订阅 global。
心跳：客户端发 "ping" → 服务端回 "pong"。
"""

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.core.constants import ws_channel_for_project
from app.core.security import decode_token
from app.ws.manager import manager

router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/alarm")
async def alarm_ws(
    websocket: WebSocket,
    token: str | None = Query(default=None, description="访问令牌(JWT)"),
    project_id: int | None = Query(default=None, description="按项目订阅频道"),
) -> None:
    """实时告警/位置通道：大屏/前端订阅后接收推送。"""
    # 1) 鉴权
    if not token:
        await websocket.close(code=4401, reason="missing token")
        return
    try:
        decode_token(token, expected_type="access")
    except Exception:
        await websocket.close(code=4401, reason="invalid token")
        return

    # 2) 按项目分频道接入
    channel = ws_channel_for_project(project_id)
    await manager.connect(websocket, channel)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, channel)
    except Exception:  # noqa: BLE001
        manager.disconnect(websocket, channel)
