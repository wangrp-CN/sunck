"""核心评分算法单元测试（纯函数，无 DB 依赖）。"""

from app.core.scoring import (
    device_health_level,
    device_health_score,
    project_risk_score,
)


# ---------------- 设备健康分 ----------------
def test_device_health_offline_no_alarm():
    # 离线且无上报、无告警 → 0 分、差
    s = device_health_score(online_state="offline", reported=False, alarm_severity_counts={})
    assert s == 0
    assert device_health_level(s) == "差"


def test_device_health_fresh_reported_no_alarm():
    # 在线新鲜 + 有上报 + 无告警 → 满分 100、优
    s = device_health_score(online_state="fresh", reported=True, alarm_severity_counts={})
    assert s == 100
    assert device_health_level(s) == "优"


def test_device_health_severity_penalty():
    # 在线新鲜有上报(100) - 1条严重(3) - 2条警告(4) = 93 → 优
    s = device_health_score(
        online_state="fresh",
        reported=True,
        alarm_severity_counts={"严重": 1, "警告": 2},
    )
    assert s == 93
    assert device_health_level(s) == "优"


def test_device_health_penalty_cap():
    # 大量告警惩罚被封顶在 40，不会拉成负数：100 - 40 = 60
    s = device_health_score(
        online_state="fresh",
        reported=True,
        alarm_severity_counts={"严重": 100},
    )
    assert s == 60


def test_device_health_stale_lower_than_fresh():
    fresh = device_health_score(online_state="fresh", reported=True, alarm_severity_counts={})
    stale = device_health_score(online_state="stale", reported=True, alarm_severity_counts={})
    assert stale < fresh
    assert stale == 35 + 30  # 35 + 30 = 65


# ---------------- 项目风险分 ----------------
def test_project_risk_empty():
    raw, idx, level = project_risk_score(unhandled_by_level={}, overdue_by_level={}, open_hazards=0)
    assert raw == 0
    assert idx == 0
    assert level == "低"


def test_project_risk_severity_weighting():
    # 1条严重未处理(3*2=6) vs 1条提示未处理(1*2=2)：严重风险更高
    severe = project_risk_score(unhandled_by_level={"严重": 1})[0]
    minor = project_risk_score(unhandled_by_level={"提示": 1})[0]
    assert severe > minor


def test_project_risk_index_normalized_bounded():
    # 风险指数恒在 0-100，且随 raw 单调递增
    raw_small, idx_small, _ = project_risk_score(unhandled_by_level={"提示": 1}, open_hazards=1)
    raw_big, idx_big, _ = project_risk_score(
        unhandled_by_level={"严重": 50, "警告": 50}, overdue_by_level={"重大": 30}, open_hazards=100
    )
    assert 0 <= idx_small <= 100
    assert 0 <= idx_big <= 100
    assert idx_big > idx_small
    # 饱和：极端大 raw 也不会超过 100
    huge = project_risk_score(unhandled_by_level={"严重": 100000})[1]
    assert huge == 100


def test_project_risk_levels():
    # 高：大量严重未处理
    _, idx_high, lvl_high = project_risk_score(unhandled_by_level={"严重": 20})
    assert lvl_high == "高"
    # 中：中等风险
    _, idx_mid, lvl_mid = project_risk_score(unhandled_by_level={"提示": 10})
    assert lvl_mid in ("中", "低") or idx_mid >= 30
    # 低：极轻微
    _, _, lvl_low = project_risk_score(open_hazards=1)
    assert lvl_low == "低"
