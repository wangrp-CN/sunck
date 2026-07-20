"""阶段1 实时链路测试：协议 / 落库 / 规则 / 告警去重 / WebSocket 鉴权。

直接驱动 app.service.pipeline.handle_upstream（不经真实 MQTT），
验证 ① 落库 ② 围栏侵入告警 ③ 间距阈值告警 ④ 去重 ⑤ WS 推送（捕获 emit）。
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.core.constants import (
    ALARM_TYPE_DEVICE,
    ALARM_TYPE_DISTANCE,
    ALARM_TYPE_FENCE,
    DEVICE_TYPE_ANTI_INTRUSION,
    DEVICE_TYPE_LOCATE,
)
from app.core.database import SessionLocal
from app.core.redis import get_redis_client
from app.core.security import create_access_token
from app.main import app
from app.model.alarm import Alarm
from app.model.device import AntiIntrusionDevice, LocateDevice
from app.model.fence import ElectronicFence
from app.model.job import WorkPlan, WorkPlanDevice, WorkPlanFence
from app.model.project import Project
from app.model.realtime import DeviceLocation
from app.model.system import User
from app.mqtt import client as mqtt_client
from app.service.location_service import save_location
from app.service.pipeline import handle_upstream
from app.ws import bridge

_FENCE_WKT = (
    "POLYGON(("
    "121.4995 31.2195, 121.5005 31.2195, "
    "121.5005 31.2205, 121.4995 31.2205, "
    "121.4995 31.2195))"
)


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def clear_dedup():
    """每个测试前清理 TEST- 设备的告警去重键，避免跨用例污染。"""
    r = get_redis_client()
    for key in r.keys("alarm:dedup:TEST-*"):
        r.delete(key)
    yield


@pytest.fixture
def isolated(db_session):
    """隔离数据：测试项目 + 围栏 + 定位设备 + 一个激活作业计划（v2 判定前提）。

    规则引擎 v2 仅对「激活且覆盖该设备」的作业计划产生告警，故此处创建一个
    执行中、无时间窗限制、绑定本围栏、全触发条件、dwell_time=0（立即）的计划；
    设备不做绑定 => 计划覆盖项目内全部设备，参考大机回落到项目全部大机。
    用例结束后连同关联表一并清理。
    """
    proj = Project(name="__t__proj", dept_id=None, status="在建")
    db_session.add(proj)
    db_session.flush()
    fence = ElectronicFence(
        project_id=proj.id,
        name="__t__fence",
        fence_type="人员禁区",
        enabled=True,
        geometry_wkt=_FENCE_WKT,
    )
    db_session.add(fence)
    loc = LocateDevice(project_id=proj.id, name="__t__loc", device_no="TEST-LOC-1", status="在线")
    db_session.add(loc)
    db_session.flush()

    plan = WorkPlan(
        project_id=proj.id,
        name="__t__plan",
        is_start=True,
        status="执行中",
        plan_start=None,
        plan_end=None,
        rule_json=json.dumps(
            {
                "monitor_target": "人员/设备",
                "trigger_conditions": [
                    ALARM_TYPE_FENCE,
                    ALARM_TYPE_DISTANCE,
                    ALARM_TYPE_DEVICE,
                ],
                "dwell_time": 0,
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(plan)
    db_session.flush()
    db_session.add(WorkPlanFence(plan_id=plan.id, fence_id=fence.id))
    db_session.commit()  # 必须提交：pipeline 使用独立会话，需可见本项目/围栏/计划与外键
    yield proj, fence, loc
    db_session.execute(delete(WorkPlanFence).where(WorkPlanFence.plan_id == plan.id))
    db_session.execute(delete(WorkPlanDevice).where(WorkPlanDevice.plan_id == plan.id))
    db_session.execute(delete(WorkPlan).where(WorkPlan.id == plan.id))
    db_session.execute(delete(Alarm).where(Alarm.device_no == "TEST-LOC-1"))
    db_session.execute(delete(Alarm).where(Alarm.device_no == "TEST-AI-1"))
    db_session.execute(delete(DeviceLocation).where(DeviceLocation.device_no == "TEST-LOC-1"))
    db_session.execute(delete(DeviceLocation).where(DeviceLocation.device_no == "TEST-AI-1"))
    db_session.execute(
        delete(AntiIntrusionDevice).where(AntiIntrusionDevice.device_no == "TEST-AI-1")
    )
    db_session.execute(delete(LocateDevice).where(LocateDevice.device_no == "TEST-LOC-1"))
    db_session.execute(delete(ElectronicFence).where(ElectronicFence.id == fence.id))
    db_session.execute(delete(Project).where(Project.id == proj.id))
    db_session.commit()


def _captured_emit(monkeypatch):
    sent: list = []

    def fake(channel, payload):
        sent.append((channel, payload))

    monkeypatch.setattr(bridge, "emit", fake)
    return sent


def test_fence_intrusion_and_ws_push(isolated, monkeypatch):
    """定位设备进入围栏 → 落库 + 围栏侵入告警 + WS 推送。"""
    sent = _captured_emit(monkeypatch)
    parsed = {
        "device_no": "TEST-LOC-1",
        "status": "在线",
        "longitude": 121.5000,  # 围栏中心
        "latitude": 31.2200,
        "accuracy": 4.0,
        "report_time": None,
    }
    result = handle_upstream(DEVICE_TYPE_LOCATE, parsed)
    assert result["alarms_created"] >= 1

    db = SessionLocal()
    try:
        loc = db.scalar(
            select(DeviceLocation)
            .where(DeviceLocation.device_no == "TEST-LOC-1")
            .order_by(DeviceLocation.id.desc())
        )
        assert loc is not None
        assert loc.longitude == 121.5000
        alarm = db.scalar(
            select(Alarm).where(
                Alarm.device_no == "TEST-LOC-1", Alarm.alarm_type == ALARM_TYPE_FENCE
            )
        )
        assert alarm is not None
        assert alarm.alarm_status == "告警开始"
    finally:
        db.close()

    types = [m[1]["type"] for m in sent]
    assert "location" in types
    assert "alarm" in types


def test_distance_threshold(isolated, monkeypatch):
    """定位设备贴近大机（<阈值）→ 间距过近告警。"""
    _captured_emit(monkeypatch)
    db = SessionLocal()
    try:
        save_location(
            db,
            device_type=DEVICE_TYPE_ANTI_INTRUSION,
            device_no="TEST-AI-1",
            device_name="大机A",
            project_id=isolated[0].id,
            longitude=121.4996,
            latitude=31.2200,
            status="在线",
        )
        db.commit()
    finally:
        db.close()

    parsed = {
        "device_no": "TEST-LOC-1",
        "status": "在线",
        "longitude": 121.4998,  # 距大机约 20m < 50m 阈值
        "latitude": 31.2200,
        "accuracy": 4.0,
        "report_time": None,
    }
    handle_upstream(DEVICE_TYPE_LOCATE, parsed)
    db = SessionLocal()
    try:
        alarm = db.scalar(
            select(Alarm).where(
                Alarm.device_no == "TEST-LOC-1", Alarm.alarm_type == ALARM_TYPE_DISTANCE
            )
        )
        assert alarm is not None, "应产生间距过近告警"
    finally:
        db.close()


def test_alarm_dedup(isolated, monkeypatch):
    """同一围栏侵入在去重窗口内只产生一条告警（防风暴）。"""
    _captured_emit(monkeypatch)
    base = {
        "device_no": "TEST-LOC-1",
        "status": "在线",
        "longitude": 121.5000,
        "latitude": 31.2200,
        "accuracy": 4.0,
        "report_time": None,
    }
    handle_upstream(DEVICE_TYPE_LOCATE, dict(base))
    handle_upstream(DEVICE_TYPE_LOCATE, dict(base))  # 重复上报

    db = SessionLocal()
    try:
        n = db.scalar(
            select(func.count()).select_from(
                select(Alarm)
                .where(Alarm.device_no == "TEST-LOC-1", Alarm.alarm_type == ALARM_TYPE_FENCE)
                .subquery()
            )
        )
        assert n == 1, "去重后应仅 1 条围栏侵入告警"
    finally:
        db.close()


def test_device_self_alarm(isolated, monkeypatch):
    """大机设备自报告警（接口 3）→ 产生 device_alarm 告警。"""
    _captured_emit(monkeypatch)
    db = SessionLocal()
    try:
        db.add(
            AntiIntrusionDevice(
                project_id=isolated[0].id, name="__t__ai", device_no="TEST-AI-1", status="在线"
            )
        )
        db.commit()
    finally:
        db.close()
    parsed = {
        "device_no": "TEST-AI-1",
        "status": "在线",
        "alarm_status": "告警开始",
        "alarm_info": "A 防区侵入",
        "image": "http://x/a.jpg",
        "report_time": None,
    }
    result = handle_upstream(DEVICE_TYPE_ANTI_INTRUSION, parsed)
    assert result["alarms_created"] >= 1
    db = SessionLocal()
    try:
        alarm = db.scalar(
            select(Alarm).where(
                Alarm.device_no == "TEST-AI-1", Alarm.alarm_type == ALARM_TYPE_DEVICE
            )
        )
        assert alarm is not None
        assert "http://x/a.jpg" in (alarm.media_urls or "")
    finally:
        db.close()


def _admin_token() -> str:
    db = SessionLocal()
    try:
        u = db.scalar(select(User).where(User.username == "admin", User.is_deleted.is_(False)))
        return create_access_token(u.id)
    finally:
        db.close()


def test_ws_no_token_rejected():
    """无令牌连接 → 服务端关闭(4401)。"""
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws/alarm") as ws:
            ws.receive_text()
    assert exc.value.code == 4401


def test_ws_auth_and_heartbeat():
    """带令牌连接 → 心跳 ping/pong 正常。"""
    client = TestClient(app)
    token = _admin_token()
    with client.websocket_connect(f"/ws/alarm?token={token}&project_id=1") as ws:
        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_online_status_recent_vs_stale(isolated):
    """在线状态：最近上报=在线，超过阈值=离线；summary 与 items 一致。"""
    proj = isolated[0]
    db = SessionLocal()
    try:
        # 最近上报（阈值内）→ 在线
        save_location(
            db,
            device_type=DEVICE_TYPE_LOCATE,
            device_no="TEST-LOC-1",
            device_name="定位1",
            project_id=proj.id,
            longitude=121.5000,
            latitude=31.2200,
            status="在线",
            report_time=datetime.now(timezone.utc),
        )
        # 2 小时前上报（远超默认 300s 阈值）→ 离线
        save_location(
            db,
            device_type="train_approach",
            device_no="TEST-AI-1",
            device_name="列车1",
            project_id=proj.id,
            longitude=121.5010,
            latitude=31.2210,
            status="在线",
            report_time=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        db.commit()
    finally:
        db.close()

    client = TestClient(app)
    token = _admin_token()
    resp = client.get(
        "/api/v1/realtime/online-status",
        headers={"Authorization": f"Bearer {token}"},
        params={"project_id": proj.id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == 0, body
    d = body["data"]
    assert d["total"] == 2, d
    assert d["online"] == 1, d
    assert d["offline"] == 1, d
    # 按类型汇总
    assert d["by_type"][DEVICE_TYPE_LOCATE]["online"] == 1
    assert d["by_type"]["train_approach"]["offline"] == 1
    # items 在线标记
    online_items = [i for i in d["items"] if i["online"]]
    offline_items = [i for i in d["items"] if not i["online"]]
    assert len(online_items) == 1 and online_items[0]["device_no"] == "TEST-LOC-1"
    assert len(offline_items) == 1 and offline_items[0]["device_no"] == "TEST-AI-1"
    assert online_items[0]["gcj02"] is not None


def test_send_command_dept_isolation(monkeypatch, isolated):
    """下发指令部门隔离：越权部门设备返回 404 且不真正下发；可见设备 200 且下发。"""
    published = []
    monkeypatch.setattr(mqtt_client, "publish", lambda *a, **k: published.append((a, k)))

    client = TestClient(app)
    admin_token = _admin_token()

    # 越权：DataScope 限定到不存在的部门 999，设备所属项目 dept_id=None 不在可见集合
    from app.core.data_scope import DataScope
    from app.core.deps import get_data_scope

    def _fake_scope():
        return DataScope(is_all=False, dept_ids=[999])

    app.dependency_overrides[get_data_scope] = _fake_scope
    try:
        resp = client.post(
            "/api/v1/realtime/command",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "device_type": DEVICE_TYPE_LOCATE,
                "device_no": "TEST-LOC-1",
                "action": "alarm",
                "params": {"on": False},
            },
        )
        assert resp.status_code == 404, resp.text
        assert not published, "越权时不应下发指令到设备"
    finally:
        app.dependency_overrides.pop(get_data_scope, None)

    # 可见：admin 默认 is_all -> 200 且真正下发
    resp = client.post(
        "/api/v1/realtime/command",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "device_type": DEVICE_TYPE_LOCATE,
            "device_no": "TEST-LOC-1",
            "action": "alarm",
            "params": {"on": False},
        },
    )
    assert resp.status_code == 200, resp.text
    assert published, "可见设备应下发指令"
