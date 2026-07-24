"""智能核心 v2：风险/健康分时序快照 测试。

覆盖：
- service 层：run_snapshot 落库 + get_risk_trend 可回查（本次快照为最新一条）；
- 接口层：snapshot/run（超管）、risk-latest、risk-trend 鉴权与数据正确；
- 非超管不可手动触发。

测试前后清空 risk_health_snapshot 表，避免与失败残留行互相干扰。
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.model.snapshot import RiskHealthSnapshot


@pytest.fixture
def wipe_snapshots():
    db = SessionLocal()
    try:
        db.execute(delete(RiskHealthSnapshot))
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.execute(delete(RiskHealthSnapshot))
        db.commit()
    finally:
        db.close()


def test_snapshot_service_inserts_and_trend(wipe_snapshots):
    from app.service import metrics_snapshot as svc

    db = SessionLocal()
    try:
        res = svc.run_snapshot(db, hours=24, days=7)
        assert res["devices"] > 0, "应有设备快照"
        assert res["projects"] > 0, "应有项目快照"
        snap_at = res["snapshot_at"]

        latest = svc.get_latest_risk_snapshots(db)
        assert latest, "应取到最新项目风险快照"
        pid = latest[0]["project_id"]

        series = svc.get_risk_trend(db, pid, days=7)
        assert series, "应取到趋势序列"
        # 本次快照是最新一条（与端点同源）
        newest = max(datetime.fromisoformat(s["snapshot_at"]) for s in series)
        assert newest == datetime.fromisoformat(snap_at)
    finally:
        db.close()


def test_metrics_endpoints(client: TestClient, admin_token: str, wipe_snapshots):
    h = {"Authorization": f"Bearer {admin_token}"}

    r = client.post("/api/v1/metrics/snapshot/run", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["devices"] > 0

    r = client.get("/api/v1/metrics/risk-latest", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    assert items, "risk-latest 应返回项目"
    pid = items[0]["project_id"]

    r = client.get(f"/api/v1/metrics/risk-trend?project_id={pid}&days=7", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["project_id"] == pid


def test_snapshot_run_requires_auth(client: TestClient, wipe_snapshots):
    r = client.post("/api/v1/metrics/snapshot/run")
    assert r.status_code in (401, 403)
