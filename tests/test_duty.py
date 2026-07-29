"""🅱 值班排班 + 告警自动派单测试。

覆盖：排班 CRUD、当前值班查询、逻辑删除，以及未指定处理人时按当班人自动指派派单。
使用 admin（超管，数据范围=全部），测试 fixture 清理自建数据，保证用例间隔离。
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.model.duty_roster import DutyRoster
from app.model.notification import Notification
from app.model.project import Project
from app.model.system import User


def _uid() -> str:
    return secrets.token_hex(3)


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def env(client: TestClient, admin_token: str):
    db = SessionLocal()
    try:
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
        assert pid is not None, "需存在真实项目"
        now = datetime.now(timezone.utc)
        u = _uid()
        r = client.post(
            "/api/v1/auth/register",
            headers=_h(admin_token),
            json={
                "username": f"DUTY{u}",
                "password": "Test@123456",
                "role_codes": ["operator"],
                "status": True,
            },
        )
        assert r.status_code == 200, r.text
        onduty_id = r.json()["data"]["id"]
        roster = DutyRoster(
            project_id=pid,
            user_id=onduty_id,
            shift="白班",
            duty_role="值班员",
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            note="测试值班",
        )
        db.add(roster)
        db.commit()
        rid = roster.id
        yield {"pid": pid, "onduty_id": onduty_id, "rid": rid, "admin_token": admin_token}
    finally:
        # 清理自建数据，保证用例隔离
        db2 = SessionLocal()
        try:
            db2.execute(delete(DutyRoster).where(DutyRoster.project_id == pid))
            uobj = db2.get(User, onduty_id)
            if uobj:
                db2.delete(uobj)
            db2.commit()
        finally:
            db2.close()
        db.close()


def test_create_and_list_roster(env, client: TestClient):
    c, tok = client, env["admin_token"]
    body = {
        "project_id": env["pid"],
        "user_id": env["onduty_id"],
        "shift": "夜班",
        "start_time": "2026-07-29T22:00:00+00:00",
        "end_time": "2026-07-30T06:00:00+00:00",
    }
    r = c.post("/api/v1/duty/", headers=_h(tok), json=body)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["shift"] == "夜班" and data["user_name"]
    new_id = data["id"]

    r = c.get(f"/api/v1/duty/?project_id={env['pid']}", headers=_h(tok))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert any(i["id"] == new_id for i in items)


def test_on_duty_resolves(env, client: TestClient):
    c, tok = client, env["admin_token"]
    r = c.get(f"/api/v1/duty/on-duty?project_id={env['pid']}", headers=_h(tok))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["user_id"] == env["onduty_id"]
    assert data["user_name"]


def test_update_and_delete_roster(env, client: TestClient):
    c, tok = client, env["admin_token"]
    r = c.put(
        f"/api/v1/duty/{env['rid']}",
        headers=_h(tok),
        json={"shift": "中班", "note": "改班"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["shift"] == "中班"

    r = c.delete(f"/api/v1/duty/{env['rid']}", headers=_h(tok))
    assert r.json()["code"] == 0
    r = c.get(f"/api/v1/duty/{env['rid']}", headers=_h(tok))
    assert r.json()["code"] == 404


def test_auto_dispatch_assigns_on_duty(env, client: TestClient):
    """未指定处理人时，派单应自动指派给当前值班人并通知。"""
    c, tok = client, env["admin_token"]
    body = {
        "source_type": "manual",
        "project_id": env["pid"],
        "title": "自动派单测试",
        "level": "警告",
    }
    r = c.post("/api/v1/dispatch/", headers=_h(tok), json=body)
    assert r.status_code == 200, r.text
    order = r.json()["data"]
    assert order["assignee_id"] == env["onduty_id"], "应自动指派当班人"

    db = SessionLocal()
    try:
        n = db.scalars(
            select(Notification).where(
                Notification.user_id == env["onduty_id"], Notification.is_read.is_(False)
            )
        ).first()
        assert n is not None, "当班人应收到站内信"
        assert "派单" in (n.title or "")
    finally:
        db.close()


def test_auto_dispatch_no_roster_no_assignee(client: TestClient, admin_token: str):
    """无排班时，未指定处理人的派单 assignee 为空，不报错。"""
    db = SessionLocal()
    try:
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
        assert pid is not None
        # 清空该项目排班，确保无当班人
        db.execute(delete(DutyRoster).where(DutyRoster.project_id == pid))
        db.commit()
    finally:
        db.close()

    body = {
        "source_type": "manual",
        "project_id": pid,
        "title": "无排班自动派单",
        "level": "提示",
    }
    r = client.post("/api/v1/dispatch/", headers=_h(admin_token), json=body)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["assignee_id"] is None
