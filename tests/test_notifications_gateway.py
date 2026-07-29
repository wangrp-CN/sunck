"""短信/语音网关（P2① · 模拟真实数据）回归测试。

验证：模拟网关生成真实形态回执、通知器落库触达记录、无手机号标记 no_phone、
真实模式缺凭据返回 not_configured、以及 /test-send 与 /deliveries 接口链路。
"""

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.gateways import send_via_gateway
from app.core.notify import SmsNotifier, notify
from app.model.notification import Notification
from app.model.notification_delivery import NotificationDelivery
from app.model.system import User


@pytest.fixture(autouse=True)
def _clean_deliveries():
    db = SessionLocal()
    try:
        db.query(NotificationDelivery).delete()
        db.query(Notification).delete()
        db.commit()
    finally:
        db.close()


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _make_user(phone=None) -> tuple[User, Session]:
    db = SessionLocal()
    u = User(
        username=f"gwuser_{uuid.uuid4().hex[:8]}",
        nickname="gw",
        password_hash="x",
        dept_id=None,
        status=True,
        phone=phone,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u, db


def test_simulated_sms_gateway_shape():
    r = send_via_gateway("sms", "13800000000", "告警：1号机超限")
    assert r.status == "sent"
    assert r.code == "OK"
    assert r.biz_id and r.request_id
    assert r.raw.get("BizId") == r.biz_id


def test_simulated_voice_gateway_shape():
    r = send_via_gateway("voice", "13800000000", "语音告警")
    assert r.status == "sent"
    assert r.raw.get("CallId") == r.biz_id


def test_notify_sms_persists_delivery():
    u, db = _make_user(phone="13900000000")
    SmsNotifier().send(db, u.id, "标题", "内容")
    db.commit()
    rec = db.query(NotificationDelivery).filter_by(user_id=u.id, channel="sms").one()
    assert rec.status == "sent"
    assert rec.biz_id is not None
    assert rec.phone == "13900000000"


def test_notify_no_phone_marks_no_phone():
    u, db = _make_user(phone=None)
    SmsNotifier().send(db, u.id, "标题", "内容")
    db.commit()
    rec = db.query(NotificationDelivery).filter_by(user_id=u.id, channel="sms").one()
    assert rec.status == "no_phone"


def test_notify_fanout_sms_voice():
    u, db = _make_user(phone="13700000000")
    notify(db, [u.id], "标题", "内容", channels=("sms", "voice"))
    db.commit()
    chans = {d.channel for d in db.query(NotificationDelivery).filter_by(user_id=u.id).all()}
    assert chans == {"sms", "voice"}


def test_real_mode_without_creds_not_configured(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "sms_mode", "real")
    monkeypatch.setattr(settings, "sms_api_key", None)
    r = send_via_gateway("sms", "13800000000", "x")
    assert r.status == "not_configured"


def test_test_send_api(client, auth_headers):
    r = client.post(
        "/api/v1/notifications/test-send",
        json={"channel": "sms", "phone": "13600000000", "content": "验证触达"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["result"]["status"] == "sent"
    assert body["data"]["delivery"]["id"]


def test_deliveries_list_api(client, auth_headers):
    client.post(
        "/api/v1/notifications/test-send",
        json={"channel": "voice", "phone": "13500000000", "content": "语音验证"},
        headers=auth_headers,
    )
    r = client.get("/api/v1/notifications/deliveries", headers=auth_headers)
    assert r.status_code == 200
    items = r.json()["data"]
    assert any(d["channel"] == "voice" and d["status"] == "sent" for d in items)
