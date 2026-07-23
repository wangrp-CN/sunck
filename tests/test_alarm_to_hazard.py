"""告警→隐患一键转工单 集成测试（复用 conftest 的 client / admin_token）。"""

import uuid

import pytest

from app.core.database import SessionLocal
from app.model.alarm import Alarm
from app.model.hazard import Hazard

API = "/api/v1"
_created: list[int] = []  # 记录创建的 alarm id，teardown 硬删
_created_hazard: list[int] = []


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    db = SessionLocal()
    if _created_hazard:
        db.query(Hazard).filter(Hazard.id.in_(_created_hazard)).delete(synchronize_session=False)
    if _created:
        db.query(Alarm).filter(Alarm.id.in_(_created)).delete(synchronize_session=False)
    db.commit()
    db.close()
    _created.clear()
    _created_hazard.clear()


def _mk_alarm(client, token, **over):
    db = SessionLocal()
    a = Alarm(
        project_id=over.get("project_id"),
        alarm_type=over.get("alarm_type", "fence_intrusion"),
        device_type=over.get("device_type", "LOC-S"),
        device_name=over.get("device_name", "测试设备"),
        device_no=over.get("device_no", f"DEV-{uuid.uuid4().hex[:6]}"),
        alarm_info=over.get("alarm_info", "围栏侵入测试"),
        alarm_status="告警开始",
        alarm_level=over.get("alarm_level", "严重"),
        handle_status="待处理",
        fence_name=over.get("fence_name", "测试围栏"),
        alarm_time=over.get("alarm_time"),
    )
    db.add(a)
    db.flush()
    aid = a.id
    db.commit()
    db.close()
    _created.append(aid)
    return aid


def test_convert_alarm_to_hazard(client, admin_token):
    aid = _mk_alarm(client, admin_token, alarm_level="严重")
    # 转换（缺省推导）
    r = client.post(
        f"{API}/alarms/{aid}/convert-to-hazard",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    h = r.json()["data"]
    assert h["source_alarm_id"] == aid
    assert h["level"] == "重大"  # 严重 → 重大
    assert h["source"] == "系统"
    hid = h["id"]
    _created_hazard.append(hid)

    # 告警侧回填（无单告警 GET 接口，直接查库校验）
    db = SessionLocal()
    refreshed = db.get(Alarm, aid)
    assert refreshed is not None and refreshed.hazard_id == hid
    db.close()

    # 重复转换 → 业务码 400
    r3 = client.post(
        f"{API}/alarms/{aid}/convert-to-hazard",
        json={},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r3.status_code == 200
    assert r3.json()["code"] == 400


def test_convert_with_overrides(client, admin_token):
    aid = _mk_alarm(client, admin_token, alarm_level="提示")
    r = client.post(
        f"{API}/alarms/{aid}/convert-to-hazard",
        json={
            "title": "手动标题",
            "level": "低",
            "category": "环境",
            "due_at": "2030-01-01T00:00:00",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200, r.text
    h = r.json()["data"]
    assert h["title"] == "手动标题"
    assert h["level"] == "低"
    assert h["category"] == "环境"
    assert h["due_at"].startswith("2030-01-01")
    _created_hazard.append(h["id"])
