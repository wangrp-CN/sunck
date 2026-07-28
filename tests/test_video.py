"""视频 AI 深化⑧：事件升级为平台告警（闭环联动）测试。

覆盖：回推+列表、手动升级建告警并回填 alarm_id、升级幂等、级别映射（高危/高置信提升）、
ingest 时按配置自动升级。
"""

import secrets

import pytest
from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.model.alarm import Alarm
from app.model.project import Project
from app.model.video import VideoChannel, VideoEvent
from app.service import video_service as svc


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _rand_no(prefix="CAM"):
    return f"{prefix}-{secrets.token_hex(3)}"


def _make_channel(db, project_id=None, ai_enabled=True, channel_no=None):
    c = VideoChannel(
        project_id=project_id,
        name="测试通道",
        channel_no=channel_no or _rand_no(),
        status="在线",
        ai_enabled=ai_enabled,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _ingest(client, auth_headers, channel_no, event_type, confidence=None, snapshot=None):
    return client.post(
        "/api/v1/videos/events/ingest",
        headers=auth_headers,
        json={
            "channel_no": channel_no,
            "event_type": event_type,
            "confidence": confidence,
            "snapshot_url": snapshot,
            "detail": "测试细节",
        },
    )


def _last_event(db, channel_id):
    return db.scalar(
        select(VideoEvent).where(VideoEvent.channel_id == channel_id).order_by(VideoEvent.id.desc())
    )


def test_ingest_and_list(client, auth_headers):
    db = SessionLocal()
    try:
        proj = Project(name=f"视频Proj-{secrets.token_hex(2)}")
        db.add(proj)
        db.commit()
        db.refresh(proj)
        ch = _make_channel(db, proj.id)
        r = _ingest(client, auth_headers, ch.channel_no, "intrusion", 0.9, "http://x/snap.jpg")
        assert r.status_code == 200, r.text
        lst = client.get("/api/v1/videos/events", headers=auth_headers)
        assert lst.status_code == 200
        items = lst.json()["data"]["items"]
        assert any(i["event_type"] == "intrusion" for i in items)
    finally:
        db.close()


def test_escalate_creates_alarm_and_links(client, auth_headers):
    db = SessionLocal()
    try:
        proj = Project(name=f"视频Proj-{secrets.token_hex(2)}")
        db.add(proj)
        db.commit()
        db.refresh(proj)
        ch = _make_channel(db, proj.id)
        _ingest(client, auth_headers, ch.channel_no, "intrusion", 0.92, "http://x/s1.jpg")
        ev = _last_event(db, ch.id)
        r = client.post(f"/api/v1/videos/events/{ev.id}/escalate", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()["data"]
        assert body["alarm_id"] is not None
        assert body["alarm_level"] == "严重"

        db.refresh(ev)
        assert ev.alarm_id == body["alarm_id"]

        alarm = db.get(Alarm, ev.alarm_id)
        assert alarm is not None
        assert alarm.project_id == proj.id
        assert alarm.alarm_level == "严重"
        assert alarm.media_urls == "http://x/s1.jpg"
        assert "视频AI" in (alarm.alarm_info or "")
        assert alarm.device_no == ch.channel_no
    finally:
        db.close()


def test_escalate_idempotent(client, auth_headers):
    db = SessionLocal()
    try:
        ch = _make_channel(db, None)
        _ingest(client, auth_headers, ch.channel_no, "no_helmet", 0.8)
        ev = _last_event(db, ch.id)
        r1 = client.post(f"/api/v1/videos/events/{ev.id}/escalate", headers=auth_headers)
        r2 = client.post(f"/api/v1/videos/events/{ev.id}/escalate", headers=auth_headers)
        assert r1.json()["data"]["alarm_id"] == r2.json()["data"]["alarm_id"]
        # 仅一条告警（去重 + 幂等，无重复建单）
        label = svc.VIDEO_EVENT_TYPE_LABELS["no_helmet"]
        cnt = db.scalar(
            select(func.count())
            .select_from(Alarm)
            .where(Alarm.device_no == ch.channel_no, Alarm.alarm_type == f"视频AI-{label}")
        )
        assert cnt == 1
    finally:
        db.close()


def test_escalate_level_mapping_uplift(client, auth_headers):
    # other(提示) + 高置信(>=0.9) => 提升到「严重」
    db = SessionLocal()
    try:
        ch = _make_channel(db, None)
        _ingest(client, auth_headers, ch.channel_no, "other", 0.95)
        ev = _last_event(db, ch.id)
        client.post(f"/api/v1/videos/events/{ev.id}/escalate", headers=auth_headers)
        db.refresh(ev)
        alarm = db.get(Alarm, ev.alarm_id)
        assert alarm.alarm_level == "严重"
    finally:
        db.close()


def test_auto_escalate_on_ingest(client, auth_headers, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "video_auto_escalate_enabled", True)
    monkeypatch.setattr(settings, "video_auto_escalate_threshold", 0.8)
    db = SessionLocal()
    try:
        ch = _make_channel(db, None)
        r = _ingest(client, auth_headers, ch.channel_no, "intrusion", 0.9)
        assert r.status_code == 200, r.text
        ev = _last_event(db, ch.id)
        assert ev.alarm_id is not None
    finally:
        db.close()


def test_escalate_missing_event_404(client, auth_headers):
    r = client.post("/api/v1/videos/events/999999/escalate", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["code"] == 404
