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


def test_band_perfect_linear_zero_width(env):
    """完美线性序列：残差为 0，置信带宽度为 0（上下界==预测值）。"""
    db = SessionLocal()
    try:
        data = svc.compute_forecast(db, env["pid"], horizon_days=7)
        assert data is not None
        assert data["std_resid"] == 0.0
        assert data["forecast_lower"] == data["forecast_value"] == data["forecast_upper"]
    finally:
        db.close()


def test_band_noisy_series(env):
    """带噪声序列：std_resid>0，上界>预测值>下界。"""
    db = SessionLocal()
    try:
        # 在既有 10 点线性序列上叠一个偏离点制造残差
        now = datetime.now(timezone.utc)
        db.add(
            RiskHealthSnapshot(
                scope_type="project",
                ref_id=str(env["pid"]),
                name="预测测试项目",
                risk_index=80,  # 明显偏离线性趋势
                risk_level="高",
                raw_score=80,
                snapshot_at=now - timedelta(hours=12),
            )
        )
        db.commit()
        data = svc.compute_forecast(db, env["pid"], horizon_days=7)
        assert data is not None
        assert data["std_resid"] > 0
        assert data["forecast_lower"] < data["forecast_value"] < data["forecast_upper"]
        assert 0 <= data["forecast_lower"] and data["forecast_upper"] <= 100
    finally:
        db.close()


def test_device_health_forecast(env):
    """设备 health_score 序列（M2 多指标）：预测级别按健康分档（优/良/中/差）。"""
    db = SessionLocal()
    dno = f"FC-TEST-{env['pid']}"
    try:
        now = datetime.now(timezone.utc)
        # 10 天健康分缓慢下降：95 → 77（斜率 -2/天）
        for i in range(10):
            db.add(
                RiskHealthSnapshot(
                    scope_type="device",
                    ref_id=dno,
                    name="预测测试设备",
                    health_score=95 - i * 2,
                    health_level="优",
                    online_state="fresh",
                    snapshot_at=now - timedelta(days=9 - i),
                )
            )
        db.commit()
        data = svc.compute_device_forecast(db, dno, horizon_days=7)
        assert data is not None
        assert data["metric"] == "health_score"
        assert data["scope_type"] == "device" and data["ref_id"] == dno
        # 77 - 7*2 = 63 → 「中」（health 分档，而非 risk 分档）
        assert data["forecast_value"] < data["last_value"]
        assert data["forecast_level"] == "中"
    finally:
        db2 = SessionLocal()
        try:
            db2.execute(delete(RiskHealthSnapshot).where(RiskHealthSnapshot.ref_id == dno))
            db2.execute(delete(Forecast).where(Forecast.ref_id == dno))
            db2.commit()
        finally:
            db2.close()
        db.close()


def test_api_preview(env, client: TestClient):
    """预览端点：series + forecast(含置信带)；样本不足时 forecast 为 null。"""
    c, tok = client, env["admin_token"]
    r = c.get(
        f"/api/v1/forecasts/preview?scope_type=project&ref_id={env['pid']}",
        headers=_h(tok),
    )
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data["series"]) == 10
    fc = data["forecast"]
    assert fc is not None
    assert fc["forecast_lower"] <= fc["forecast_value"] <= fc["forecast_upper"]
    assert fc["forecast_at"] and fc["sample_count"] == 10

    # 非法 scope_type
    r = c.get("/api/v1/forecasts/preview?scope_type=bad&ref_id=1", headers=_h(tok))
    assert r.json()["code"] == 400

    # 不存在的设备：admin 超管 is_all 放行，返回空序列 + forecast null
    r = c.get(
        "/api/v1/forecasts/preview?scope_type=device&ref_id=NO-SUCH-DEV",
        headers=_h(tok),
    )
    data = r.json()["data"]
    assert data["series"] == [] and data["forecast"] is None


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
