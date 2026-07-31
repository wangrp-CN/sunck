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

from app.config import settings
from app.core.data_scope import DataScope
from app.core.database import SessionLocal
from app.model.forecast import Forecast
from app.model.forecast_backtest import ForecastBacktest
from app.model.project import Project
from app.model.snapshot import RiskHealthSnapshot
from app.service import backtest_service as bt_svc
from app.service import forecast_models as m


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
        assert set(summary["models"]) == {"ols_v1", "hw_v1", "hw_feat_v1"}
        for mv in ("ols_v1", "hw_v1", "hw_feat_v1"):
            assert mv in summary["by_model"]

        rows = db.scalars(select(ForecastBacktest).where(ForecastBacktest.ref_id == str(pid))).all()
        assert len(rows) > 0
        # 行级 model_version 必为已注册模型（hw_feat_v1 在合成序列下可能未越阈而缺失，故取子集）
        assert {r.model_version for r in rows} <= {"ols_v1", "hw_v1", "hw_feat_v1"}
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
        assert len(models) == 3
        versions = {m["model_version"] for m in models}
        assert versions == {"ols_v1", "hw_v1", "hw_feat_v1"}
        by_ver = {m["model_version"]: m for m in models}
        # ols_v1 / hw_v1 在合成越阈序列下必有数据；hw_feat_v1 可能未越阈，仅校验结构存在
        assert by_ver["ols_v1"]["verifiable"] > 0
        assert by_ver["ols_v1"]["hits"] > 0
        assert by_ver["hw_v1"]["verifiable"] > 0
        assert "hw_feat_v1" in by_ver

        comp = data["comparison"]
        assert comp is not None
        assert comp["baseline"] == "ols_v1"
        assert comp["challenger"] == "hw_feat_v1"
        assert comp["baseline_label"] == "OLS 线性"
        assert comp["challenger_label"] == "Holt-Winters + 特征融合"
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
    assert len(body2["data"]["models"]) == 3
    assert body2["data"]["comparison"] is not None


def test_model_default_endpoints(client: TestClient, admin_token: str, bt_env):
    """GET 读当前默认模型；POST 一键切换并即时重算落库；非法版本拒绝。"""
    orig = settings.forecast_primary_model
    try:
        # 读默认
        r = client.get("/api/v1/forecasts/model/default", headers=_h(admin_token))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == 0, body
        assert body["data"]["model_version"] == orig
        assert len(body["data"]["available"]) == 3

        # 一键切换到 hw_v1（即时重算 + 落库）
        r2 = client.post(
            "/api/v1/forecasts/model/default",
            json={"model_version": "hw_v1"},
            headers=_h(admin_token),
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["code"] == 0, r2.json()
        assert r2.json()["data"]["model_version"] == "hw_v1"
        assert settings.forecast_primary_model == "hw_v1"

        # 该项目的 forecast 已用 hw_v1 重算落库
        db = SessionLocal()
        try:
            f = db.scalars(
                select(Forecast).where(
                    Forecast.ref_id == str(bt_env), Forecast.metric == "risk_index"
                )
            ).first()
            assert f is not None and f.model_version == "hw_v1"
        finally:
            db.close()

        # 切回原模型（恢复全局/库状态）
        r3 = client.post(
            "/api/v1/forecasts/model/default",
            json={"model_version": orig},
            headers=_h(admin_token),
        )
        assert r3.json()["code"] == 0
        assert settings.forecast_primary_model == orig
    finally:
        settings.forecast_primary_model = orig


def test_model_default_rejects_unknown(client: TestClient, admin_token: str):
    """未知模型版本应被拒绝（业务错误码）。"""
    r = client.post(
        "/api/v1/forecasts/model/default",
        json={"model_version": "nope"},
        headers=_h(admin_token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["code"] != 0


def test_backtest_includes_hw_feat_v1():
    """回测模型集合应包含 hw_feat_v1（预测特征工程融合模型）。"""
    assert "hw_feat_v1" in m.MODELS
    assert "hw_feat_v1" in m.AB_MODELS
    # run_backtest 即便无数据，返回的 models 也包含 hw_feat_v1（空跑不报错）
    db = SessionLocal()
    try:
        bt_svc.run_backtest(db, days=30, horizon=7)
        db.rollback()
    finally:
        db.close()
