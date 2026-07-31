"""预测模型注册表测试（预测模型升级 + A/B 对照）。

覆盖：
- ``forecast_ols``：完美线性序列还原斜率/截距；退化与截断；
- ``forecast_holt_winters``：≥2 周走周季节性、<2 周退化为 Holt、<3 点返回 None；
- ``_level_for`` 分档复用 app.core.scoring 口径；
- ``forecast_by_model`` 未知版本回退 PRIMARY_MODEL；
无需数据库，纯函数确定性验证。
"""

from datetime import datetime, timedelta, timezone

from app.config import settings
from app.service import forecast_models as m
from app.service import forecast_service as svc

METRIC_RISK = "risk_index"
METRIC_HEALTH = "health_score"


def _series(values: list[float], start: datetime | None = None) -> list[tuple[datetime, float]]:
    t0 = start or datetime.now(timezone.utc)
    return [(t0 + timedelta(days=i), v) for i, v in enumerate(values)]


def test_forecast_ols_perfect_linear():
    """完美线性序列：斜率/截距精确还原，外推值正确分档。"""
    s = _series([10 + 4 * i for i in range(10)])  # 斜率 4/天，截距 10
    d = m.forecast_ols(s, METRIC_RISK, 7)
    assert d is not None
    assert abs(d["slope"] - 4.0) < 1e-6
    assert abs(d["intercept"] - 10.0) < 1e-6
    # 末点 x=9，外推 7 天 → x_target=16 → 4*16+10=74
    assert d["forecast_value"] == 74.0
    assert d["forecast_level"] == "高"
    assert d["model_version"] == "ols_v1"
    assert d["last_value"] == 46


def test_forecast_ols_degenerate_and_none():
    """样本 < 2 返回 None；n==2 退化为 std=0 的线性。"""
    assert m.forecast_ols([(datetime.now(timezone.utc), 1.0)], METRIC_RISK, 7) is None
    d = m.forecast_ols(_series([10.0, 20.0]), METRIC_RISK, 7)
    assert d is not None
    assert d["std_resid"] == 0.0


def test_forecast_ols_clamp():
    """预测值超出 [0,100] 应被截断。"""
    up = m.forecast_ols(_series([0.0, 100.0, 200.0]), METRIC_RISK, 30)
    assert up is not None and up["forecast_value"] == 100.0
    down = m.forecast_ols(_series([100.0, 50.0, 0.0]), METRIC_RISK, 30)
    assert down is not None and down["forecast_value"] == 0.0


def test_forecast_hw_seasonal_long_series():
    """≥ 2 周序列：走三重指数平滑（周季节性），结果合理截断。"""
    import math

    base = datetime.now(timezone.utc)
    vals = [50.0 + i * 1.0 + 8.0 * math.sin(2 * math.pi * i / 7) for i in range(21)]
    s = _series(vals, start=base)
    d = m.forecast_holt_winters(s, METRIC_RISK, 7)
    assert d is not None
    assert d["model_version"] == "hw_v1"
    assert 0.0 <= d["forecast_value"] <= 100.0
    # 置信带应包裹预测值（截断后允许相等）
    assert d["forecast_lower"] <= d["forecast_value"] <= d["forecast_upper"]


def test_forecast_hw_short_returns_none():
    """序列 < 3 点返回 None。"""
    assert m.forecast_holt_winters(_series([1.0, 2.0]), METRIC_RISK, 7) is None


def test_forecast_hw_degrades_to_holt():
    """3 ≤ n < 2 周：退化为 Holt 线性趋势，仍返回字典。"""
    s = _series([20.0 + i * 1.5 for i in range(10)])
    d = m.forecast_holt_winters(s, METRIC_RISK, 7)
    assert d is not None
    assert d["model_version"] == "hw_v1"
    # 上升序列外推应高于末点（趋势为正）
    assert d["forecast_value"] > d["last_value"]


def test_level_for_risk_index():
    assert m._level_for(METRIC_RISK, 70) == "高"
    assert m._level_for(METRIC_RISK, 45) == "中"
    assert m._level_for(METRIC_RISK, 10) == "低"


def test_level_for_health_score():
    assert m._level_for(METRIC_HEALTH, 50) == "差"
    assert m._level_for(METRIC_HEALTH, 65) == "中"
    assert m._level_for(METRIC_HEALTH, 80) == "良"
    assert m._level_for(METRIC_HEALTH, 95) == "优"


def test_forecast_by_model_unknown_falls_back():
    """未知模型版本回退到 PRIMARY_MODEL（ols_v1）。"""
    s = _series([10.0 + 4 * i for i in range(10)])
    d = m.forecast_by_model("does_not_exist", s, METRIC_RISK, 7)
    assert d is not None
    assert d["model_version"] == m.PRIMARY_MODEL == "ols_v1"


def test_resolve_default_model_reads_settings(monkeypatch):
    """默认模型版本从 settings.forecast_primary_model 动态解析；非法值回退 PRIMARY_MODEL。"""
    monkeypatch.setattr(settings, "forecast_primary_model", "hw_v1")
    assert svc._resolve_default_model() == "hw_v1"
    monkeypatch.setattr(settings, "forecast_primary_model", "not_a_model")
    assert svc._resolve_default_model() == svc.models.PRIMARY_MODEL
    monkeypatch.setattr(settings, "forecast_primary_model", "ols_v1")
    assert svc._resolve_default_model() == "ols_v1"


def _make_feat_series(n: int = 21, horizon: int = 7):
    """构造：HW 可捕捉的基线(水平+趋势+周季节) + 周期3的外部特征耦合项。

    周期3分量 HW(周期7) 吸收不掉 → 成为残差；hw_feat_v1 用外部特征(device_load=i%3)
    残差回归校正后应当还原这部分，从而与纯 HW 产生差异且更接近真值。
    """
    import math

    t0 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    base, feat = [], []
    for i in range(n):
        b = 50.0 + 0.2 * i + 3.0 * math.sin(2 * math.pi * i / 7.0)
        f = float(i % 3)
        base.append(b)
        feat.append(f)
    series = [(t0 + timedelta(days=i), base[i] + 50.0 * feat[i]) for i in range(n)]
    # 外部特征覆盖历史 + 未来 horizon 天
    external: dict[str, dict[str, float]] = {}
    for i in range(n + horizon):
        d = (t0 + timedelta(days=i)).date()
        external[d.isoformat()] = {"device_load": float(i % 3)}
    return series, external, horizon


def test_hw_feat_fallback_without_external():
    """无外部特征时 hw_feat_v1 退化为纯 HW（hw_v1 行为），model_version 仍标记自身。"""
    s = _series([10 + 2 * i + 3 * (i % 7) for i in range(21)])
    fused = m.forecast_holt_winters_feature(s, METRIC_RISK, 7)
    pure = m.forecast_holt_winters(s, METRIC_RISK, 7)
    assert fused is not None and pure is not None
    assert fused["model_version"] == "hw_feat_v1"
    assert fused["forecast_value"] == pure["forecast_value"]


def test_hw_feat_short_series_none():
    s = _series([1.0, 2.0])
    assert m.forecast_holt_winters_feature(s, METRIC_RISK, 7) is None


def test_hw_feat_fusion_consumes_external():
    """hw_feat_v1 应消费外部特征：融合预测与纯 HW 明显不同，且不变量（确定性）。"""
    series, external, horizon = _make_feat_series()
    fused = m.forecast_holt_winters_feature(
        series, METRIC_RISK, horizon, external_features=external
    )
    pure = m.forecast_holt_winters(series, METRIC_RISK, horizon)
    assert fused is not None and pure is not None
    assert fused["model_version"] == "hw_feat_v1"
    # 外部特征被实际消费：融合预测明显偏离纯 HW
    assert abs(fused["forecast_value"] - pure["forecast_value"]) > 10.0
    # 结果合法且确定性可复现
    assert 0.0 <= fused["forecast_value"] <= 100.0
    fused2 = m.forecast_holt_winters_feature(
        series, METRIC_RISK, horizon, external_features=external
    )
    assert fused2["forecast_value"] == fused["forecast_value"]
