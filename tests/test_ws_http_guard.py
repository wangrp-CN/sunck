"""回归测试：WebSocket 实时通道（/ws/alarm）被裸 HTTP 访问时不再回 404 Not Found。

背景：/ws/alarm 仅注册为 WebSocket 路由；未带 Upgrade 的裸 HTTP 请求（监控探针、
反向代理未透传 Upgrade、手动 curl）会触发 Starlette 默认 404 detail="Not Found"，
前端/控制台据此报「message: Not Found」。main.py 已为 /ws/{path} 增加 HTTP 兜底，
返回 426 Upgrade Required 与明确指引，同时真实 WebSocket 握手不受影响。
"""

from starlette.websockets import WebSocketDisconnect


def test_ws_alarm_plain_http_returns_426_not_404(client):
    r = client.get("/ws/alarm")
    assert r.status_code == 426, r.text
    body = r.json()
    assert body["code"] == 426
    assert "WebSocket" in body["message"]


def test_ws_alarm_handshake_still_works(client, admin_token):
    with client.websocket_connect(f"/ws/alarm?token={admin_token}") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_ws_alarm_no_token_closed(client):
    try:
        with client.websocket_connect("/ws/alarm") as ws:
            ws.receive_text()
        assert False, "expected close without token"
    except WebSocketDisconnect:
        pass
