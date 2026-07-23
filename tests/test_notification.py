"""通知中心 集成测试：列表/未读计数/标记已读/全部已读 + 告警触发站内信。"""

import uuid

import pytest

from app.core.database import SessionLocal
from app.model.notification import Notification
from app.model.system import User

API = "/api/v1/notifications"


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    # 清空通知表（测试专用，避免跨用例/跨用户残留）
    db = SessionLocal()
    db.query(Notification).delete(synchronize_session=False)
    db.commit()
    db.close()


def _admin_id() -> int:
    db = SessionLocal()
    u = db.query(User).filter(User.is_superuser.is_(True)).first()
    db.close()
    return u.id


def test_notification_list_and_read(client, admin_token):
    uid = _admin_id()
    db = SessionLocal()
    db.add_all(
        [
            Notification(user_id=uid, channel="in_app", category="alarm", title="t1", content="c1"),
            Notification(user_id=uid, channel="in_app", category="alarm", title="t2"),
        ]
    )
    db.commit()
    db.close()

    # 未读计数
    r = client.get(f"{API}/unread-count", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert r.json()["data"]["count"] >= 2

    # 仅看未读列表
    r = client.get(f"{API}/?unread_only=true", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert len(items) >= 2
    nid = items[0]["id"]

    # 标记单条已读
    r = client.post(f"{API}/{nid}/read", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert r.json()["data"]["is_read"] is True

    # 全部已读（至少覆盖剩余未读）
    r = client.post(f"{API}/read-all", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200
    assert r.json()["data"]["updated"] >= 1


def test_alarm_creation_triggers_notification(client, admin_token):
    uid = _admin_id()
    from app.service.alarm_service import create_alarm

    db = SessionLocal()
    before = db.query(Notification).filter(Notification.user_id == uid).count()
    alarm = create_alarm(
        db,
        alarm_type="fence_intrusion",
        device_no=f"NT-{uuid.uuid4().hex[:8]}",
        device_name="通知测试设备",
        alarm_info="围栏侵入-通知测试",
        project_id=None,
    )
    db.commit()
    after = db.query(Notification).filter(Notification.user_id == uid).count()
    db.close()

    assert alarm is not None, "新告警应去重创建成功"
    assert after > before, "告警产生应推送站内信给活跃用户"
    # 末条通知标题应含『新告警』
    db = SessionLocal()
    last = (
        db.query(Notification)
        .filter(Notification.user_id == uid)
        .order_by(Notification.id.desc())
        .first()
    )
    db.close()
    assert last is not None and "新告警" in last.title
