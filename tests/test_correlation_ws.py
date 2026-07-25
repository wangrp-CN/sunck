"""跨设备共因事件组实时 WebSocket 推送测试。

覆盖：
- 端点 /ws/correlation 的 HTTP 兜底(426)、握手(ping/pong)、鉴权(无 token 关闭)；
- 发布侧：新增跨设备共因经 Redis 频道发布、指纹去重、非跨设备不发布；
- 分发侧：API 进程经 WS 频道把消息下发给订阅客户端（模拟订阅线程转发）。
"""

import json
from datetime import datetime, timezone

from sqlalchemy import delete
from starlette.websockets import WebSocketDisconnect

from app.core.redis import get_redis_client


def _redis_ok() -> bool:
    try:
        return bool(get_redis_client().ping())
    except Exception:  # noqa: BLE001
        return False


def test_ws_correlation_plain_http_returns_426(client):
    r = client.get("/ws/correlation")
    assert r.status_code == 426, r.text
    body = r.json()
    assert body["code"] == 426
    assert "WebSocket" in body["message"]


def test_ws_correlation_handshake_works(client, admin_token):
    with client.websocket_connect(f"/ws/correlation?token={admin_token}") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_ws_correlation_no_token_closed(client):
    try:
        with client.websocket_connect("/ws/correlation") as ws:
            ws.receive_text()
        assert False, "expected close without token"
    except WebSocketDisconnect:
        pass


def test_publish_new_cross_device_groups(client):
    if not _redis_ok():
        import pytest

        pytest.skip("Redis 不可用，跳过发布侧测试")

    from app.core.database import SessionLocal
    from app.model.correlation import CorrelatedEventGroup
    from app.ws.correlation_pubsub import (
        REDIS_CHANNEL,
        publish_new_cross_device_groups,
    )

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        cross = CorrelatedEventGroup(
            project_id=999001,
            project_name="WS测试项目",
            spatial_type="fence",
            scope_key="WS围栏",
            fence_name="WS围栏",
            started_at=now,
            ended_at=now,
            alarm_count=3,
            device_count=2,
            is_cross_device=True,
            max_level="警告",
            device_nos="[]",
            levels="[]",
            alarm_types="[]",
            alarm_ids="[]",
            root_cause_hint="测试共因",
            computed_at=now,
        )
        single = CorrelatedEventGroup(
            project_id=999002,
            project_name="WS单机",
            spatial_type="device",
            scope_key="dev:1",
            started_at=now,
            ended_at=now,
            alarm_count=1,
            device_count=1,
            is_cross_device=False,
            max_level="提示",
            device_nos="[]",
            levels="[]",
            alarm_types="[]",
            alarm_ids="[]",
            root_cause_hint="单机",
            computed_at=now,
        )
        db.add_all([cross, single])
        db.commit()
        db.refresh(cross)

        r = get_redis_client()
        sub = r.pubsub()
        sub.subscribe(REDIS_CHANNEL)

        # 仅跨设备组应被发布（1 条）
        n = publish_new_cross_device_groups([cross, single])
        assert n == 1

        msg = None
        for _ in range(20):
            m = sub.get_message(ignore_subscribe_messages=True, timeout=0.5)
            if m and m.get("type") == "message":
                msg = json.loads(m["data"])
                break
        assert msg is not None, "未收到 Redis 发布消息"
        assert msg["payload"]["type"] == "correlation"
        assert msg["payload"]["action"] == "new_cross_device"
        assert msg["payload"]["data"]["id"] == cross.id
        assert "corr:global" in msg["ws_channels"]
        assert "corr:project:999001" in msg["ws_channels"]

        # 指纹去重：同一事件再次发布不应重复
        n2 = publish_new_cross_device_groups([cross])
        assert n2 == 0
    finally:
        db.execute(
            delete(CorrelatedEventGroup).where(
                CorrelatedEventGroup.project_id.in_([999001, 999002])
            )
        )
        db.commit()
        db.close()
        try:
            sub.close()
        except Exception:  # noqa: BLE001
            pass


def test_ws_correlation_delivers(client, admin_token):
    from app.ws import bridge

    with client.websocket_connect(f"/ws/correlation?token={admin_token}") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"
        payload = {
            "type": "correlation",
            "action": "new_cross_device",
            "data": {"id": 123, "project_id": 7, "root_cause_hint": "实时推送验证"},
        }
        # 模拟订阅线程转发：直接经 WS 桥下发至 corr:global 频道
        bridge.emit("corr:global", payload)
        raw = ws.receive_text()
        parsed = json.loads(raw)
        assert parsed["type"] == "correlation"
        assert parsed["action"] == "new_cross_device"
        assert parsed["data"]["id"] == 123
