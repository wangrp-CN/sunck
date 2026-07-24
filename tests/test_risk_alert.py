"""智能核心 v2：项目风险指数阈值预警 测试。

覆盖：
- ``evaluate_risk_alerts``：越阈判定 + ``is_new``（上升沿 / 持续越阈区别）；
- ``alert_newly_breached``：上升沿下发站内信、同一越阈快照重复调用不重复轰炸（降噪）；
- 无越阈时既不返回也不下发；
- 接口：``GET /metrics/risk-alerts`` 鉴权与越阈返回、``POST /risk-alerts/notify`` 仅超管可触发。

测试前后清空 risk_health_snapshot / risk_alert_state / notification 三表，保证隔离。
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.model.notification import Notification
from app.model.project import Project
from app.model.risk_alert import RiskAlertState
from app.model.snapshot import RiskHealthSnapshot
from app.service import risk_alert as alert_svc


@pytest.fixture
def wipe():
    db = SessionLocal()
    try:
        db.execute(delete(Notification))
        db.execute(delete(RiskAlertState))
        db.execute(delete(RiskHealthSnapshot))
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.execute(delete(Notification))
        db.execute(delete(RiskAlertState))
        db.execute(delete(RiskHealthSnapshot))
        db.commit()
    finally:
        db.close()


def _add_snapshot(db, project_id: int, risk_index: int, when: datetime, name="项目P"):
    db.add(
        RiskHealthSnapshot(
            scope_type="project",
            ref_id=str(project_id),
            name=name,
            risk_index=risk_index,
            risk_level="高" if risk_index >= 60 else "低",
            raw_score=risk_index,
            snapshot_at=when,
        )
    )


def test_rising_edge_alerts_once(wipe):
    """上升沿（prev 未越阈、latest 越阈）→ 下发 1 次；重复调用同一快照不再下发。"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        _add_snapshot(db, 101, 30, now - timedelta(days=1))  # 未越阈
        _add_snapshot(db, 101, 80, now)  # 越阈（上升沿）
        db.commit()

        breaches = alert_svc.evaluate_risk_alerts(db)
        assert len(breaches) == 1, breaches
        b = breaches[0]
        assert b["project_id"] == 101
        assert b["risk_index"] == 80
        assert b["is_new"] is True

        sent = alert_svc.alert_newly_breached(db)
        assert sent == 1, "上升沿应下发 1 条站内信预警"

        # 同一 latest 快照再次触发 → 降噪，不重复下发
        sent2 = alert_svc.alert_newly_breached(db)
        assert sent2 == 0, "同一越阈快照不应重复下发"

        # 确认确有 1 条站内信（category=risk_alert）
        n = db.scalar(select(Notification).where(Notification.category == "risk_alert"))
        assert n is not None
    finally:
        db.close()


def test_sustained_breach_no_duplicate(wipe):
    """持续越阈（prev/latest 均越阈）：非上升沿，但同快照未预警过仍发 1 次；二次跳过。"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        _add_snapshot(db, 202, 70, now - timedelta(days=1))  # 越阈
        _add_snapshot(db, 202, 80, now)  # 越阈
        db.commit()

        breaches = alert_svc.evaluate_risk_alerts(db)
        assert breaches[0]["is_new"] is False

        sent = alert_svc.alert_newly_breached(db)
        assert sent == 1, "持续越阈且未预警过此快照，应下发 1 次"
        sent2 = alert_svc.alert_newly_breached(db)
        assert sent2 == 0, "同一快照不应重复下发"
    finally:
        db.close()


def test_no_breach_no_alert(wipe):
    """远低于阈值：不越阈、不下发、无站内信。"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        _add_snapshot(db, 303, 20, now)
        db.commit()

        breaches = alert_svc.evaluate_risk_alerts(db)
        assert breaches == []

        sent = alert_svc.alert_newly_breached(db)
        assert sent == 0

        n = db.scalar(select(Notification))
        assert n is None, "无越阈不应产生任何通知"
    finally:
        db.close()


def test_risk_alerts_endpoint(client: TestClient, admin_token: str, wipe):
    """GET /metrics/risk-alerts：仅返回越阈项目（受数据范围约束，且须为真实项目）。"""
    h = {"Authorization": f"Bearer {admin_token}"}
    db = SessionLocal()
    try:
        # 取两个真实存在的项目，确保落在数据范围过滤内（接口按 Project 表校验权限）
        pids = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).all()
        assert len(pids) >= 2, "测试库应至少含 2 个项目"
        p_breach, p_safe = pids[0], pids[1]
        now = datetime.now(timezone.utc)
        _add_snapshot(db, p_breach, 85, now, name="越阈项目")
        _add_snapshot(db, p_safe, 10, now, name="安全项目")
        db.commit()
    finally:
        db.close()

    r = client.get("/api/v1/metrics/risk-alerts", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    resp_pids = [i["project_id"] for i in data["items"]]
    assert p_breach in resp_pids
    assert p_safe not in resp_pids
    assert data["items"][0]["risk_index"] == 85


def test_risk_alerts_notify_requires_admin(client: TestClient, wipe):
    """POST /metrics/risk-alerts/notify 未登录应被拒绝。"""
    r = client.post("/api/v1/metrics/risk-alerts/notify")
    assert r.status_code in (401, 403)
