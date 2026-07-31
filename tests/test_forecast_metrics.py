"""预测指标注册表单测（预测可解释化 + 多指标解耦）。

纯单测，无需数据库：验证 metric 注册、分档、越阈判据、预防式区间越阈判据的口径统一。
"""

from app.service import forecast_metrics as fm


def test_metrics_for_scope():
    assert [m.key for m in fm.metrics_for_scope("project")] == ["risk_index"]
    assert [m.key for m in fm.metrics_for_scope("device")] == ["health_score"]
    # 注册表默认仅两指标
    assert {m.key for m in fm.all_metrics()} == {"risk_index", "health_score"}


def test_metric_column_resolves_snapshot_attr():
    # metric_column 必须返回 RiskHealthSnapshot 的 SQLAlchemy 列对象
    col = fm.metric_column("risk_index")
    assert col.name == "risk_index"
    col2 = fm.metric_column("health_score")
    assert col2.name == "health_score"


def test_level_for_risk_low_good():
    assert fm.level_for("risk_index", 65) == "高"
    assert fm.level_for("risk_index", 35) == "中"
    assert fm.level_for("risk_index", 10) == "低"


def test_level_for_health_high_good():
    assert fm.level_for("health_score", 95) == "优"
    assert fm.level_for("health_score", 80) == "良"
    assert fm.level_for("health_score", 65) == "中"
    assert fm.level_for("health_score", 50) == "差"


def test_breach_for_point_threshold():
    # risk_index：仅「高」触发，级别警告
    assert fm.breach_for("risk_index", 70, "高") == (True, "警告")
    assert fm.breach_for("risk_index", 70, "中") == (False, None)
    # health_score：中→警告，差→严重
    assert fm.breach_for("health_score", 65, "中") == (True, "警告")
    assert fm.breach_for("health_score", 50, "差") == (True, "严重")
    assert fm.breach_for("health_score", 95, "优") == (False, None)
    # 未知指标不触发
    assert fm.breach_for("unknown_metric", 99, "高") == (False, None)


def test_preventive_breach_interval_low_good():
    # risk_index（low_good）：上界越过阈值(60)即预警
    assert fm.preventive_breach("risk_index", 40.0, 65.0) == (True, "警告")
    assert fm.preventive_breach("risk_index", 40.0, 50.0) == (False, None)


def test_preventive_breach_interval_high_good():
    # health_score（high_good）：下界越过阈值(60)即预警
    assert fm.preventive_breach("health_score", 55.0, 90.0) == (True, "严重")
    assert fm.preventive_breach("health_score", 70.0, 90.0) == (False, None)


def test_explain_contributions_runs():
    # 解释函数对贡献列表稳定产出中文串（具体措辞随方向变化，至少非空）
    contribs = [
        {"feature": "rainfall", "label": "降雨", "impact": 3.2},
        {"feature": "construction_intensity", "label": "施工强度", "impact": -1.1},
    ]
    risk_txt = fm  # 仅占位，避免未用导入告警
    assert risk_txt is not None
    from app.service.forecast_service import _explain_contributions

    risk_expl = _explain_contributions("risk_index", contribs)
    assert isinstance(risk_expl, str) and len(risk_expl) > 0
    health_expl = _explain_contributions("health_score", contribs)
    assert isinstance(health_expl, str) and len(health_expl) > 0
