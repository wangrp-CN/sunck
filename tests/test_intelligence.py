"""智能核心深化（#④）测试。

覆盖：
- ④-1 阈值自学习标定：service 标定/落库/查询/应用闭环；evaluate_risk_alerts 尊重生效阈值；
       接口 标定/查看/应用 流程 + 超管鉴权。
- ④-2 关联去重：GET /correlations/dedup-stats 返回 TTL/开关。
- ④-3 视频 AI：POST /videos/ai/analyze 返回 pending_capability 占位。
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import settings
from app.core.database import SessionLocal
from app.model.risk_alert import (
    RiskAlertState,
    RiskAlertThresholdCalibration,
    RiskAlertThresholdOverride,
)
from app.model.snapshot import RiskHealthSnapshot
from app.service import risk_alert as alert_svc
from app.service import threshold_calibration as tc


@pytest.fixture
def wipe():
    db = SessionLocal()
    try:
        db.execute(delete(RiskAlertThresholdOverride))
        db.execute(delete(RiskAlertThresholdCalibration))
        db.execute(delete(RiskAlertState))
        db.execute(delete(RiskHealthSnapshot))
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.execute(delete(RiskAlertThresholdOverride))
        db.execute(delete(RiskAlertThresholdCalibration))
        db.execute(delete(RiskAlertState))
        db.execute(delete(RiskHealthSnapshot))
        db.commit()
    finally:
        db.close()


def _add_snapshot(db, ref_id: int, risk_index: int, when: datetime, name="P"):
    db.add(
        RiskHealthSnapshot(
            scope_type="project",
            ref_id=str(ref_id),
            name=name,
            risk_index=risk_index,
            risk_level="高" if risk_index >= 60 else "低",
            raw_score=risk_index,
            snapshot_at=when,
        )
    )


# ---------------------------------------------------------------------------
# ④-1 阈值自学习标定 · service
# ---------------------------------------------------------------------------


def test_calibrate_uses_distribution(wipe):
    """标定应基于历史分布给出 [min,max] 内推荐阈值，且目标越阈率越高→阈值越低。"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        for i, v in enumerate(range(10, 101, 10)):  # 10,20,...,100
            _add_snapshot(db, 1000 + i, v, now - timedelta(hours=i))
        db.commit()

        low_target = tc.calibrate_threshold(db, window_days=90, target_breach_rate=0.10)
        high_target = tc.calibrate_threshold(db, window_days=90, target_breach_rate=0.50)
        assert 40 <= low_target["recommended_threshold"] <= 90
        assert 40 <= high_target["recommended_threshold"] <= 90
        # 目标越阈率更高（允许更多越阈）→ 推荐阈值更低
        assert low_target["recommended_threshold"] >= high_target["recommended_threshold"]
        assert low_target["sample_count"] == 10
        assert len(low_target["sweep"]) > 0
        assert "p95" in low_target["stats"]
    finally:
        db.close()


def test_active_threshold_override_and_evaluate(wipe):
    """生效阈值：无覆盖回退 settings；apply 后 evaluate_risk_alerts 采纳。"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        _add_snapshot(db, 2001, 70, now, name="阈值项目")
        db.commit()

        # 默认回退 settings
        assert tc.get_active_threshold(db) == settings.risk_alert_threshold

        # 覆盖为 65 → 70 越阈
        tc.apply_threshold(db, 65, source="manual")
        assert tc.get_active_threshold(db) == 65
        breaches = alert_svc.evaluate_risk_alerts(db)
        assert any(b["project_id"] == 2001 for b in breaches)

        # 覆盖为 80 → 70 不越阈
        tc.apply_threshold(db, 80, source="manual")
        breaches2 = alert_svc.evaluate_risk_alerts(db)
        assert not any(b["project_id"] == 2001 for b in breaches2)
    finally:
        db.close()


def test_calibrate_persist_and_latest(wipe):
    """calibrate→persist→get_latest 闭环，to_dict 含解析后的 sweep/stats。"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        for i, v in enumerate(range(10, 101, 10)):
            _add_snapshot(db, 3000 + i, v, now - timedelta(hours=i))
        db.commit()

        result = tc.calibrate_threshold(db, window_days=90, target_breach_rate=0.10)
        row = tc.persist_calibration(db, result)
        latest = tc.get_latest_calibration(db)
        assert latest is not None and latest.id == row.id
        d = latest.to_dict()
        assert d["recommended_threshold"] == result["recommended_threshold"]
        assert isinstance(d["sweep"], list) and len(d["sweep"]) > 0
        assert isinstance(d["stats"], dict) and "p95" in d["stats"]
    finally:
        db.close()


# ---------------------------------------------------------------------------
# ④-1 阈值自学习标定 · 接口
# ---------------------------------------------------------------------------


def test_intelligence_api_flow(client: TestClient, admin_token: str, wipe):
    h = {"Authorization": f"Bearer {admin_token}"}

    # 无 token 拒绝
    r0 = client.get("/api/v1/intelligence/threshold-calibration")
    assert r0.status_code in (401, 403)

    # 查看：默认 active = settings，无最近标定
    r1 = client.get("/api/v1/intelligence/threshold-calibration", headers=h)
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["active_threshold"] == settings.risk_alert_threshold
    assert r1.json()["data"]["latest"] is None

    # 标定（需先有样本；直接调，样本不足时沿用当前阈值不报错）
    r2 = client.post(
        "/api/v1/intelligence/threshold-calibration/calibrate",
        headers=h,
        json={
            "window_days": 90,
            "target_breach_rate": 0.10,
            "min_threshold": 40,
            "max_threshold": 90,
        },
    )
    assert r2.status_code == 200, r2.text
    cid = r2.json()["data"]["calibration_id"]
    assert isinstance(cid, int)

    # 应用
    rec = r2.json()["data"]["recommended_threshold"]
    r3 = client.post(
        "/api/v1/intelligence/threshold-calibration/apply",
        headers=h,
        json={"threshold": rec, "source": "auto", "calibration_id": cid},
    )
    assert r3.status_code == 200, r3.text
    assert r3.json()["data"]["active_threshold"] == rec
    assert r3.json()["data"]["source"] == "auto"

    # 应用后再查看，active 已更新
    r4 = client.get("/api/v1/intelligence/threshold-calibration", headers=h)
    assert r4.json()["data"]["active_threshold"] == rec
    assert r4.json()["data"]["latest"]["id"] == cid


def test_intelligence_apply_rejects_bad_source(client: TestClient, admin_token: str, wipe):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = client.post(
        "/api/v1/intelligence/threshold-calibration/apply",
        headers=h,
        json={"threshold": 50, "source": "bogus"},
    )
    assert r.status_code == 200
    assert r.json()["code"] != 0  # BusinessError: source 非法


# ---------------------------------------------------------------------------
# ④-2 关联去重统计
# ---------------------------------------------------------------------------


def test_correlation_dedup_stats(client: TestClient, admin_token: str):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = client.get("/api/v1/metrics/correlations/dedup-stats", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["fp_ttl_seconds"] == settings.correlation_fp_ttl_seconds
    assert d["dedup_enabled"] == settings.correlation_dedup_enabled
    assert d["active_fingerprints"] >= -1  # -1 表示 Redis 不可用（不阻断）


# ---------------------------------------------------------------------------
# ④-3 视频 AI 异常识别接口预留
# ---------------------------------------------------------------------------


def test_video_ai_analyze_pending(client: TestClient, admin_token: str):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = client.post(
        "/api/v1/videos/ai/analyze",
        headers=h,
        json={"channel_no": "CAM-01", "model": "default"},
    )
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == "pending_capability"
    assert "expected_capabilities" in d
