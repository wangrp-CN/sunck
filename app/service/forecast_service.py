"""风险预测服务（Phase 5 智能化预测 M1 预测基座 + M2 增强 + M3 预测性预警回灌）。

对 ``RiskHealthSnapshot`` 时序做**纯 Python OLS（最小二乘）线性趋势外推**：

- M1：项目 ``risk_index`` 日序列 → 未来 N 天风险指数预测，upsert 落 ``forecast`` 表；
- M2：新增设备 ``health_score`` 多指标预测、残差 95% 置信带
  （``forecast_lower/upper``）、以及供前端画图的序列预览（历史点+预测点+置信带）；
- M3：越阈预测自动回灌 ``predictive_alert`` 告警（``run_predictive_alerts``），
  复用既有告警流（站内信通知 + 告警管理页一键派单闭环），幂等不重复派警。

设计要点：
- 无第三方依赖（不引 numpy/sklearn），样本量小（≤ 数十点）用解析解即可；
- 每个 (scope_type, ref_id, metric, horizon_days) 只保留最新一条预测；
- 预测值/置信带截断到 [0, 100]；risk_index 按 scoring 风险阈值分档（高/中/低），
  health_score 按健康阈值分档（优/良/中/差）；
- 序列点数 < ``settings.forecast_min_points`` 时不出预测（防 1~2 点直线误导）；
- ``run_forecasts`` 对快照做**单查批量加载**（按 ref_id 分组），避免逐设备 N+1。

服务内不 commit，由端点或 job 统一提交（项目 SOP）。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.constants import ALARM_TYPE_FORECAST
from app.core.scoring import RISK_LEVEL_HIGH, RISK_LEVEL_MID, device_health_level
from app.model.alarm import Alarm
from app.model.device import AntiIntrusionDevice, LocateDevice, TrainApproachDevice
from app.model.forecast import Forecast
from app.model.project import Project
from app.model.snapshot import RiskHealthSnapshot
from app.service import forecast_models as models

METRIC_RISK_INDEX = "risk_index"
METRIC_HEALTH_SCORE = "health_score"

#: 默认上线模型（保持 OLS 不变；hw_v1 仅作 A/B 对照，可通过 recompute?model=hw_v1 切换）
DEFAULT_MODEL = models.PRIMARY_MODEL

#: 指标 → 快照取值列
_METRIC_COLUMNS = {
    METRIC_RISK_INDEX: RiskHealthSnapshot.risk_index,
    METRIC_HEALTH_SCORE: RiskHealthSnapshot.health_score,
}

_DEVICE_MODELS = [AntiIntrusionDevice, LocateDevice, TrainApproachDevice]

#: 95% 置信带 z 值
_Z95 = 1.96


def _risk_level(value: float) -> str:
    """预测值按与实时口径一致的阈值分档（app.core.scoring）。"""
    if value >= RISK_LEVEL_HIGH:
        return "高"
    if value >= RISK_LEVEL_MID:
        return "中"
    return "低"


def _level_for(metric: str, value: float) -> str:
    if metric == METRIC_HEALTH_SCORE:
        return device_health_level(int(round(value)))
    return _risk_level(value)


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def _ols(points: list[tuple[float, float]]) -> tuple[float, float]:
    """最小二乘拟合 y = slope*x + intercept，返回 (slope, intercept)。

    调用方保证 len(points) >= 2；x 全相等（同刻多点）时斜率视为 0。
    """
    n = float(len(points))
    sx = sum(p[0] for p in points)
    sy = sum(p[1] for p in points)
    sxx = sum(p[0] * p[0] for p in points)
    sxy = sum(p[0] * p[1] for p in points)
    denom = n * sxx - sx * sx
    if denom == 0:
        return 0.0, sy / n
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


def _fit_and_forecast(
    series: list[tuple[datetime, float]],
    metric: str,
    horizon: int,
    model_version: str = DEFAULT_MODEL,
) -> dict | None:
    """对时序按指定模型拟合并外推，返回公共字段字典（含 model_version，不含归属信息）。

    模型调度见 :mod:`app.service.forecast_models`（ols_v1 / hw_v1）。样本不足时
    返回 None（由调用方跳过落库）。
    """
    return models.forecast_by_model(model_version, series, metric, horizon)


# ---------------------------------------------------------------------------
# 序列加载
# ---------------------------------------------------------------------------


def _load_series(
    db: Session, scope_type: str, ref_id: str, metric: str, days: int
) -> list[tuple[datetime, float]]:
    """单个对象的快照序列（旧→新），保留 datetime 供换算天数。"""
    col = _METRIC_COLUMNS[metric]
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(RiskHealthSnapshot.snapshot_at, col)
        .where(
            RiskHealthSnapshot.scope_type == scope_type,
            RiskHealthSnapshot.ref_id == ref_id,
            RiskHealthSnapshot.snapshot_at >= since,
            col.is_not(None),
        )
        .order_by(RiskHealthSnapshot.snapshot_at.asc())
    ).all()
    return [(_as_utc(at), float(val)) for at, val in rows]


def _load_series_bulk(
    db: Session, scope_type: str, metric: str, days: int
) -> dict[str, list[tuple[datetime, float]]]:
    """按 ref_id 分组批量加载某类快照序列（单查，防 N+1）。"""
    col = _METRIC_COLUMNS[metric]
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(RiskHealthSnapshot.ref_id, RiskHealthSnapshot.snapshot_at, col)
        .where(
            RiskHealthSnapshot.scope_type == scope_type,
            RiskHealthSnapshot.snapshot_at >= since,
            col.is_not(None),
        )
        .order_by(RiskHealthSnapshot.snapshot_at.asc())
    ).all()
    out: dict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for ref_id, at, val in rows:
        out[ref_id].append((_as_utc(at), float(val)))
    return out


def _as_utc(at: datetime) -> datetime:
    return at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at


# ---------------------------------------------------------------------------
# 计算入口
# ---------------------------------------------------------------------------


def compute_forecast(
    db: Session,
    project_id: int,
    *,
    horizon_days: int | None = None,
    history_days: int | None = None,
    model_version: str = DEFAULT_MODEL,
) -> dict | None:
    """单个项目的 risk_index 预测；样本不足返回 None（不落库）。"""
    horizon = horizon_days or settings.forecast_horizon_days
    history = history_days or settings.forecast_history_days
    series = _load_series(db, "project", str(project_id), METRIC_RISK_INDEX, days=history)
    if len(series) < settings.forecast_min_points:
        return None
    data = _fit_and_forecast(series, METRIC_RISK_INDEX, horizon, model_version=model_version)
    if data is None:
        return None
    data.update(project_id=project_id, scope_type="project", ref_id=str(project_id))
    return data


def compute_device_forecast(
    db: Session,
    device_no: str,
    *,
    horizon_days: int | None = None,
    history_days: int | None = None,
    model_version: str = DEFAULT_MODEL,
) -> dict | None:
    """单个设备的 health_score 预测（M2）；样本不足返回 None。"""
    horizon = horizon_days or settings.forecast_horizon_days
    history = history_days or settings.forecast_history_days
    series = _load_series(db, "device", device_no, METRIC_HEALTH_SCORE, days=history)
    if len(series) < settings.forecast_min_points:
        return None
    data = _fit_and_forecast(series, METRIC_HEALTH_SCORE, horizon, model_version=model_version)
    if data is None:
        return None
    data.update(project_id=_device_project_id(db, device_no), scope_type="device", ref_id=device_no)
    return data


def _device_project_id(db: Session, device_no: str) -> int | None:
    for m in _DEVICE_MODELS:
        pid = db.scalars(select(m.project_id).where(m.device_no == device_no)).first()
        if pid is not None:
            return pid
    return None


def preview_forecast(
    db: Session,
    scope_type: str,
    ref_id: str,
    *,
    horizon_days: int | None = None,
    history_days: int | None = None,
    model_version: str = DEFAULT_MODEL,
) -> dict | None:
    """序列预览（M2，供前端画图）：历史点 + 拟合参数 + 预测点 + 置信带。

    样本不足时仍返回历史序列（forecast 为 None），前端可提示"数据积累中"。
    """
    horizon = horizon_days or settings.forecast_horizon_days
    history = history_days or settings.forecast_history_days
    metric = METRIC_RISK_INDEX if scope_type == "project" else METRIC_HEALTH_SCORE
    series = _load_series(db, scope_type, ref_id, metric, days=history)
    out: dict = {
        "scope_type": scope_type,
        "ref_id": ref_id,
        "metric": metric,
        "horizon_days": horizon,
        "series": [{"at": at.isoformat(), "value": val} for at, val in series],
        "forecast": None,
    }
    if len(series) >= settings.forecast_min_points:
        fit = _fit_and_forecast(series, metric, horizon, model_version=model_version)
        if fit is not None:
            fit["forecast_at"] = fit["forecast_at"].isoformat()
            fit["computed_at"] = fit["computed_at"].isoformat()
            out["forecast"] = fit
    return out


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------


def upsert_forecast(db: Session, data: dict, name: str | None = None) -> Forecast:
    """按唯一键 (scope_type, ref_id, metric, horizon_days) upsert。"""
    obj = db.scalars(
        select(Forecast).where(
            Forecast.scope_type == data["scope_type"],
            Forecast.ref_id == data["ref_id"],
            Forecast.metric == data["metric"],
            Forecast.horizon_days == data["horizon_days"],
        )
    ).first()
    if obj is None:
        obj = Forecast(**data, name=name)
        db.add(obj)
    else:
        for k, v in data.items():
            setattr(obj, k, v)
        if name is not None:
            obj.name = name
    db.flush()
    return obj


def run_forecasts(
    db: Session, horizon_days: int | None = None, model_version: str = DEFAULT_MODEL
) -> dict:
    """全量预测（项目 risk_index + 设备 health_score），批量加载防 N+1。

    不 commit，由调用方提交。返回 {computed, skipped, projects, devices}。
    """
    horizon = horizon_days or settings.forecast_horizon_days
    history = settings.forecast_history_days
    min_pts = settings.forecast_min_points
    computed = skipped = 0

    # 项目 risk_index
    proj_series = _load_series_bulk(db, "project", METRIC_RISK_INDEX, days=history)
    projects = db.execute(
        select(Project.id, Project.name).where(Project.is_deleted.is_(False))
    ).all()
    for pid, pname in projects:
        series = proj_series.get(str(pid), [])
        if len(series) < min_pts:
            skipped += 1
            continue
        data = _fit_and_forecast(series, METRIC_RISK_INDEX, horizon, model_version=model_version)
        if data is None:
            skipped += 1
            continue
        data.update(project_id=pid, scope_type="project", ref_id=str(pid))
        upsert_forecast(db, data, name=pname)
        computed += 1

    # 设备 health_score（M2）
    dev_series = _load_series_bulk(db, "device", METRIC_HEALTH_SCORE, days=history)
    devices: list[tuple[str, str, int | None]] = []
    for m in _DEVICE_MODELS:
        devices.extend(
            db.execute(
                select(m.device_no, m.name, m.project_id).where(m.is_deleted.is_(False))
            ).all()
        )
    for dno, dname, dpid in devices:
        series = dev_series.get(dno, [])
        if len(series) < min_pts:
            skipped += 1
            continue
        data = _fit_and_forecast(series, METRIC_HEALTH_SCORE, horizon, model_version=model_version)
        if data is None:
            skipped += 1
            continue
        data.update(project_id=dpid, scope_type="device", ref_id=dno)
        upsert_forecast(db, data, name=dname)
        computed += 1

    return {
        "computed": computed,
        "skipped": skipped,
        "projects": len(projects),
        "devices": len(devices),
    }


# ---------------------------------------------------------------------------
# M3：预测性预警回灌告警流
# ---------------------------------------------------------------------------


#: 越阈判据 → 告警级别。risk_index 仅「高」触发；health_score「中」→警告、「差」→严重。
def _breach_for(
    metric: str, forecast_value: float, forecast_level: str | None
) -> tuple[bool, str | None]:
    """纯函数版越阈判据：给定指标/预测值/级别，返回 (是否触发预警, 告警级别)。

    - risk_index：预测级别「高」（forecast_value >= RISK_LEVEL_HIGH=60）触发，级别「警告」；
    - health_score：预测级别「中」→「警告」、「差」→「严重」；优/良不触发。
    """
    if metric == METRIC_RISK_INDEX:
        if forecast_level == "高":
            return True, "警告"
        return False, None
    if metric == METRIC_HEALTH_SCORE:
        if forecast_level == "差":
            return True, "严重"
        if forecast_level == "中":
            return True, "警告"
        return False, None
    return False, None


def _predictive_breach(fc: Forecast) -> tuple[bool, str | None]:
    """判断预测是否越阈，并返回应生成的告警级别（封装 :func:`_breach_for`）。"""
    return _breach_for(fc.metric, fc.forecast_value, fc.forecast_level)


def run_predictive_alerts(db: Session) -> dict[str, Any]:
    """预测性预警回灌（M3）：遍历 forecast 表，对越阈预测生成 ``predictive_alert`` 告警。

    越阈判据见 :func:`_predictive_breach`。幂等：以
    ``device_no = predictive:{metric}:{ref_id}:{horizon_days}`` 编码唯一键，
    同键已存在告警则跳过（与 ``trend_anomaly`` 同范式，跨日定时运行不重复派警）。

    复用既有告警流：``alarm_service.create_alarm`` 落库 + 站内信通知 +
    告警管理页「一键派单」接入根因派单闭环。

    不 commit，由 ``scripts/snapshot_job.py`` 统一提交。返回 ``{"created", "alarm_ids"}``。
    """
    from app.service import alarm_service

    rows = db.scalars(select(Forecast)).all()
    created_ids: list[int] = []
    for fc in rows:
        if fc.forecast_value is None or fc.forecast_level is None:
            continue
        breach, level = _predictive_breach(fc)
        if not breach:
            continue
        device_no = f"predictive:{fc.metric}:{fc.ref_id}:{fc.horizon_days}"
        # 幂等：同 device_no 已存在告警则跳过（跨 Redis-TTL 仍生效）
        existing = db.scalar(select(Alarm.id).where(Alarm.device_no == device_no).limit(1))
        if existing is not None:
            continue
        horizon = fc.horizon_days
        lower = fc.forecast_lower if fc.forecast_lower is not None else fc.forecast_value
        upper = fc.forecast_upper if fc.forecast_upper is not None else fc.forecast_value
        fa_str = fc.forecast_at.strftime("%Y-%m-%d") if fc.forecast_at else "—"
        if fc.metric == METRIC_RISK_INDEX:
            info = (
                f"风险预测预警：项目《{fc.name}》预测 {horizon} 天后风险指数将升至 "
                f"{fc.forecast_value:.0f}（高，当前 {fc.last_value:.0f}），"
                f"95% 置信区间 [{lower:.0f}, {upper:.0f}]，预计 {fa_str} 触及。"
            )
        else:
            info = (
                f"健康预测预警：设备《{fc.name}》预测 {horizon} 天后健康分将降至 "
                f"{fc.forecast_value:.0f}（{fc.forecast_level}，当前 {fc.last_value:.0f}），"
                f"95% 置信区间 [{lower:.0f}, {upper:.0f}]，预计 {fa_str} 触及。"
            )
        alarm = alarm_service.create_alarm(
            db,
            project_id=fc.project_id,
            alarm_type=ALARM_TYPE_FORECAST,
            device_no=device_no,
            device_name=fc.name,
            alarm_info=info,
            alarm_level=level,
            alarm_time=fc.computed_at,
            handle_status="待处理",
        )
        if alarm is not None:
            created_ids.append(alarm.id)
    return {"created": len(created_ids), "alarm_ids": created_ids}
