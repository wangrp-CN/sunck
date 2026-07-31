"""告警态势总览端点回归测试。

覆盖 GET /v1/alarms/situation：
- KPI：今日新增 / 待处理 / 严重待处理 / 活跃预防式
- pending_by_level：待处理按级别分布
- trend：近 14 天每日按级别堆叠（长度=14、各日合计=总告警数）

另覆盖 GET /v1/alarms/preventive-summary（此前 summarize_preventive 用
`with_entities`，在 SQLAlchemy 2.0 下不存在，会 500；现改用 `with_only_columns`）。

本套件假设测试库干净：fixture 起始清空 alarm 表，按 project_id 清理自建数据，
避免历史运行残留（尤其预防式告警 device_no 非 SIT 前缀）污染计数。
"""

import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.constants import ALARM_TYPE_PREVENTIVE
from app.core.database import SessionLocal
from app.main import app
from app.model.alarm import Alarm
from app.model.project import Project


def _uid() -> str:
    return secrets.token_hex(3)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_token(client):
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin@123456"})
    assert r.status_code == 200, r.text
    return r.json()["data"]["access_token"]


@pytest.fixture
def seeded():
    """建项目 + 5 条不同状态/级别/时间的告警，返回 project_id。

    - A 待处理/严重/今天        → today_new, pending, pending_critical
    - B 待处理/警告/昨天        → pending
    - C 待处理/提示/前天        → pending
    - D 已处理/严重/3 天前      → 仅入趋势（非今日、非待处理）
    - E 待处理/警告/今天/预防式 → today_new, pending, active_preventive
    """
    db = SessionLocal()
    try:
        # 清掉历史残留，保证精确计数（测试库应在干净状态下运行）
        db.execute(Alarm.__table__.delete())
        db.commit()
        p = Project(name=f"SIT{_uid()}_态势", status="在建")
        db.add(p)
        db.flush()
        pid = p.id
        now = datetime.now(timezone.utc)
        specs = [
            ("严重", "待处理", now, None),
            ("警告", "待处理", now - timedelta(days=1), None),
            ("提示", "待处理", now - timedelta(days=2), None),
            ("严重", "已处理", now - timedelta(days=3), None),
            ("警告", "待处理", now, ALARM_TYPE_PREVENTIVE),
        ]
        for i, (lvl, hs, at, atype) in enumerate(specs):
            db.add(
                Alarm(
                    project_id=pid,
                    alarm_type=atype,
                    device_type="locate",
                    device_name=f"设备{i}",
                    device_no=f"SIT_{i}" if atype is None else f"preventive:risk_index:P{pid}:7",
                    alarm_info=f"态势告警{i}",
                    alarm_status="告警开始",
                    alarm_level=lvl,
                    handle_status=hs,
                    alarm_time=at,
                )
            )
        db.commit()
        yield pid
    finally:
        db.close()


def _cleanup(pid: int):
    db = SessionLocal()
    try:
        db.execute(Alarm.__table__.delete().where(Alarm.project_id == pid))
        db.commit()
    finally:
        db.close()


def test_situation_kpi_and_distribution(client, admin_token, seeded):
    pid = seeded
    try:
        r = client.get(
            "/api/v1/alarms/situation", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        d = body["data"]
        kpi = d["kpi"]
        # A + E 均为今日 → 今日新增 = 2
        assert kpi["today_new"] == 2
        # A + B + C + E 待处理 = 4
        assert kpi["pending"] == 4
        # 仅 A 为严重待处理 = 1
        assert kpi["pending_critical"] == 1
        # E 为活跃预防式（待处理）= 1
        assert kpi["active_preventive"] == 1
        # 待处理按级别：严重1 / 警告2(B+E) / 提示1
        assert d["pending_by_level"].get("严重") == 1
        assert d["pending_by_level"].get("警告") == 2
        assert d["pending_by_level"].get("提示") == 1
    finally:
        _cleanup(pid)


def test_situation_trend_shape(client, admin_token, seeded):
    pid = seeded
    try:
        r = client.get(
            "/api/v1/alarms/situation?days=14", headers={"Authorization": f"Bearer {admin_token}"}
        )
        assert r.status_code == 200
        trend = r.json()["data"]["trend"]
        assert len(trend) == 14
        # 各日合计 = 全部 5 条告警
        assert sum(t["total"] for t in trend) == 5
        # 最新一日（趋势末位）含今日 A(严重)+E(警告) = 2
        assert trend[-1]["total"] == 2
        assert trend[-1]["严重"] == 1
        assert trend[-1]["警告"] == 1
        # 每个点字段齐全
        for t in trend:
            assert set(t.keys()) >= {"date", "total", "严重", "警告", "提示"}
    finally:
        _cleanup(pid)


def test_preventive_summary_endpoint(client, admin_token, seeded):
    """回归 summarize_preventive：此前 with_entities 在 SA2.0 下不可用（潜在 500），
    现改用 with_only_columns，需确保端点正常返回活跃预防式告警。"""
    pid = seeded
    try:
        r = client.get(
            "/api/v1/alarms/preventive-summary",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["code"] == 0
        # seeded 中 E 为待处理预防式（警告）
        assert body["data"]["total"] == 1
        assert body["data"]["by_level"].get("警告") == 1
    finally:
        _cleanup(pid)
