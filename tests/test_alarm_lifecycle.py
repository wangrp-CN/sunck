"""告警生命周期测试：去重续期（防无界堆积）+ 违规解除自动结束。

对应优化项「规则引擎只开始不结束」：
- 持续违规期间每次上行都续期去重窗口，整段只产 1 条告警开始（根治每 300s 重建）；
- 违规解除时自动把仍打开的告警置「告警结束」+「已消警」，形成完整生命周期。
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, func, select

from app.core.constants import (
    ALARM_STATUS_CLEARED,
    ALARM_STATUS_END,
    ALARM_STATUS_START,
    ALARM_TYPE_DEVICE,
    ALARM_TYPE_FENCE,
    DEVICE_TYPE_LOCATE,
)
from app.core.database import SessionLocal
from app.core.redis import get_redis_client
from app.model.alarm import Alarm
from app.model.device import AntiIntrusionDevice, LocateDevice
from app.model.fence import ElectronicFence
from app.model.job import WorkPlan, WorkPlanFence
from app.model.project import Project
from app.model.realtime import DeviceLocation
from app.service.alarm_service import (
    ALARM_DEDUP_TTL,
    create_alarm,
    end_alarm_by_id,
    reconcile_active_alarms,
)
from app.service.pipeline import handle_upstream

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
def clear_redis_keys():
    """清理测试设备相关的去重键与活跃违规集合，避免跨用例污染。"""
    r = get_redis_client()
    for k in r.keys("alarm:dedup:TEST-LC-*"):
        r.delete(k)
    r.delete("rule2:active:TEST-LC-1")
    yield
    for k in r.keys("alarm:dedup:TEST-LC-*"):
        r.delete(k)
    r.delete("rule2:active:TEST-LC-1")


@pytest.fixture
def isolated(db_session):
    """隔离数据：项目 + 围栏 + 定位设备 + 激活作业计划（v2 判定前提）。"""
    proj = Project(name="__t__lc_proj", dept_id=None, status="在建")
    db_session.add(proj)
    db_session.flush()
    fence = ElectronicFence(
        project_id=proj.id,
        name="__t__lc_fence",
        fence_type="人员禁区",
        enabled=True,
        geometry_wkt=_FENCE_WKT,
    )
    db_session.add(fence)
    loc = LocateDevice(project_id=proj.id, name="__t__lc_loc", device_no="TEST-LC-1", status="在线")
    db_session.add(loc)
    db_session.flush()
    plan = WorkPlan(
        project_id=proj.id,
        name="__t__lc_plan",
        is_start=True,
        status="执行中",
        plan_start=None,
        plan_end=None,
        rule_json=json.dumps(
            {
                "monitor_target": "人员/设备",
                "trigger_conditions": [ALARM_TYPE_FENCE, ALARM_TYPE_DEVICE],
                "dwell_time": 0,
            },
            ensure_ascii=False,
        ),
    )
    db_session.add(plan)
    db_session.flush()
    db_session.add(WorkPlanFence(plan_id=plan.id, fence_id=fence.id))
    db_session.commit()
    yield proj, fence, loc
    db_session.execute(delete(WorkPlanFence).where(WorkPlanFence.plan_id == plan.id))
    db_session.execute(delete(WorkPlan).where(WorkPlan.id == plan.id))
    db_session.execute(delete(Alarm).where(Alarm.device_no == "TEST-LC-1"))
    db_session.execute(delete(DeviceLocation).where(DeviceLocation.device_no == "TEST-LC-1"))
    db_session.execute(
        delete(AntiIntrusionDevice).where(AntiIntrusionDevice.device_no == "TEST-AI-1")
    )
    db_session.execute(delete(LocateDevice).where(LocateDevice.device_no == "TEST-LC-1"))
    db_session.execute(delete(ElectronicFence).where(ElectronicFence.id == fence.id))
    db_session.execute(delete(Project).where(Project.id == proj.id))
    db_session.commit()


# ---------------------------------------------------------------------------
# 1) 去重续期：命中已存在键时刷新 TTL，而非仅跳过
# ---------------------------------------------------------------------------


def test_create_alarm_dedup_refresh(monkeypatch, db_session):
    """去重命中（nx 抢占失败）时应续期 TTL，而非仅跳过（防持续违规无界堆积）。"""
    fake = MagicMock()
    fake.set.return_value = None  # 模拟 set(nx=True) 返回 None → 键已存在 → 去重命中
    monkeypatch.setattr("app.service.alarm_service.get_redis_client", lambda: fake)
    fields = dict(
        alarm_type=ALARM_TYPE_FENCE,
        device_no="TEST-LC-1",
        alarm_status=ALARM_STATUS_START,
        project_id=None,
    )
    out = create_alarm(db_session, **fields)
    assert out is None, "去重命中应跳过创建"
    # 判定必须用原子 set(nx=True) 抢占，而非 exists→set 竞态
    assert fake.set.call_args_list[0].kwargs.get("nx") is True, "去重判定须用原子 set(nx=True)"
    fake.expire.assert_called_once()
    args = fake.expire.call_args.args
    assert args[1] == ALARM_DEDUP_TTL, "续期窗口应为 ALARM_DEDUP_TTL"


def test_create_alarm_first_creates(monkeypatch, db_session):
    """首次（nx 抢占成功）应创建告警并写入真实告警 id 到去重键。"""
    fake = MagicMock()
    fake.set.return_value = True  # 模拟 set(nx=True) 抢占成功 → 首次创建
    monkeypatch.setattr("app.service.alarm_service.get_redis_client", lambda: fake)
    fields = dict(
        alarm_type=ALARM_TYPE_FENCE,
        device_no="TEST-LC-1",
        alarm_status=ALARM_STATUS_START,
        project_id=None,
    )
    try:
        out = create_alarm(db_session, **fields)
        assert out is not None and isinstance(out, Alarm)
        db_session.commit()
        calls = fake.set.call_args_list
        # 首次调用须为原子抢占（nx=True）
        assert calls[0].kwargs.get("nx") is True, "首次创建须用原子 set(nx=True) 抢占"
        # 占位后须把真实告警 id 写回去重键（供规则引擎配对自动结束读取）
        assert any(c.args[1] == str(out.id) for c in calls), "去重键应写入真实告警 id"
    finally:
        db_session.execute(delete(Alarm).where(Alarm.device_no == "TEST-LC-1"))
        db_session.commit()


def test_create_alarm_dedup_atomic_no_db_row_on_hit(monkeypatch, db_session):
    """#8 回归：去重命中（nx 抢占失败）时不得落库任何告警行。

    原子判定（set(nx=True)）发生在 db.add 之前，故并发双写被根绝——
    即使 Redis 返回「键已存在」，本调用也不应新增告警记录。
    """
    fake = MagicMock()
    fake.set.return_value = None  # 模拟并发下 nx 抢占失败
    monkeypatch.setattr("app.service.alarm_service.get_redis_client", lambda: fake)
    fields = dict(
        alarm_type=ALARM_TYPE_FENCE,
        device_no="TEST-LC-1",
        alarm_status=ALARM_STATUS_START,
        project_id=None,
    )
    out = create_alarm(db_session, **fields)
    assert out is None
    db_session.commit()
    cnt = db_session.scalar(
        select(func.count()).select_from(Alarm).where(Alarm.device_no == "TEST-LC-1")
    )
    assert cnt == 0, "去重命中（nx 失败）不应落库任何告警行"


# ---------------------------------------------------------------------------
# 2) 自动结束：end_alarm_by_id
# ---------------------------------------------------------------------------


def test_end_alarm_by_id(db_session):
    a = Alarm(
        device_no="TEST-LC-1",
        alarm_type=ALARM_TYPE_FENCE,
        alarm_status=ALARM_STATUS_START,
        handle_status="待处理",
        alarm_time=datetime.now(timezone.utc),
    )
    db_session.add(a)
    db_session.commit()
    assert end_alarm_by_id(db_session, a.id) is True
    db_session.refresh(a)
    assert a.alarm_status == ALARM_STATUS_END
    assert a.handle_status == ALARM_STATUS_CLEARED
    # 幂等：已结束不应再次更新
    assert end_alarm_by_id(db_session, a.id) is False
    db_session.execute(delete(Alarm).where(Alarm.id == a.id))
    db_session.commit()


# ---------------------------------------------------------------------------
# 3) reconcile：违规解除自动结束上一轮仍打开的告警
# ---------------------------------------------------------------------------


def test_reconcile_ends_cleared_violation(db_session):
    a = Alarm(
        device_no="TEST-LC-1",
        alarm_type=ALARM_TYPE_FENCE,
        alarm_status=ALARM_STATUS_START,
        handle_status="待处理",
        alarm_time=datetime.now(timezone.utc),
    )
    db_session.add(a)
    db_session.commit()
    r = get_redis_client()
    vk = "alarm:dedup:TEST-LC-1:fence_intrusion:__t__lc_fence:告警开始:"

    # 本轮仍活跃 -> 记录进活跃集合
    assert reconcile_active_alarms(db_session, "TEST-LC-1", {vk: a.id}) == []
    assert r.hgetall("rule2:active:TEST-LC-1") == {vk: str(a.id)}

    # 下一轮该违规键缺失 -> 自动结束
    ended = reconcile_active_alarms(db_session, "TEST-LC-1", {})
    assert ended == [a.id]
    db_session.refresh(a)
    assert a.alarm_status == ALARM_STATUS_END
    assert a.handle_status == ALARM_STATUS_CLEARED
    # 无活跃 -> 哈希应被清理
    assert r.hgetall("rule2:active:TEST-LC-1") == {}

    db_session.execute(delete(Alarm).where(Alarm.id == a.id))
    db_session.commit()


# ---------------------------------------------------------------------------
# 4) 集成：pipeline 完整生命周期（开始 → 解除自动结束）
# ---------------------------------------------------------------------------


def test_pipeline_lifecycle_auto_end(isolated, monkeypatch):
    """设备进入围栏→1条告警开始；离开围栏(无候选)→自动结束。"""
    inside = {
        "device_no": "TEST-LC-1",
        "status": "在线",
        "longitude": 121.5000,
        "latitude": 31.2200,
        "accuracy": 4.0,
        "report_time": None,
    }
    handle_upstream(DEVICE_TYPE_LOCATE, inside)
    outside = {
        "device_no": "TEST-LC-1",
        "status": "在线",
        "longitude": 121.5100,
        "latitude": 31.2300,
        "accuracy": 4.0,
        "report_time": None,
    }
    handle_upstream(DEVICE_TYPE_LOCATE, outside)  # 移出围栏：本应触发自动结束

    db = SessionLocal()
    try:
        alarms = db.scalars(
            select(Alarm)
            .where(Alarm.device_no == "TEST-LC-1", Alarm.alarm_type == ALARM_TYPE_FENCE)
            .order_by(Alarm.id)
        ).all()
        # 整个违规周期只产生 1 条围栏告警（去重续期生效）
        assert len(alarms) == 1, f"围栏告警应仅 1 条，实际 {len(alarms)}"
        assert alarms[0].alarm_status == ALARM_STATUS_END, "移出围栏后应自动结束"
        assert alarms[0].handle_status == ALARM_STATUS_CLEARED
    finally:
        db.close()
