"""预测命中率报表测试：命中 / 误报 / 待验证 判定与聚合。

构造两个「实际触发预测性预警」的预测（复用 _predictive_breach 越阈判据）：
- risk_index 预测（level=高）：窗口内实际值越阈 → 命中；
- health_score 预测（level=差）：窗口内实际值始终不越阈 → 误报。
并验证 `/v1/forecasts/hit-rate` 端点聚合命中率与按指标分布。
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.model.forecast import Forecast
from app.model.project import Project
from app.model.snapshot import RiskHealthSnapshot
from app.service.forecast_service import METRIC_HEALTH_SCORE, METRIC_RISK_INDEX

_HORIZON = 5


@pytest.fixture
def env():
    db = SessionLocal()
    try:
        p = Project(name="__t__hitrate_proj", dept_id=None, status="在建")
        db.add(p)
        db.flush()
        pid = p.id
        ref = str(pid)
        now = datetime.now(timezone.utc)
        # 10 天快照：risk_index 50→95（窗口内越阈），health_score 恒为 80（永不越阈）
        for i in range(10):
            db.add(
                RiskHealthSnapshot(
                    scope_type="project",
                    ref_id=ref,
                    name="命中率测试项目",
                    risk_index=50 + i * 5,
                    risk_level="低",
                    health_score=80,
                    health_level="优",
                    snapshot_at=now - timedelta(days=9 - i),
                )
            )
        # 风险预测：level=高 → 触发；预测值 70，窗口内实际值将达 85 → 命中
        db.add(
            Forecast(
                project_id=pid,
                scope_type="project",
                ref_id=ref,
                name="命中率测试项目",
                metric=METRIC_RISK_INDEX,
                horizon_days=_HORIZON,
                sample_count=10,
                last_value=85.0,
                slope=5.0,
                intercept=50.0,
                forecast_value=70.0,
                forecast_level="高",
                forecast_at=now - timedelta(days=7),
                computed_at=now - timedelta(days=7),
            )
        )
        # 健康预测：level=差 → 触发；预测值 40，实际恒为 80（不越阈）→ 误报
        db.add(
            Forecast(
                project_id=pid,
                scope_type="project",
                ref_id=ref,
                name="命中率测试项目",
                metric=METRIC_HEALTH_SCORE,
                horizon_days=_HORIZON,
                sample_count=10,
                last_value=80.0,
                slope=-1.0,
                intercept=85.0,
                forecast_value=40.0,
                forecast_level="差",
                forecast_at=now - timedelta(days=7),
                computed_at=now - timedelta(days=7),
            )
        )
        db.commit()
        yield {"pid": pid}
    finally:
        db2 = SessionLocal()
        try:
            db2.execute(delete(Forecast).where(Forecast.ref_id == str(p.id)))
            db2.execute(
                delete(RiskHealthSnapshot).where(
                    RiskHealthSnapshot.scope_type == "project",
                    RiskHealthSnapshot.ref_id == str(p.id),
                )
            )
            db2.execute(delete(Project).where(Project.id == p.id))
            db2.commit()
        finally:
            db2.close()
        db.close()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_hit_rate_endpoint(client, admin_token, env):
    """命中率端点：1 命中 + 1 误报 → hit_rate=0.5，按指标分布正确。"""
    pid = env["pid"]
    r = client.get(f"/api/v1/forecasts/hit-rate?project_id={pid}", headers=_h(admin_token))
    assert r.json()["code"] == 0, r.text
    d = r.json()["data"]
    assert d["verifiable"] == 2
    assert d["hits"] == 1
    assert d["false_positives"] == 1
    assert d["hit_rate"] == 0.5
    assert d["by_metric"][METRIC_RISK_INDEX]["hits"] == 1
    assert d["by_metric"][METRIC_RISK_INDEX]["hit_rate"] == 1.0
    assert d["by_metric"][METRIC_HEALTH_SCORE]["false_positives"] == 1
    assert d["by_metric"][METRIC_HEALTH_SCORE]["hit_rate"] == 0.0
    assert d["avg_lead_hours"] is not None


def test_hit_rate_pending_not_in_denominator(client, admin_token, env):
    """窗口未结束的预测计入 pending，不计入命中率分母。"""
    db = SessionLocal()
    try:
        fc = db.scalars(
            select(Forecast).where(
                Forecast.ref_id == str(env["pid"]),
                Forecast.metric == METRIC_RISK_INDEX,
            )
        ).first()
        # 把预测目标时刻推到未来，使窗口未结束 → 变 pending
        fc.forecast_at = datetime.now(timezone.utc) + timedelta(days=3)
        db.commit()
    finally:
        db.close()

    r = client.get(f"/api/v1/forecasts/hit-rate?project_id={env['pid']}", headers=_h(admin_token))
    d = r.json()["data"]
    # 风险预测转 pending；健康预测仍为误报 → verifiable=1, pending=1
    assert d["verifiable"] == 1
    assert d["pending"] == 1
    assert d["false_positives"] == 1
    assert d["hits"] == 0
