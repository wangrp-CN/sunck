"""预测模型注册表（预测模型升级 + A/B 对照）。

在原有纯 OLS 线性外推（``ols_v1``）基础上，新增 **Holt-Winters 季节趋势模型**
（``hw_v1``，三重指数平滑：水平 + 趋势 + 周季节性）作为升级模型。两者均输出
与 ``Forecast`` 表字段一致的归一化字典（含 ``model_version``），便于统一落库、
回测与 A/B 对比。

设计要点：
- 纯 Python（不引 numpy/sklearn），小样本用解析/迭代解即可；
- 网格搜索（小参数集）按单步预测 SSE 选参，确定性、可复现；
- 序列 < 2 周时 HW 退化为 Holt 线性趋势（无季节性）；
- 预测值/置信带截断 [0,100]，级别分档复用 ``app.core.scoring`` 口径；
- 服务层不 commit，由调用方统一提交（项目 SOP）。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from app.core.scoring import RISK_LEVEL_HIGH, RISK_LEVEL_MID, device_health_level

METRIC_RISK_INDEX = "risk_index"
METRIC_HEALTH_SCORE = "health_score"

#: 95% 置信带 z 值
_Z95 = 1.96
#: 周季节性周期（天）
_WEEK = 7

#: 默认上线模型（保持 OLS 不变，HW 仅作 A/B 对照；可切 hw_v1 上线）
PRIMARY_MODEL = "ols_v1"

#: 参与 A/B 的模型集合（顺序即报表展示顺序；首=基线，末=挑战者）
AB_MODELS = ("ols_v1", "hw_v1", "hw_feat_v1")

#: 模型展示名（前端报表用）
MODEL_LABELS = {
    "ols_v1": "OLS 线性",
    "hw_v1": "Holt-Winters 季节趋势",
    "hw_feat_v1": "Holt-Winters + 特征融合",
}


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def _level_for(metric: str, value: float) -> str:
    """预测值按与实时口径一致的阈值分档（app.core.scoring）。"""
    if metric == METRIC_HEALTH_SCORE:
        return device_health_level(int(round(value)))
    if value >= RISK_LEVEL_HIGH:
        return "高"
    if value >= RISK_LEVEL_MID:
        return "中"
    return "低"


def _common(
    metric: str,
    horizon: int,
    series: list[tuple[datetime, float]],
    *,
    forecast_value: float,
    std: float,
    slope: float,
    intercept: float,
    model_version: str,
) -> dict[str, Any]:
    """组装与 Forecast 表字段一致的归一化字典。"""
    last_at, last_value = series[-1]
    raw = forecast_value
    fv = _clamp(raw)
    band = _Z95 * std
    return {
        "metric": metric,
        "horizon_days": horizon,
        "sample_count": len(series),
        "last_value": last_value,
        "slope": round(slope, 4),
        "intercept": round(intercept, 4),
        "forecast_value": round(fv, 2),
        "forecast_level": _level_for(metric, fv),
        "std_resid": round(std, 4),
        "forecast_lower": round(_clamp(raw - band), 2),
        "forecast_upper": round(_clamp(raw + band), 2),
        "forecast_at": last_at + timedelta(days=horizon),
        "computed_at": datetime.now(timezone.utc),
        "model_version": model_version,
    }


# ---------------------------------------------------------------------------
# ols_v1：原有最小二乘线性外推（保持行为不变）
# ---------------------------------------------------------------------------


def forecast_ols(
    series: list[tuple[datetime, float]],
    metric: str,
    horizon: int,
    model_version: str = "ols_v1",
    external_features: Any = None,
) -> dict | None:
    """最小二乘拟合 y = slope*x + intercept 并外推（x 以天为单位）。

    返回归一化字典；样本 < 2 返回 None（调用方跳过）。
    """
    n = len(series)
    if n < 2:
        return None
    t0 = series[0][0]
    xs = [((at - t0).total_seconds() / 86400.0) for at, _ in series]
    ys = [v for _, v in series]

    sx = sum(xs)
    sy = sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    denom = n * sxx - sx * sx
    slope = 0.0 if denom == 0 else (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n

    if n > 2:
        sse = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
        std = math.sqrt(sse / (n - 2))
    else:
        std = 0.0

    x_target = xs[-1] + horizon
    raw = slope * x_target + intercept
    return _common(
        metric,
        horizon,
        series,
        forecast_value=raw,
        std=std,
        slope=slope,
        intercept=intercept,
        model_version=model_version,
    )


# ---------------------------------------------------------------------------
# hw_v1：Holt-Winters 加法（水平 + 趋势 + 周季节性）
# ---------------------------------------------------------------------------


def _hw_train(y: list[float], m: int, alpha: float, beta: float, gamma: float):
    """单步训练：返回 (level, trend, seasonals, sse, cnt)。

    seasonals 为长度 m 的列表（周位置 0..m-1 的季节性因子，已中心化使和为 0）。
    """
    n = len(y)
    l0 = sum(y[:m]) / m
    b0 = (sum(y[m : 2 * m]) - sum(y[:m])) / m if n >= 2 * m else 0.0
    s_init = [y[i] - l0 for i in range(m)]
    s_mean = sum(s_init) / m
    seas = [v - s_mean for v in s_init]

    lev, trend = l0, b0
    sse = 0.0
    cnt = 0
    for i in range(m, n):
        si = i % m
        yhat = lev + trend + seas[si]
        err = y[i] - yhat
        sse += err * err
        cnt += 1
        new_seas = gamma * (y[i] - lev - trend) + (1 - gamma) * seas[si]
        new_lev = alpha * (y[i] - new_seas) + (1 - alpha) * (lev + trend)
        new_trend = beta * (new_lev - lev) + (1 - beta) * trend
        lev, trend, seas[si] = new_lev, new_trend, new_seas
    return lev, trend, seas, (math.sqrt(sse / cnt) if cnt > 0 else 0.0)


def _holt_train(y: list[float], alpha: float, beta: float):
    """Holt 双指数平滑（仅趋势，无季节性）。返回 (level, trend, std)。"""
    n = len(y)
    lev = y[0]
    trend = (y[1] - y[0]) if n >= 2 else 0.0
    sse = 0.0
    cnt = 0
    for i in range(1, n):
        yhat = lev + trend
        err = y[i] - yhat
        sse += err * err
        cnt += 1
        new_lev = alpha * y[i] + (1 - alpha) * (lev + trend)
        new_trend = beta * (new_lev - lev) + (1 - beta) * trend
        lev, trend = new_lev, new_trend
    return lev, trend, (math.sqrt(sse / cnt) if cnt > 0 else 0.0)


_HW_GRID = [(a, b, g) for a in (0.3, 0.5, 0.7) for b in (0.05, 0.1, 0.3) for g in (0.1, 0.3, 0.5)]
_HOLT_GRID = [(a, b) for a in (0.3, 0.5, 0.7) for b in (0.05, 0.1, 0.3)]


def forecast_holt_winters(
    series: list[tuple[datetime, float]],
    metric: str,
    horizon: int,
    model_version: str = "hw_v1",
    external_features: Any = None,
) -> dict | None:
    """Holt-Winters 加法模型（趋势 + 周季节性）。

    序列 < 3 返回 None；序列 < 2 周退化为 Holt 线性趋势；否则三重指数平滑。
    网格搜索选参（单步 SSE 最小），确定性可复现。
    """
    n = len(series)
    if n < 3:
        return None
    ys = [v for _, v in series]

    if n >= 2 * _WEEK:
        best = None
        for a, b, g in _HW_GRID:
            lev, trend, seas, std = _hw_train(ys, _WEEK, a, b, g)
            key = (std, a, b, g)
            if best is None or key < best[0]:
                best = (key, lev, trend, seas, std)
        _, lev, trend, seas, std = best
        # 未来第 h 步（1-based）对应日索引 n-1+h，季节位置 (n-1+h) % m
        h = horizon
        si = (n - 1 + h) % _WEEK
        raw = lev + h * trend + seas[si]
        return _common(
            metric,
            horizon,
            series,
            forecast_value=raw,
            std=std,
            slope=trend,
            intercept=lev,
            model_version=model_version,
        )

    # 退化：Holt 线性趋势
    best = None
    for a, b in _HOLT_GRID:
        lev, trend, std = _holt_train(ys, a, b)
        key = (std, a, b)
        if best is None or key < best[0]:
            best = (key, lev, trend, std)
    _, lev, trend, std = best
    raw = lev + horizon * trend
    return _common(
        metric,
        horizon,
        series,
        forecast_value=raw,
        std=std,
        slope=trend,
        intercept=lev,
        model_version=model_version,
    )


# ---------------------------------------------------------------------------
# hw_feat_v1：Holt-Winters 基线 + 外部/日历特征残差融合校正
# ---------------------------------------------------------------------------


def _design_row(d: date, ext: dict) -> list[float]:
    """设计向量：[1(截距), dow, month, is_weekend, temperature, rainfall,
    wind_speed, construction_intensity, device_load]；缺失外部特征补 0。"""
    return [
        1.0,
        float(d.weekday()),
        float(d.month),
        1.0 if d.weekday() >= 5 else 0.0,
        float(ext.get("temperature", 0.0)),
        float(ext.get("rainfall", 0.0)),
        float(ext.get("wind_speed", 0.0)),
        float(ext.get("construction_intensity", 0.0)),
        float(ext.get("device_load", 0.0)),
    ]


def _ridge_solve(xs: list[list[float]], y: list[float], lam: float = 1e-6) -> list[float]:
    """岭回归 (XᵀX + λI)β = Xᵀy 的纯 Python 解（高斯消元，确定性）。"""
    k = len(xs[0])
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for row, yi in zip(xs, y):
        for i in range(k):
            xty[i] += row[i] * yi
            for j in range(k):
                xtx[i][j] += row[i] * row[j]
    for i in range(k):
        xtx[i][i] += lam
    a = [row[:] + [xty[i]] for i, row in enumerate(xtx)]
    n = k
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(a[r][col]))
        a[col], a[piv] = a[piv], a[col]
        pv = a[col][col] or 1e-12
        for r in range(n):
            if r == col:
                continue
            f = a[r][col] / pv
            if f == 0.0:
                continue
            for c in range(col, n + 1):
                a[r][c] -= f * a[col][c]
    return [a[i][n] / (a[i][i] or 1e-12) for i in range(n)]


def _hw_fit(y: list[float], dates: list[date], m: int, alpha: float, beta: float, gamma: float):
    """HW 拟合（含逐点单步残差），返回 (level, trend, seas, std, resid)。"""
    n = len(y)
    l0 = sum(y[:m]) / m
    b0 = (sum(y[m : 2 * m]) - sum(y[:m])) / m if n >= 2 * m else 0.0
    s_init = [y[i] - l0 for i in range(m)]
    s_mean = sum(s_init) / m
    seas = [v - s_mean for v in s_init]
    lev, trend = l0, b0
    resid: list[tuple[date, float]] = []
    sse = 0.0
    cnt = 0
    for i in range(m, n):
        si = i % m
        err = y[i] - (lev + trend + seas[si])
        resid.append((dates[i], err))
        sse += err * err
        cnt += 1
        new_seas = gamma * (y[i] - lev - trend) + (1 - gamma) * seas[si]
        new_lev = alpha * (y[i] - new_seas) + (1 - alpha) * (lev + trend)
        new_trend = beta * (new_lev - lev) + (1 - beta) * trend
        lev, trend, seas[si] = new_lev, new_trend, new_seas
    std = math.sqrt(sse / cnt) if cnt > 0 else 0.0
    return lev, trend, seas, std, resid


def _holt_fit(y: list[float], dates: list[date], alpha: float, beta: float):
    """Holt 拟合（含逐点单步残差），返回 (level, trend, std, resid)。"""
    n = len(y)
    lev = y[0]
    trend = (y[1] - y[0]) if n >= 2 else 0.0
    resid: list[tuple[date, float]] = []
    sse = 0.0
    cnt = 0
    for i in range(1, n):
        err = y[i] - (lev + trend)
        resid.append((dates[i], err))
        sse += err * err
        cnt += 1
        new_lev = alpha * y[i] + (1 - alpha) * (lev + trend)
        new_trend = beta * (new_lev - lev) + (1 - beta) * trend
        lev, trend = new_lev, new_trend
    std = math.sqrt(sse / cnt) if cnt > 0 else 0.0
    return lev, trend, std, resid


def _has_external(ext: dict) -> bool:
    return any(any(v != 0.0 for v in d.values()) for d in ext.values())


def forecast_holt_winters_feature(
    series: list[tuple[datetime, float]],
    metric: str,
    horizon: int,
    *,
    external_features: dict | None = None,
    model_version: str = "hw_feat_v1",
) -> dict | None:
    """hw_feat_v1：HW 季节趋势基线 + 外部/日历特征残差融合校正。

    先用 Holt-Winters（<2 周退化为 Holt）给出基线预测与逐点单步残差，再用外部特征
    （气象/施工/设备负载）+ 日历特征对残差做岭回归校正，对未来各步叠加校正量。
    外部特征缺失时优雅退化为纯 HW（行为与 hw_v1 一致），保证鲁棒且 A/B 口径无脏数据。

    返回归一化字典（model_version=hw_feat_v1）；样本 <3 返回 None。
    """
    n = len(series)
    if n < 3:
        return None
    external_features = external_features or {}
    if not _has_external(external_features) or len(series) < 2 * _WEEK:
        # 无外部特征或样本不足两周：退化为纯 HW（hw_v1 行为），保持可回归
        return forecast_holt_winters(series, metric, horizon, model_version=model_version)

    dates = [at.date() for at, _ in series]
    ys = [v for _, v in series]

    # 1) 选 HW/Holt 最佳参数并取基线状态 + 残差
    if n >= 2 * _WEEK:
        best = None
        for a, b, g in _HW_GRID:
            fit = _hw_fit(ys, dates, _WEEK, a, b, g)
            key = (fit[3], a, b, g)
            if best is None or key < best[0]:
                best = (key, fit)
        lev, trend, seas, hw_std, resid = best[1]
        use_seasonal = True
    else:
        best = None
        for a, b in _HOLT_GRID:
            fit = _holt_fit(ys, dates, a, b)
            key = (fit[2], a, b)
            if best is None or key < best[0]:
                best = (key, fit)
        lev, trend, hw_std, resid = best[1]
        seas = None
        use_seasonal = False

    if len(resid) < 5:
        # 残差点过少，校正不可靠：退化为纯 HW
        return forecast_holt_winters(series, metric, horizon, model_version=model_version)

    # 2) 残差回归（外部特征 + 日历）
    rd = [d for d, _ in resid]
    rv = [e for _, e in resid]
    X = [_design_row(d, external_features.get(d.isoformat(), {})) for d in rd]
    beta = _ridge_solve(X, rv)
    fitted = [sum(b * x for b, x in zip(beta, row)) for row in X]
    sse = sum((e - f) ** 2 for e, f in zip(rv, fitted))
    resid_std = math.sqrt(sse / max(1, len(rv) - len(beta)))

    # 3) 逐期预测：基线 + 校正
    raw = None
    for h in range(1, horizon + 1):
        fd = dates[-1] + timedelta(days=h)
        baseline = lev + h * trend + (seas[(n - 1 + h) % _WEEK] if use_seasonal else 0.0)
        ext_h = external_features.get(fd.isoformat(), {})
        corr = sum(b * v for b, v in zip(beta, _design_row(fd, ext_h)))
        raw = baseline + corr
    if raw is None:
        return None

    std_total = math.sqrt(hw_std**2 + resid_std**2)
    return _common(
        metric,
        horizon,
        series,
        forecast_value=raw,
        std=std_total,
        slope=trend,
        intercept=lev,
        model_version=model_version,
    )


# ---------------------------------------------------------------------------
# 模型注册表与调度
# ---------------------------------------------------------------------------


MODELS: dict[str, Callable[..., dict | None]] = {
    "ols_v1": forecast_ols,
    "hw_v1": forecast_holt_winters,
    "hw_feat_v1": forecast_holt_winters_feature,
}


def forecast_by_model(
    model_version: str,
    series: list[tuple[datetime, float]],
    metric: str,
    horizon: int,
    *,
    external_features: dict | None = None,
) -> dict | None:
    """按 model_version 调度对应模型；未知版本回退到 PRIMARY_MODEL。

    回退时把实际使用的版本（PRIMARY_MODEL）写回结果，避免把不存在的版本号落库，
    保证 ``model_version`` 列与注册表一致、A/B 聚合口径无脏数据。
    """
    fn = MODELS.get(model_version)
    if fn is None:
        fn = MODELS[PRIMARY_MODEL]
        model_version = PRIMARY_MODEL
    return fn(
        series,
        metric,
        horizon,
        model_version=model_version,
        external_features=external_features,
    )
