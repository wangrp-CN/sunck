"""趋势异常进告警流（#81 扩展）测试。

覆盖：统计基线检测口径（spike/drop/常量基线/样本不足）、级别映射、
run_anomaly_detection 落库 + 幂等（二次运行不重复派警）、
GET /metrics/anomalies 预览端点（不落库）。
使用 admin（超管，数据范围=全部），测试前后清理自建数据。
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.constants import ALARM_TYPE_ANOMALY
from app.core.database import SessionLocal
from app.model.alarm import Alarm
from app.model.project import Project
from app.service import anomaly_service as svc


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 检测核心（与前端 anomaly.ts 同口径）
# ---------------------------------------------------------------------------
def test_detect_series_spike_and_drop():
    opts = {"window": 7, "k": 2.0, "min_trailing": 3, "min_points": 5}
    # 浮动基线 + 末尾突增
    vals = [10.0, 12.0, 11.0, 13.0, 12.0, 11.0, 12.0, 40.0]
    det = svc.detect_series(vals, **opts)
    assert det[-1]["is_anomaly"] is True
    assert det[-1]["direction"] == "spike"
    # 末尾骤降
    vals2 = [10.0, 12.0, 11.0, 13.0, 12.0, 11.0, 12.0, 0.0]
    det2 = svc.detect_series(vals2, **opts)
    assert det2[-1]["is_anomaly"] is True
    assert det2[-1]["direction"] == "drop"


def test_detect_series_constant_baseline_and_short():
    opts = {"window": 7, "k": 2.0, "min_trailing": 3, "min_points": 5}
    # 常量基线（std≈0）：任何偏离即判异常，z=±inf
    vals = [5.0, 5.0, 5.0, 5.0, 5.0, 9.0]
    det = svc.detect_series(vals, **opts)
    assert det[-1]["is_anomaly"] is True
    assert det[-1]["z"] == float("inf")
    # 序列过短：整条不判异常
    det2 = svc.detect_series([1.0, 100.0], **opts)
    assert all(not a["is_anomaly"] for a in det2)


def test_level_mapping():
    assert svc._level_for(float("inf")) == "严重"
    assert svc._level_for(3.5) == "严重"
    assert svc._level_for(-2.4) == "警告"
    assert svc._level_for(1.2) == "提示"


# ---------------------------------------------------------------------------
# 落库 + 幂等 + 预览端点
# ---------------------------------------------------------------------------
@pytest.fixture
def env(client: TestClient, admin_token: str):
    """独立项目 + 昨日告警尖刺（其余日子零填充 → 常量基线偏离即异常）。"""
    db = SessionLocal()
    try:
        proj = Project(name=f"ANOM-{secrets.token_hex(3)}", status="在建")
        db.add(proj)
        db.flush()
        pid = proj.id
        spike_day = datetime.now(timezone.utc) - timedelta(days=1)
        for i in range(10):
            db.add(
                Alarm(
                    project_id=pid,
                    alarm_type="fence_intrusion",
                    device_no=f"ANOMDEV{i}",
                    alarm_info="尖刺样本",
                    alarm_level="警告",
                    alarm_time=spike_day,
                )
            )
        db.commit()
    finally:
        db.close()
    yield {"pid": pid, "client": client, "admin_token": admin_token}
    db = SessionLocal()
    try:
        db.execute(delete(Alarm).where(Alarm.project_id == pid))
        db.execute(delete(Project).where(Project.id == pid))
        db.commit()
    finally:
        db.close()


def test_run_anomaly_detection_idempotent(env):
    pid = env["pid"]
    db = SessionLocal()
    try:
        # 第一次运行：告警量序列在尖刺日应落 1 条 trend_anomaly 告警
        r1 = svc.run_anomaly_detection(db, project_id=pid)
        db.commit()
        assert r1["created"] >= 1
        rows = db.scalars(
            select(Alarm).where(Alarm.project_id == pid, Alarm.alarm_type == ALARM_TYPE_ANOMALY)
        ).all()
        assert len(rows) >= 1
        a = rows[0]
        assert a.device_no.startswith("anomaly:")
        assert "趋势异常" in (a.alarm_info or "") or "异常" in (a.alarm_info or "")
        assert a.alarm_level in ("严重", "警告", "提示")
        assert a.handle_status == "待处理"
        before = len(rows)

        # 第二次运行：同 (序列,项目,周期) 已存在 → 不重复派警
        r2 = svc.run_anomaly_detection(db, project_id=pid)
        db.commit()
        assert r2["created"] == 0
        after = db.scalar(
            select(Alarm.id)
            .where(Alarm.project_id == pid, Alarm.alarm_type == ALARM_TYPE_ANOMALY)
            .limit(1000)
        )
        assert after is not None
        cnt = len(
            db.scalars(
                select(Alarm.id).where(
                    Alarm.project_id == pid, Alarm.alarm_type == ALARM_TYPE_ANOMALY
                )
            ).all()
        )
        assert cnt == before
    finally:
        db.close()


def test_anomalies_preview_endpoint(env):
    c: TestClient = env["client"]
    h = _h(env["admin_token"])
    pid = env["pid"]

    r = c.get("/api/v1/metrics/anomalies", headers=h, params={"lookback_days": 30})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0
    data = body["data"]
    assert data["lookback_days"] == 30
    assert set(data["params"].keys()) == {"k", "window", "min_trailing", "min_points"}
    # 尖刺项目应出现在异常明细中（alarm 序列 spike）
    mine = [x for x in data["items"] if x["project_id"] == pid and x["series_key"] == "alarm"]
    assert mine, "尖刺项目未被检出"
    assert mine[0]["direction"] == "spike"
    assert mine[0]["level"] in ("严重", "警告", "提示")

    # 预览不落库：端点调用不产生 trend_anomaly 告警
    db = SessionLocal()
    try:
        cnt = len(
            db.scalars(
                select(Alarm.id).where(
                    Alarm.project_id == pid, Alarm.alarm_type == ALARM_TYPE_ANOMALY
                )
            ).all()
        )
        # env 里只有 test_run 创建过（本测试独立 fixture，应为 0）
        assert cnt == 0
    finally:
        db.close()
