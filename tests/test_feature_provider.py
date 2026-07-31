"""外部特征提供者与特征工程测试（预测特征工程：突破单序列）。

覆盖：
- MockExternalProvider：确定性合成（同一项目/日期结果可复现、每日 5 个特征）；
- FeatureEngineer.build_matrix：日历+外部特征设计矩阵正确；
- _ridge_solve：纯 Python 岭回归精确解；
- backfill_to_db：幂等 upsert 落 external_feature 表；
- ensure_external_features：已存在则跳过回填。

DB 相关用例用 SessionLocal 自建 Project，finally 清理，保证隔离。
"""

from datetime import date, timedelta

from sqlalchemy import delete, func, select

from app.core.database import SessionLocal
from app.model.feature import ExternalFeature
from app.model.project import Project
from app.service import feature_provider as fp
from app.service import forecast_models as m


def test_mock_provider_deterministic_and_shape():
    p = fp.MockExternalProvider()
    d0 = date(2025, 1, 1)
    out1 = p.fetch(7, d0, d0 + timedelta(days=2))
    out2 = p.fetch(7, d0, d0 + timedelta(days=2))
    assert out1 == out2  # 确定性
    # 每日 5 个特征
    days = {(d, name) for d, name, _ in out1}
    assert len(days) == 3 * 5
    names = {name for _, name, _ in out1}
    assert names == set(fp.FEATURE_NAMES)
    # 不同项目应产生不同温度（相位偏移）
    other = p.fetch(99, d0, d0)
    assert other != out1[:5]


def test_feature_engineer_matrix():
    d = date(2025, 1, 1)  # 周三
    ext = {"temperature": 12.5, "device_load": 0.6}
    row = fp.FeatureEngineer.row_for(d, ext)
    assert row[0] == 1.0  # 截距
    assert row[1] == float(d.weekday())  # dow
    assert row[2] == 1.0  # month
    assert row[3] == 0.0  # 非周末
    assert row[4] == 12.5  # temperature
    assert row[8] == 0.6  # device_load
    # 缺失外部特征补 0
    row2 = fp.FeatureEngineer.row_for(d, {})
    assert row2[4:] == [0.0, 0.0, 0.0, 0.0, 0.0]


def test_ridge_solve_exact():
    # y = 2*x1 + 5  （截距5, 斜率2），无噪声应能精确还原
    X = [[1.0, 1.0], [1.0, 2.0], [1.0, 3.0], [1.0, 4.0]]
    y = [7.0, 9.0, 11.0, 13.0]
    beta = m._ridge_solve(X, y)
    assert abs(beta[0] - 5.0) < 1e-4
    assert abs(beta[1] - 2.0) < 1e-4


def test_backfill_upsert_idempotent():
    db = SessionLocal()
    proj = Project(name="test-feature-provider")
    db.add(proj)
    db.flush()
    pid = proj.id
    try:
        d0 = date(2025, 6, 1)
        n = fp.backfill_to_db(db, [pid], d0, d0 + timedelta(days=2), source="mock")
        assert n == 3 * 5
        db.commit()
        count = db.scalar(
            select(func.count())
            .select_from(ExternalFeature)
            .where(ExternalFeature.project_id == pid)
        )
        assert count == 15
        # 再次回填同范围 → 幂等（行数不变，仅更新值）
        n2 = fp.backfill_to_db(db, [pid], d0, d0 + timedelta(days=2), source="mock")
        assert n2 == 15
        db.commit()
        count2 = db.scalar(
            select(func.count())
            .select_from(ExternalFeature)
            .where(ExternalFeature.project_id == pid)
        )
        assert count2 == 15
        # load_external_dict 能按日期取回
        ext = fp.load_external_dict(db, pid, d0, d0 + timedelta(days=2))
        assert d0.isoformat() in ext
        assert "temperature" in ext[d0.isoformat()]
    finally:
        db.execute(delete(ExternalFeature).where(ExternalFeature.project_id == pid))
        db.delete(proj)
        db.commit()
        db.close()


def test_ensure_external_features_skips_when_present():
    db = SessionLocal()
    proj = Project(name="test-feature-ensure")
    db.add(proj)
    db.flush()
    pid = proj.id
    d0 = date(2025, 7, 1)
    try:
        fp.backfill_to_db(db, [pid], d0, d0 + timedelta(days=1), source="mock")
        db.commit()
        # 已存在 → ensure 不报错，且本项目特征保持完整（范围含该日）
        fp.ensure_external_features(db, days=10)
        ext = fp.load_external_dict(db, pid, d0, d0 + timedelta(days=1))
        assert d0.isoformat() in ext
        assert len(ext[d0.isoformat()]) == 5
    finally:
        db.execute(delete(ExternalFeature).where(ExternalFeature.project_id == pid))
        db.delete(proj)
        db.commit()
        db.close()
