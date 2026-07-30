"""🅱 M4 告警策略（收敛/抑制/升级）测试。

覆盖：策略 CRUD、匹配优先级、静默时段判定（含跨天）、create_alarm 静默跳过通知、
收敛窗口覆盖、超时升级（级别提升 + escalated_at 幂等留痕）。

隔离约定：每用例用 uuid 唯一 alarm_type / device_no，避免命中他例策略与
Redis 去重键；finally 内同会话清理自建策略/告警。
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app.core.database import SessionLocal
from app.model.alarm import Alarm
from app.model.alarm_policy import AlarmPolicy
from app.model.notification import Notification
from app.model.project import Project
from app.service import alarm_policy_service as svc
from app.service import alarm_service


def _uid() -> str:
    return secrets.token_hex(3)


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _first_pid(db) -> int:
    pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
    assert pid is not None, "需存在真实项目"
    return pid


# ---------------------------------------------------------------------------
# CRUD（API 层）
# ---------------------------------------------------------------------------


def test_policy_crud(client: TestClient, admin_token: str):
    db = SessionLocal()
    created_id = None
    try:
        pid = _first_pid(db)
        # 创建
        r = client.post(
            "/api/v1/alarm-policies/",
            headers=_h(admin_token),
            json={
                "name": f"测试策略{_uid()}",
                "project_id": pid,
                "alarm_type": "fence_intrusion",
                "suppress_window_seconds": 120,
                "silence_start": "22:00",
                "silence_end": "06:00",
                "escalate_after_minutes": 30,
                "escalate_to_level": "严重",
                "escalate_channels": "in_app,sms",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == 0
        created_id = body["data"]["id"]
        assert body["data"]["project_name"]

        # 列表 + 过滤
        r = client.get(
            "/api/v1/alarm-policies/",
            headers=_h(admin_token),
            params={"project_id": pid, "alarm_type": "fence_intrusion"},
        )
        assert r.json()["code"] == 0
        assert any(it["id"] == created_id for it in r.json()["data"]["items"])

        # meta
        r = client.get("/api/v1/alarm-policies/meta", headers=_h(admin_token))
        meta = r.json()["data"]
        assert {"key": "predictive_alert", "label": "预测预警"} in meta["alarm_types"]
        assert "in_app" in meta["channels"]

        # 编辑：清除静默（空串=清除）+ 关闭升级（0=清除）
        r = client.put(
            f"/api/v1/alarm-policies/{created_id}",
            headers=_h(admin_token),
            json={"silence_start": "", "silence_end": "", "escalate_after_minutes": 0},
        )
        data = r.json()["data"]
        assert data["silence_start"] is None
        assert data["escalate_after_minutes"] is None

        # 非法级别
        r = client.put(
            f"/api/v1/alarm-policies/{created_id}",
            headers=_h(admin_token),
            json={"escalate_to_level": "灾难"},
        )
        assert r.json()["code"] == 400

        # 删除（逻辑删除）
        r = client.delete(f"/api/v1/alarm-policies/{created_id}", headers=_h(admin_token))
        assert r.json()["data"]["deleted"] is True
        r = client.get(f"/api/v1/alarm-policies/{created_id}", headers=_h(admin_token))
        assert r.json()["code"] == 404
    finally:
        if created_id:
            db.execute(delete(AlarmPolicy).where(AlarmPolicy.id == created_id))
            db.commit()
        db.close()


# ---------------------------------------------------------------------------
# 匹配优先级 / 静默判定（服务层）
# ---------------------------------------------------------------------------


def test_resolve_policy_precedence():
    db = SessionLocal()
    ids: list[int] = []
    try:
        pid = _first_pid(db)
        atype = f"t_{_uid()}"

        def _mk(name, project_id, alarm_type):
            p = AlarmPolicy(name=name, project_id=project_id, alarm_type=alarm_type)
            db.add(p)
            db.flush()
            ids.append(p.id)
            return p

        g_all = _mk("全局通配", None, None)
        g_type = _mk("全局+类型", None, atype)
        p_all = _mk("项目通配", pid, None)
        p_type = _mk("项目+类型", pid, atype)
        db.commit()

        assert svc.resolve_policy(db, pid, atype).id == p_type.id
        assert svc.resolve_policy(db, pid, "other_type_x").id == p_all.id
        assert svc.resolve_policy(db, None, atype).id == g_type.id
        assert svc.resolve_policy(db, None, "other_type_x").id == g_all.id
        # 禁用后不再命中
        p_type.enabled = False
        db.commit()
        assert svc.resolve_policy(db, pid, atype).id == p_all.id
    finally:
        db.execute(delete(AlarmPolicy).where(AlarmPolicy.id.in_(ids)))
        db.commit()
        db.close()


def test_in_silence_windows():
    from app.core.clock import LOCAL_TZ

    p = AlarmPolicy(name="s", silence_start="08:00", silence_end="18:00")
    # 构造北京时间 12:00 / 20:00 的 UTC 时刻
    noon = datetime.now(LOCAL_TZ).replace(hour=12, minute=0).astimezone(timezone.utc)
    evening = datetime.now(LOCAL_TZ).replace(hour=20, minute=0).astimezone(timezone.utc)
    assert svc.in_silence(p, noon) is True
    assert svc.in_silence(p, evening) is False
    # 跨天窗口 22:00-06:00
    p2 = AlarmPolicy(name="s2", silence_start="22:00", silence_end="06:00")
    late = datetime.now(LOCAL_TZ).replace(hour=23, minute=30).astimezone(timezone.utc)
    early = datetime.now(LOCAL_TZ).replace(hour=5, minute=0).astimezone(timezone.utc)
    assert svc.in_silence(p2, late) is True
    assert svc.in_silence(p2, early) is True
    assert svc.in_silence(p2, noon) is False
    # 无策略 / 无时段
    assert svc.in_silence(None) is False
    assert svc.in_silence(AlarmPolicy(name="x")) is False


def test_effective_suppress_window():
    assert svc.effective_suppress_window(None) is None
    assert svc.effective_suppress_window(AlarmPolicy(name="a")) is None
    assert svc.effective_suppress_window(AlarmPolicy(name="b", suppress_window_seconds=120)) == 120


# ---------------------------------------------------------------------------
# create_alarm 集成：静默抑制（落库但不通知）
# ---------------------------------------------------------------------------


def test_create_alarm_silenced_skips_notify():
    db = SessionLocal()
    policy_id = None
    alarm_id = None
    try:
        pid = _first_pid(db)
        atype = f"t_{_uid()}"
        p = AlarmPolicy(
            name="全天静默",
            project_id=pid,
            alarm_type=atype,
            silence_start="00:00",
            silence_end="23:59",
        )
        db.add(p)
        db.commit()
        policy_id = p.id

        before = db.scalar(select(func.count()).select_from(Notification)) or 0
        alarm = alarm_service.create_alarm(
            db,
            project_id=pid,
            alarm_type=atype,
            device_no=f"POL-{_uid()}",
            device_name="策略测试设备",
            alarm_info="静默测试",
            alarm_level="警告",
        )
        db.commit()
        assert alarm is not None  # 告警仍正常落库（不丢数据）
        alarm_id = alarm.id
        after = db.scalar(select(func.count()).select_from(Notification)) or 0
        assert after == before  # 但静默期间不产生任何通知
    finally:
        if alarm_id:
            db.execute(delete(Alarm).where(Alarm.id == alarm_id))
        if policy_id:
            db.execute(delete(AlarmPolicy).where(AlarmPolicy.id == policy_id))
        db.commit()
        db.close()


# ---------------------------------------------------------------------------
# 超时升级：级别提升 + escalated_at 幂等
# ---------------------------------------------------------------------------


@pytest.fixture
def escalation_env():
    """项目 + 唯一类型策略（30 分钟升级到严重）+ 一条 2 小时前的待处理告警。"""
    db = SessionLocal()
    pid = _first_pid(db)
    atype = f"t_{_uid()}"
    policy = AlarmPolicy(
        name="超时升级",
        project_id=pid,
        alarm_type=atype,
        escalate_after_minutes=30,
        escalate_to_level="严重",
        escalate_channels="in_app",
    )
    alarm = Alarm(
        project_id=pid,
        alarm_type=atype,
        device_no=f"ESC-{_uid()}",
        device_name="升级测试设备",
        alarm_info="超时升级测试",
        alarm_level="警告",
        handle_status="待处理",
        alarm_time=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    db.add_all([policy, alarm])
    db.commit()
    yield db, pid, atype, policy, alarm
    db.execute(delete(Alarm).where(Alarm.id == alarm.id))
    db.execute(delete(AlarmPolicy).where(AlarmPolicy.id == policy.id))
    db.commit()
    db.close()


def test_run_escalations_upgrades_and_idempotent(escalation_env):
    db, pid, atype, policy, alarm = escalation_env
    res = svc.run_escalations(db)
    db.commit()
    assert alarm.id in res["alarm_ids"]
    db.refresh(alarm)
    assert alarm.alarm_level == "严重"
    assert alarm.escalated_at is not None
    # 第二轮：escalated_at 留痕 → 不再重复升级
    res2 = svc.run_escalations(db)
    db.commit()
    assert alarm.id not in res2["alarm_ids"]


def test_run_escalations_skips_not_timeout(escalation_env):
    db, pid, atype, policy, alarm = escalation_env
    # 把告警时间改为 5 分钟前（< 30 分钟阈值）→ 不升级
    alarm.alarm_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()
    res = svc.run_escalations(db)
    db.commit()
    assert alarm.id not in res["alarm_ids"]
    db.refresh(alarm)
    assert alarm.escalated_at is None
    assert alarm.alarm_level == "警告"


def test_run_escalations_api(client: TestClient, admin_token: str, escalation_env):
    db, pid, atype, policy, alarm = escalation_env
    r = client.post("/api/v1/alarm-policies/run-escalations", headers=_h(admin_token))
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert alarm.id in body["data"]["alarm_ids"]
