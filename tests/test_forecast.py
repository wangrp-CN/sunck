"""Phase 5 智能化预测 M1（预测基座）测试。

覆盖：OLS 服务纯函数、compute/run_forecasts 落库、样本不足跳过、
预测列表与重算端点。使用 admin（超管），fixture 清理自建数据保证隔离。
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.model.forecast import Forecast
from app.model.project import Project
from app.model.snapshot import RiskHealthSnapshot
from app.service import forecast_service as svc


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def env(client: TestClient, admin_token: str):
    """挑一个真实项目，铺 10 天线性上升的 risk_index 快照序列。"""
    db = SessionLocal()
    try:
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
        assert pid is not None, "需存在真实项目"
        # 清理该项目旧快照/预测，保证序列可控
        db.execute(
            delete(RiskHealthSnapshot).where(
                RiskHealthSnapshot.scope_type == "project",
                RiskHealthSnapshot.ref_id == str(pid),
            )
        )
        db.execute(delete(Forecast).where(Forecast.ref_id == str(pid)))
        now = datetime.now(timezone.utc)
        # 10 天序列：risk_index 从 10 线性升到 46（斜率 4/天）
        for i in range(10):
            db.add(
                RiskHealthSnapshot(
                    scope_type="project",
                    ref_id=str(pid),
                    name="预测测试项目",
                    risk_index=10 + i * 4,
                    risk_level="低",
                    raw_score=10 + i * 4,
                    snapshot_at=now - timedelta(days=9 - i),
                )
            )
        db.commit()
        yield {"pid": pid, "admin_token": admin_token}
    finally:
        db2 = SessionLocal()
        try:
            db2.execute(
                delete(RiskHealthSnapshot).where(
                    RiskHealthSnapshot.scope_type == "project",
                    RiskHealthSnapshot.ref_id == str(pid),
                )
            )
            db2.execute(delete(Forecast).where(Forecast.ref_id == str(pid)))
            db2.commit()
        finally:
            db2.close()
        db.close()


def test_ols_basic():
    """完美线性序列：斜率/截距应精确还原。"""
    pts = [(0.0, 10.0), (1.0, 14.0), (2.0, 18.0), (3.0, 22.0)]
    slope, intercept = svc._ols(pts)
    assert abs(slope - 4.0) < 1e-9
    assert abs(intercept - 10.0) < 1e-9


def test_ols_flat_and_degenerate():
    slope, intercept = svc._ols([(0.0, 50.0), (1.0, 50.0), (2.0, 50.0)])
    assert abs(slope) < 1e-9 and abs(intercept - 50.0) < 1e-9
    # x 全相等：斜率退化为 0，截距为均值
    slope, intercept = svc._ols([(1.0, 10.0), (1.0, 20.0)])
    assert slope == 0.0 and abs(intercept - 15.0) < 1e-9


def test_compute_forecast_rising(env):
    """上升序列：预测值应高于最新观测，级别按阈值分档。"""
    db = SessionLocal()
    try:
        data = svc.compute_forecast(db, env["pid"], horizon_days=7)
        assert data is not None
        assert data["sample_count"] == 10
        assert data["slope"] > 3.5  # ~4/天
        assert data["last_value"] == 46
        assert data["forecast_value"] > data["last_value"]
        assert data["forecast_value"] <= 100
        # 46 + 7*4 = 74 → 高
        assert data["forecast_level"] == "高"
    finally:
        db.close()


def test_run_forecasts_upsert(env):
    """run_forecasts 应 upsert：跑两次同键只留一条。"""
    db = SessionLocal()
    try:
        stats = svc.run_forecasts(db)
        assert stats["computed"] >= 1
        db.commit()
        svc.run_forecasts(db)
        db.commit()
        rows = db.scalars(
            select(Forecast).where(
                Forecast.ref_id == str(env["pid"]), Forecast.metric == "risk_index"
            )
        ).all()
        assert len(rows) == 1
        assert rows[0].project_id == env["pid"]
    finally:
        db.close()


def test_insufficient_samples_returns_none(client: TestClient, admin_token: str):
    """快照样本不足：compute 返回 None，recompute 端点返回业务错误码。"""
    db = SessionLocal()
    try:
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
        db.execute(
            delete(RiskHealthSnapshot).where(
                RiskHealthSnapshot.scope_type == "project",
                RiskHealthSnapshot.ref_id == str(pid),
            )
        )
        db.commit()
        assert svc.compute_forecast(db, pid) is None
    finally:
        db.close()

    r = client.post(f"/api/v1/forecasts/recompute?project_id={pid}", headers=_h(admin_token))
    assert r.status_code == 200
    assert r.json()["code"] == 1001


def test_api_recompute_and_list(env, client: TestClient):
    c, tok = client, env["admin_token"]
    # 单项目重算
    r = c.post(f"/api/v1/forecasts/recompute?project_id={env['pid']}", headers=_h(tok))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["ref_id"] == str(env["pid"])
    assert data["forecast_value"] > data["last_value"]
    assert data["forecast_at"] and data["computed_at"]

    # 列表（按项目过滤）
    r = c.get(f"/api/v1/forecasts/?project_id={env['pid']}", headers=_h(tok))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert any(i["ref_id"] == str(env["pid"]) for i in items)

    # 全量重算
    r = c.post("/api/v1/forecasts/recompute", headers=_h(tok))
    assert r.status_code == 200
    assert r.json()["data"]["computed"] >= 1
