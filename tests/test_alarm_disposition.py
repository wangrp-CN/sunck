"""处置效果闭环测试：处置记录写入、查询、统计。

覆盖：
- 处置时带 outcome → 写入 AlarmDisposition（含预案/知识库链接/解决时间）；
- 不带 outcome → 不写处置记录；
- GET /v1/alarms/{id}/dispositions 返回记录；
- GET /v1/dispositions/stats 聚合闭环率与平均闭环时长。
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete

from app.core.constants import DISPOSITION_RESOLVED, DISPOSITION_UNRESOLVED
from app.core.database import SessionLocal
from app.model.alarm import Alarm
from app.model.project import Project


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def project(db_session):
    p = Project(name="__t__disp_proj", dept_id=None, status="在建")
    db_session.add(p)
    db_session.flush()
    yield p
    db_session.execute(delete(Alarm).where(Alarm.project_id == p.id))
    db_session.execute(delete(Project).where(Project.id == p.id))
    db_session.commit()


@pytest.fixture
def alarm(db_session, project):
    a = Alarm(
        project_id=project.id,
        alarm_type="device_alarm",
        alarm_info="处置闭环测试告警",
        alarm_level="警告",
        handle_status="待处理",
        alarm_time=datetime.now(timezone.utc),
    )
    db_session.add(a)
    db_session.flush()
    db_session.commit()
    return a


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_handle_with_outcome_creates_disposition(client, admin_token, alarm):
    """处置带 outcome → 写入处置记录（含预案/知识库链接/解决时间）。"""
    payload = {
        "handle_status": "已处理",
        "content": "已现场处置",
        "playbook_id": 7,
        "knowledge_refs": [{"title": "围栏处置规范", "url": "https://kb.example/1"}],
        "outcome": DISPOSITION_RESOLVED,
        "action_taken": "断开电源并复核",
    }
    r = client.post(
        f"/api/v1/alarms/{alarm.id}/handle",
        json=payload,
        headers=_auth(admin_token),
    )
    assert r.json()["code"] == 0, r.text

    r = client.get(f"/api/v1/alarms/{alarm.id}/dispositions", headers=_auth(admin_token))
    assert r.json()["code"] == 0, r.text
    items = r.json()["data"]["items"]
    assert len(items) == 1
    d = items[0]
    assert d["outcome"] == DISPOSITION_RESOLVED
    assert d["playbook_id"] == 7
    assert d["knowledge_refs"][0]["title"] == "围栏处置规范"
    assert d["resolved_at"] is not None
    assert d["handler_id"] is not None


def test_handle_without_outcome_no_disposition(client, admin_token, alarm):
    """处置不带 outcome → 不写处置记录。"""
    r = client.post(
        f"/api/v1/alarms/{alarm.id}/handle",
        json={"handle_status": "已处理", "content": "仅更新状态"},
        headers=_auth(admin_token),
    )
    assert r.json()["code"] == 0, r.text
    r = client.get(f"/api/v1/alarms/{alarm.id}/dispositions", headers=_auth(admin_token))
    assert r.json()["data"]["items"] == []


def test_disposition_stats(client, admin_token, alarm):
    """stats 聚合闭环率与平均闭环时长。"""
    client.post(
        f"/api/v1/alarms/{alarm.id}/handle",
        json={"handle_status": "已处理", "content": "已处置", "outcome": DISPOSITION_RESOLVED},
        headers=_auth(admin_token),
    )
    r = client.get("/api/v1/dispositions/stats?days=30", headers=_auth(admin_token))
    assert r.json()["code"] == 0, r.text
    data = r.json()["data"]
    assert data["total"] >= 1
    assert data["resolved"] >= 1
    assert data["closure_rate"] == 1.0
    assert data["avg_duration_hours"] is not None


def test_disposition_unresolved_not_counted_as_closure(client, admin_token, alarm):
    """未解决 outcome 不计入闭环率。"""
    client.post(
        f"/api/v1/alarms/{alarm.id}/handle",
        json={"handle_status": "已处理", "content": "处理中", "outcome": DISPOSITION_UNRESOLVED},
        headers=_auth(admin_token),
    )
    r = client.get("/api/v1/dispositions/stats?days=30", headers=_auth(admin_token))
    data = r.json()["data"]
    assert data["closure_rate"] == 0.0
    assert data["resolved"] == 0
