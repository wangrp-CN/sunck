"""核心智能评分算法（设备健康分 / 项目风险分）。

把原本散落在端点里的「二值/线性启发式」集中为**纯函数 + 可调权重**，便于算法与
运维同学调参，且全部无 DB 依赖、可单测。两端点旧实现的主要问题：

- 设备健康分：``60在线/20上报/20无告警`` 全二值，无严重度区分、无在线梯度、
  不区分告警级别；
- 项目风险分：``未处理*2 + 超期*3 + 存量`` 线性无归一化，大项目恒高风险、
  且 ``handle_status=='未处理'`` 与模型实际值（待处理/已处理/已忽略/已确认）不符，
  导致未处理项永远为 0。

本模块提供：

- :func:`device_health_score` —— 在线新鲜度梯度 + 上报活跃度 + 按告警级别的严重度惩罚；
- :func:`device_health_level` —— 健康分档（优/良/中/差）；
- :func:`project_risk_score` —— 未处理告警按级别加权 + 超期/存量隐患加权，并归一化为
  0-100 风险指数（跨项目公平对比）+ 风险分档（高/中/低）。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 严重度权重（相对值，越大越严重）
# ---------------------------------------------------------------------------
#: 告警级别 → 严重度权重（与 ``app.core.constants.ALARM_LEVEL_TO_HAZARD_LEVEL`` 对齐）
ALARM_SEVERITY_WEIGHT: dict[str, float] = {"严重": 3.0, "警告": 2.0, "提示": 1.0}
#: 隐患等级 → 权重（用于超期隐患加权）
HAZARD_LEVEL_WEIGHT: dict[str, float] = {"重大": 3.0, "较大": 2.0, "一般": 1.0, "低": 0.5}

# ---------------------------------------------------------------------------
# 设备健康分权重（0-100）
# ---------------------------------------------------------------------------
HEALTH_ONLINE_FRESH = 70  # 在线且最近上报在阈值内
HEALTH_ONLINE_STALE = 35  # 在线但上报陈旧（阈值 < age <= 2*阈值）
HEALTH_OFFLINE = 0  # 离线 / 长期无上报
HEALTH_REPORT_BONUS = 30  # 窗口内有上报记录
HEALTH_ALARM_PENALTY_CAP = 40  # 告警惩罚上限（避免单次极端把分拉满到 0）

# 设备健康分档阈值（0-100）
HEALTH_LEVEL_GOOD = 90  # 优
HEALTH_LEVEL_FAIR = 75  # 良
HEALTH_LEVEL_MID = 60  # 中
# < HEALTH_LEVEL_MID → 差

# ---------------------------------------------------------------------------
# 项目风险分权重
# ---------------------------------------------------------------------------
RISK_UNHANDLED_MULT = 2.0  # 未处理告警（已按级别加权后）的总乘子
RISK_OVERDUE_HAZARD = 3.0  # 每条超期隐患的乘子基数（再乘隐患等级权重）
RISK_OPEN_HAZARD = 1.0  # 每条存量（未销号）隐患
RISK_NORMALIZE_K = 20.0  # 归一化饱和常数：risk_index = 100*raw/(raw+K)

# 项目风险指数分档（0-100）
RISK_LEVEL_HIGH = 60  # 高
RISK_LEVEL_MID = 30  # 中
# < RISK_LEVEL_MID → 低


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def device_health_score(
    *,
    online_state: str,
    reported: bool,
    alarm_severity_counts: dict[str, int] | None = None,
) -> int:
    """计算单设备健康分（0-100）。

    :param online_state: ``"fresh"`` 在线且上报新鲜 / ``"stale"`` 在线但陈旧 /
        ``"offline"`` 离线或无上报。
    :param reported: 窗口内是否有上报记录（活跃度奖励）。
    :param alarm_severity_counts: ``{级别: 条数}``，按级别施加严重度惩罚。
    """
    base = {
        "fresh": HEALTH_ONLINE_FRESH,
        "stale": HEALTH_ONLINE_STALE,
        "offline": HEALTH_OFFLINE,
    }.get(online_state, HEALTH_OFFLINE)
    bonus = HEALTH_REPORT_BONUS if reported else 0
    sev = alarm_severity_counts or {}
    penalty = sum(cnt * ALARM_SEVERITY_WEIGHT.get(level, 1.0) for level, cnt in sev.items())
    penalty = min(penalty, HEALTH_ALARM_PENALTY_CAP)
    return int(_clamp(base + bonus - penalty))


def device_health_level(score: int) -> str:
    """健康分 → 等级（优/良/中/差）。"""
    if score >= HEALTH_LEVEL_GOOD:
        return "优"
    if score >= HEALTH_LEVEL_FAIR:
        return "良"
    if score >= HEALTH_LEVEL_MID:
        return "中"
    return "差"


def project_risk_score(
    *,
    unhandled_by_level: dict[str, int] | None = None,
    overdue_by_level: dict[str, int] | None = None,
    open_hazards: int = 0,
) -> tuple[int, int, str]:
    """计算项目风险。

    :returns: ``(raw_risk, risk_index_0_100, risk_level)``。

    - ``raw_risk`` 为透明整数：未处理告警按级别加权 + 超期隐患（按等级加权）+ 存量隐患；
    - ``risk_index`` 经饱和函数归一化到 0-100，便于跨项目公平对比；
    - ``risk_level`` ∈ {高, 中, 低}。
    """
    unhandled = unhandled_by_level or {}
    unhandled_weighted = sum(
        cnt * ALARM_SEVERITY_WEIGHT.get(level, 1.0) for level, cnt in unhandled.items()
    )
    overdue = overdue_by_level or {}
    overdue_weighted = sum(
        cnt * HAZARD_LEVEL_WEIGHT.get(level, 1.0) for level, cnt in overdue.items()
    )
    raw = int(
        unhandled_weighted * RISK_UNHANDLED_MULT
        + overdue_weighted * RISK_OVERDUE_HAZARD
        + open_hazards * RISK_OPEN_HAZARD
    )
    risk_index = int(round(_clamp(100.0 * raw / (raw + RISK_NORMALIZE_K))))
    if risk_index >= RISK_LEVEL_HIGH:
        level = "高"
    elif risk_index >= RISK_LEVEL_MID:
        level = "中"
    else:
        level = "低"
    return raw, risk_index, level
