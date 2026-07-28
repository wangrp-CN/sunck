"""设备指令下发闭环测试（状态机 / 回执 / 重试 / 端点）。"""

import secrets
from datetime import timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.exceptions import BusinessError
from app.model.command import (
    COMMAND_STATUS_ACKED,
    COMMAND_STATUS_FAILED,
    COMMAND_STATUS_SENT,
    DeviceCommand,
)
from app.model.project import Project
from app.service import command_service


@pytest.fixture
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def _project_id(db) -> int:
    name = "cmd-test-" + secrets.token_hex(4)
    p = Project(name=name, dept_id=1, status="在建")
    db.add(p)
    db.flush()
    return p.id


def test_build_and_send_persists_and_injects_cmd_id():
    db = SessionLocal()
    try:
        pid = _project_id(db)
        with patch("app.service.command_service.publish") as pub:
            cmd = command_service.build_and_send(
                db,
                device_no="CMD-D1",
                device_type="locate",
                action="alarm",
                params={"on": False},
                project_id=pid,
                device_id=1,
            )
        # 已落库并发布
        assert cmd.id is not None
        assert cmd.status == COMMAND_STATUS_SENT
        assert cmd.sent_at is not None
        assert cmd.retry_count == 0
        # 报文注入 cmd_id，供设备回执关联
        assert pub.called
        payload = pub.call_args.args[1]
        assert f'"cmd_id": {cmd.id}' in payload or f'"cmd_id":{cmd.id}' in payload

        # 模拟设备回执
        acked = command_service.ack_command(db, cmd.id, ok=True)
        assert acked.status == COMMAND_STATUS_ACKED
        assert acked.acked_at is not None
    finally:
        db.rollback()
        db.close()


def test_build_and_send_publish_failure_marks_failed():
    db = SessionLocal()
    try:
        pid = _project_id(db)
        with patch("app.service.command_service.publish", side_effect=RuntimeError("broker down")):
            cmd = command_service.build_and_send(
                db,
                device_no="CMD-D2",
                device_type="locate",
                action="restart",
                project_id=pid,
            )
        # 发布失败不抛异常，记录为 failed 并留痕
        assert cmd.status == COMMAND_STATUS_FAILED
        assert cmd.last_error and "broker down" in cmd.last_error
    finally:
        db.rollback()
        db.close()


def test_invalid_action_raises_and_persists_nothing():
    db = SessionLocal()
    try:
        pid = _project_id(db)
        with patch("app.service.command_service.publish") as pub:
            try:
                command_service.build_and_send(
                    db,
                    device_no="CMD-D3",
                    device_type="locate",
                    action="not_supported",
                    project_id=pid,
                )
                assert False, "应抛 BusinessError"
            except BusinessError as e:
                assert e.code == 400
        # 非法动作不应落库残留记录
        assert pub.called is False
        leftover = db.scalar(select(DeviceCommand).where(DeviceCommand.device_no == "CMD-D3"))
        assert leftover is None
    finally:
        db.rollback()
        db.close()


def test_retry_increments_and_republishes():
    db = SessionLocal()
    try:
        pid = _project_id(db)
        with patch("app.service.command_service.publish"):
            cmd = command_service.build_and_send(
                db, device_no="CMD-D4", device_type="locate", action="sound", project_id=pid
            )
        with patch("app.service.command_service.publish") as pub2:
            retried = command_service.retry_command(db, cmd.id)
        assert retried.retry_count == 1
        assert retried.status == COMMAND_STATUS_SENT
        assert pub2.called

        # 已回执不可重试
        command_service.ack_command(db, cmd.id, ok=True)
        try:
            command_service.retry_command(db, cmd.id)
            assert False, "已回执应不可重试"
        except BusinessError as e:
            assert e.code == 400
    finally:
        db.rollback()
        db.close()


def test_retry_stale_automatic_and_exhaust():
    db = SessionLocal()
    try:
        pid = _project_id(db)
        suf = secrets.token_hex(3)
        # 一条超时未回执且未达上限
        with patch("app.service.command_service.publish"):
            c1 = command_service.build_and_send(
                db, device_no=f"CMD-S1-{suf}", device_type="locate", action="light", project_id=pid
            )
        # 一条已达最大重试次数
        with patch("app.service.command_service.publish"):
            c2 = command_service.build_and_send(
                db, device_no=f"CMD-S2-{suf}", device_type="locate", action="light", project_id=pid
            )
        c2.retry_count = 3  # 已达 command_max_retries 默认 3

        # 把 sent_at 拨到超时之前，使其进入 stale 窗口
        from app.core.clock import now_local

        past = now_local() - timedelta(seconds=3600)
        c1.sent_at = past
        c2.sent_at = past
        db.commit()
        c1_id, c2_id = c1.id, c2.id

        with patch("app.service.command_service.publish"):
            stats = command_service.retry_stale_commands(db)
        # 允许其它历史遗留的 stale 行（共享 DB），仅校验本条语义
        assert stats["retried"] >= 1
        assert stats["exhausted"] >= 1
        db.expire_all()
        got1 = db.get(DeviceCommand, c1_id)
        got2 = db.get(DeviceCommand, c2_id)
        assert got1.retry_count == 1
        assert got1.status == COMMAND_STATUS_SENT
        assert got2.status == COMMAND_STATUS_FAILED
    finally:
        db.rollback()
        db.close()


def test_endpoint_command_and_list(client, auth_headers):
    """端点契约：下发落库 + 列表可见 + 手动重试。"""
    from app.model.device import LocateDevice

    db = SessionLocal()
    try:
        pid = _project_id(db)
        dev = LocateDevice(
            name="CMD-DEV",
            device_no="CMD-EP-" + secrets.token_hex(4),
            device_type="locate",
            project_id=pid,
        )
        db.add(dev)
        db.commit()
        dev_no = dev.device_no
    finally:
        db.close()

    r = client.post(
        "/api/v1/realtime/command",
        headers=auth_headers,
        json={
            "device_type": "locate",
            "device_no": dev_no,
            "action": "alarm",
            "params": {"on": False},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0, body
    assert body["data"]["id"] > 0
    assert body["data"]["status"] in (COMMAND_STATUS_SENT, COMMAND_STATUS_FAILED)

    cid = body["data"]["id"]
    lst = client.get("/api/v1/commands", headers=auth_headers, params={"device_no": dev_no})
    assert lst.status_code == 200, lst.text
    items = lst.json()["data"]["items"]
    assert any(i["id"] == cid for i in items)

    rp = client.post(f"/api/v1/commands/{cid}/retry", headers=auth_headers)
    assert rp.status_code == 200, rp.text
    assert rp.json()["data"]["id"] == cid
