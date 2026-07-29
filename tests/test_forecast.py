"""Phase 5 智能化预测 M1（预测基座）测试。

覆盖：OLS 服务纯函数、compute/run_forecasts 落库、样本不足跳过、
预测列表与重算端点。使用 admin（超管），fixture 清理自建数据保证隔离。
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.model.alarm import Alarm
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


# ---------------------------------------------------------------------------
# M3：预测性预警回灌告警流
# ---------------------------------------------------------------------------


def _seed_forecast(db, *, metric, level, value, pid, ref_id, name, horizon=7):
    """落一条越阈预测，供 run_predictive_alerts 触发告警。"""
    now = datetime.now(timezone.utc)
    fc = Forecast(
        project_id=pid,
        scope_type="project" if metric == "risk_index" else "device",
        ref_id=str(ref_id),
        name=name,
        metric=metric,
        horizon_days=horizon,
        sample_count=10,
        last_value=46.0,
        slope=4.0,
        intercept=10.0,
        forecast_value=float(value),
        forecast_level=level,
        forecast_lower=max(0.0, float(value) - 4.0),
        forecast_upper=min(100.0, float(value) + 4.0),
        forecast_at=now + timedelta(days=horizon),
        computed_at=now,
    )
    db.add(fc)
    db.commit()
    return fc


def test_run_predictive_alerts_risk_high():
    """风险预测越阈（高）：生成 predictive_alert 告警（警告级别）。"""
    db = SessionLocal()
    try:
        db.execute(delete(Alarm).where(Alarm.alarm_type == "predictive_alert"))
        db.execute(delete(Forecast))
        db.commit()
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
        ref = f"{pid}-{uuid4().hex[:8]}"  # 唯一 ref_id 避免 Redis 去重键跨测试冲突
        _seed_forecast(
            db, metric="risk_index", level="高", value=74.0, pid=pid, ref_id=ref, name="测试项目"
        )
        db.commit()

        res = svc.run_predictive_alerts(db)
        db.commit()
        assert res["created"] == 1
        alarm = db.scalars(select(Alarm).where(Alarm.alarm_type == "predictive_alert")).first()
        assert alarm is not None
        assert alarm.project_id == pid
        assert alarm.alarm_level == "警告"
        assert "风险预测预警" in alarm.alarm_info
        assert "95% 置信区间" in alarm.alarm_info
        assert alarm.device_no == f"predictive:risk_index:{ref}:7"
    finally:
        db.execute(delete(Alarm).where(Alarm.alarm_type == "predictive_alert"))
        db.execute(delete(Forecast))
        db.commit()
        db.close()


def test_run_predictive_alerts_health_mid():
    """设备健康预测「中」：生成 predictive_alert（警告级别）。"""
    db = SessionLocal()
    try:
        db.execute(delete(Alarm).where(Alarm.alarm_type == "predictive_alert"))
        db.execute(delete(Forecast))
        db.commit()
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
        dno = f"FC-PRED-{pid}-{uuid4().hex[:8]}"
        _seed_forecast(
            db,
            metric="health_score",
            level="中",
            value=63.0,
            pid=pid,
            ref_id=dno,
            name="预测测试设备",
        )
        db.commit()

        res = svc.run_predictive_alerts(db)
        db.commit()
        assert res["created"] == 1
        alarm = db.scalars(select(Alarm).where(Alarm.alarm_type == "predictive_alert")).first()
        assert alarm is not None
        assert alarm.alarm_level == "警告"
        assert "健康预测预警" in alarm.alarm_info
        assert alarm.device_no == f"predictive:health_score:{dno}:7"
    finally:
        db.execute(delete(Alarm).where(Alarm.alarm_type == "predictive_alert"))
        db.execute(delete(Forecast))
        db.commit()
        db.close()


def test_predictive_alerts_idempotent():
    """同预测重复运行：仅生成一条告警（device_no 编码幂等）。"""
    db = SessionLocal()
    try:
        db.execute(delete(Alarm).where(Alarm.alarm_type == "predictive_alert"))
        db.execute(delete(Forecast))
        db.commit()
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
        ref = f"{pid}-{uuid4().hex[:8]}"
        _seed_forecast(
            db, metric="risk_index", level="高", value=74.0, pid=pid, ref_id=ref, name="测试项目"
        )
        db.commit()

        assert svc.run_predictive_alerts(db)["created"] == 1
        db.commit()
        # 第二次运行（预测仍越阈）：应幂等，不再新增
        assert svc.run_predictive_alerts(db)["created"] == 0
        db.commit()
        total = db.scalars(select(Alarm).where(Alarm.alarm_type == "predictive_alert")).all()
        assert len(total) == 1
    finally:
        db.execute(delete(Alarm).where(Alarm.alarm_type == "predictive_alert"))
        db.execute(delete(Forecast))
        db.commit()
        db.close()


def test_predictive_alerts_skips_non_breach():
    """未越阈预测（risk 中 / health 优）不应生成告警。"""
    db = SessionLocal()
    try:
        db.execute(delete(Alarm).where(Alarm.alarm_type == "predictive_alert"))
        db.execute(delete(Forecast))
        db.commit()
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
        # risk 中（<60）不触发
        _seed_forecast(
            db,
            metric="risk_index",
            level="中",
            value=45.0,
            pid=pid,
            ref_id=f"{pid}-{uuid4().hex[:8]}",
            name="测试中",
        )
        # health 优不触发
        _seed_forecast(
            db,
            metric="health_score",
            level="优",
            value=95.0,
            pid=pid,
            ref_id=f"FC-PRED-{pid}-{uuid4().hex[:8]}",
            name="测试优",
        )
        db.commit()

        res = svc.run_predictive_alerts(db)
        db.commit()
        assert res["created"] == 0
        assert (
            db.scalars(select(Alarm).where(Alarm.alarm_type == "predictive_alert")).first() is None
        )
    finally:
        db.execute(delete(Alarm).where(Alarm.alarm_type == "predictive_alert"))
        db.execute(delete(Forecast))
        db.commit()
        db.close()
