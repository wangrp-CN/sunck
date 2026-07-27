"""告警风暴抑制 v2 测试。

验证：同一 (设备,类型,围栏,状态) 在窗口内只产生 1 条告警，重复被合并并累加到
anchor 的 ``suppressed_count``；当日抑制总量经 Redis 计数器累加；``to_alarm_out``
对外包含 ``suppressed_count``。使用唯一 device_no 避免与并存测试/真实数据碰撞。
"""

import secrets
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.model.alarm import Alarm
from app.model.project import Project
from app.service.alarm_service import (
    create_alarm,
    storm_suppressed_today,
    to_alarm_out,
)


@pytest.fixture
def proj():
    db = SessionLocal()
    try:
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
    finally:
        db.close()
    return pid


def test_suppression_counts_repeats(proj):
    dev = f"SUP{secrets.token_hex(3)}"
    fields = dict(
        alarm_type="fence_intrusion",
        device_no=dev,
        device_name="设备",
        alarm_level="严重",
        alarm_status="告警开始",
        alarm_info="测试",
        project_id=proj,
        alarm_time=datetime.now(timezone.utc),
    )
    db = SessionLocal()
    try:
        a1 = create_alarm(db, **fields)
        db.commit()
        assert a1 is not None, "首条告警应创建成功"

        before = storm_suppressed_today()
        a2 = create_alarm(db, **fields)  # 窗口内重复
        a3 = create_alarm(db, **fields)
        db.commit()
        assert a2 is None and a3 is None, "窗口内重复应被抑制(返回 None)"

        db.refresh(a1)
        assert a1.suppressed_count == 2, "两条重复应累加到 anchor"
        assert storm_suppressed_today() == before + 2

        out = to_alarm_out(a1)
        assert out["suppressed_count"] == 2
    finally:
        db.execute(delete(Alarm).where(Alarm.device_no == dev))
        db.commit()
        db.close()


def test_alarm_storm_endpoint(client, admin_token):
    """/v1/metrics/alarm-storm 暴露抑制窗口与当日抑制量。"""
    r = client.get(
        "/api/v1/metrics/alarm-storm",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["window_seconds"] > 0, "抑制窗口应大于 0"
    assert isinstance(data["suppressed_today"], int), "当日抑制量应为整数"
