"""walk-forward 回测 + A/B 命中率聚合测试（预测模型升级 + A/B 对照）。

覆盖：
- ``run_backtest``：walk-forward 落 ``forecast_backtest``，越阈预测才入库；
- ``compute_ab_hitrate``：按 model_version 聚合命中率/误报率/平均提前量 + 增量对比；
- ``POST /v1/forecasts/backtest`` 与 ``GET /v1/forecasts/hit-rate/ab`` 端点（code==0）。

使用 admin（超管）+ DataScope(is_all=True)，fixture 清理自建数据保证隔离。
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.data_scope import DataScope
from app.core.database import SessionLocal
from app.model.forecast_backtest import ForecastBacktest
from app.model.project import Project
from app.model.snapshot import RiskHealthSnapshot
from app.service import backtest_service as bt_svc


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def bt_env(client: TestClient, admin_token: str):
    """挑一个真实项目，铺 60 天单调上升的 risk_index 序列（确保外推越阈且实际如期越阈）。"""
    db = SessionLocal()
    try:
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
        assert pid is not None, "需存在真实项目"
        db.execute(
            delete(RiskHealthSnapshot).where(
                RiskHealthSnapshot.scope_type == "project",
                RiskHealthSnapshot.ref_id == str(pid),
            )
        )
        db.execute(delete(ForecastBacktest).where(ForecastBacktest.ref_id == str(pid)))
        now = datetime.now(timezone.utc)
        for i in range(60):
            v = 20 + 2 * i  # 20 → 138，单调上升
            level = "高" if v >= 60 else ("中" if v >= 30 else "低")
            db.add(
                RiskHealthSnapshot(
                    scope_type="project",
                    ref_id=str(pid),
                    name="回测项目",
                    risk_index=v,
                    risk_level=level,
                    raw_score=v,
                    snapshot_at=now - timedelta(days=59 - i),
                )
            )
        db.commit()
        yield pid
    finally:
        db2 = SessionLocal()
        try:
            db2.execute(
                delete(RiskHealthSnapshot).where(
                    RiskHealthSnapshot.scope_type == "project",
                    RiskHealthSnapshot.ref_id == str(pid),
                )
            )
            db2.execute(delete(ForecastBacktest).where(ForecastBacktest.ref_id == str(pid)))
            db2.commit()
        finally:
            db2.close()
        db.close()


def test_run_backtest_lands_rows(bt_env):
    """run_backtest 仅保留越阈预测，且两模型均落库、命中判定正确。"""
    pid = bt_env
    db = SessionLocal()
    try:
        summary = bt_svc.run_backtest(db, days=90, horizon=7)
        db.commit()
        assert summary["rows"] > 0
        assert set(summary["models"]) == {"ols_v1", "hw_v1"}
        for mv in ("ols_v1", "hw_v1"):
            assert summary["by_model"][mv]["rows"] > 0

        rows = db.scalars(select(ForecastBacktest).where(ForecastBacktest.ref_id == str(pid))).all()
        assert len(rows) > 0
        assert {r.model_version for r in rows} == {"ols_v1", "hw_v1"}
        # 单调上升序列：外推值应被实际值如期超越 → 命中
        assert all(r.hit is True for r in rows)
        assert all(r.verified is True for r in rows)
    finally:
        db.close()


def test_compute_ab_hitrate_aggregates(bt_env):
    """compute_ab_hitrate 按模型聚合，并给出 baseline(challenger) 增量对比。"""
    db = SessionLocal()
    try:
        bt_svc.run_backtest(db, days=90, horizon=7)
        db.commit()

        data = bt_svc.compute_ab_hitrate(db, DataScope(is_all=True), days=90)
        models = data["models"]
        assert len(models) == 2
        versions = {m["model_version"] for m in models}
        assert versions == {"ols_v1", "hw_v1"}
        for m in models:
            assert m["verifiable"] > 0
            assert m["hits"] > 0
            assert m["hit_rate"] is not None and 0.0 <= m["hit_rate"] <= 1.0
            assert m["false_positive_rate"] is not None and 0.0 <= m["false_positive_rate"] <= 1.0

        comp = data["comparison"]
        assert comp is not None
        assert comp["baseline"] == "ols_v1"
        assert comp["challenger"] == "hw_v1"
        assert comp["baseline_label"] == "OLS 线性"
        assert comp["challenger_label"] == "Holt-Winters 季节趋势"
    finally:
        db.close()


def test_backtest_and_hitrate_endpoints(client: TestClient, admin_token: str, bt_env):
    """回测端点落库 + A/B 命中率端点返回两模型对比（code==0）。"""
    r = client.post(
        "/api/v1/forecasts/backtest",
        params={"days": 90, "horizon_days": 7},
        headers=_h(admin_token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0, body
    assert body["data"]["rows"] > 0

    r2 = client.get(
        "/api/v1/forecasts/hit-rate/ab",
        params={"days": 90},
        headers=_h(admin_token),
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["code"] == 0, body2
    assert len(body2["data"]["models"]) == 2
    assert body2["data"]["comparison"] is not None
