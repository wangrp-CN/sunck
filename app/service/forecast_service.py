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
from app.model.alarm import Alarm
from app.model.device import AntiIntrusionDevice, LocateDevice, TrainApproachDevice
from app.model.forecast import Forecast
from app.model.project import Project
from app.model.snapshot import RiskHealthSnapshot
from app.service import feature_provider as feat_svc
from app.service import forecast_metrics as fm
from app.service import forecast_models as models

METRIC_RISK_INDEX = "risk_index"
METRIC_HEALTH_SCORE = "health_score"

#: 默认上线模型版本（可在 settings.forecast_primary_model 中配置，支持运行时一键切换）。
#: 此处保留 PRIMARY_MODEL 作为解析失败的兜底；真正生效值由 _resolve_default_model() 运行时读取。
DEFAULT_MODEL = models.PRIMARY_MODEL


def _resolve_default_model() -> str:
    """读取当前上线默认模型版本；若配置值不在注册表中则回退到 PRIMARY_MODEL。

    运行时经 ``POST /v1/forecasts/model/default`` 修改 ``settings.forecast_primary_model``
    后，本函数立即反映新值，使默认预测/回测/重算均切换到新模型。
    """
    mv = getattr(settings, "forecast_primary_model", models.PRIMARY_MODEL)
    return mv if mv in models.MODELS else models.PRIMARY_MODEL


_DEVICE_MODELS = [AntiIntrusionDevice, LocateDevice, TrainApproachDevice]

#: 95% 置信带 z 值
_Z95 = 1.96


def _level_for(metric: str, value: float) -> str:
    """预测值分档委托指标注册表（口径统一，支持多指标）。"""
    return fm.level_for(metric, value)


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
    model_version: str | None = None,
    *,
    external_features: dict | None = None,
) -> dict | None:
    """对时序按指定模型拟合并外推，返回公共字段字典（含 model_version，不含归属信息）。

    模型调度见 :mod:`app.service.forecast_models`（ols_v1 / hw_v1 / hw_feat_v1）。
    ``external_features`` 为 {日期iso: {特征名: 值}}；hw_feat_v1 据此做残差融合校正，
    缺失时退化为纯 HW。样本不足时返回 None（由调用方跳过落库）。
    """
    model_version = model_version or _resolve_default_model()
    return models.forecast_by_model(
        model_version,
        series,
        metric,
        horizon,
        external_features=external_features,
    )


# ---------------------------------------------------------------------------
# 序列加载
# ---------------------------------------------------------------------------


def _load_series(
    db: Session, scope_type: str, ref_id: str, metric: str, days: int
) -> list[tuple[datetime, float]]:
    """单个对象的快照序列（旧→新），保留 datetime 供换算天数。"""
    col = fm.metric_column(metric)
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
    col = fm.metric_column(metric)
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


def _resolve_project_id(db: Session, scope_type: str, ref_id: str) -> int | None:
    """由 (scope_type, ref_id) 解析 project_id（外部特征按项目维度关联）。"""
    if scope_type == "project":
        try:
            return int(ref_id)
        except (TypeError, ValueError):
            return None
    return _device_project_id(db, ref_id)


def _load_external_features(
    db: Session, scope_type: str, ref_id: str, days: int | None = None
) -> dict:
    """加载 (scope, ref_id) 的外部特征（按 project_id 关联），覆盖历史 + 未来 horizon 天。

    返回 {日期iso: {特征名: 值}}；无项目或无特征时返回空 dict（hw_feat_v1 将退化为纯 HW）。
    """
    days = days or settings.forecast_history_days
    pid = _resolve_project_id(db, scope_type, ref_id)
    if pid is None:
        return {}
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days)
    end = today + timedelta(days=settings.forecast_horizon_days)
    return feat_svc.load_external_dict(db, pid, start, end)


# ---------------------------------------------------------------------------
# 计算入口
# ---------------------------------------------------------------------------


def compute_forecast(
    db: Session,
    project_id: int,
    *,
    horizon_days: int | None = None,
    history_days: int | None = None,
    model_version: str | None = None,
) -> dict | None:
    """单个项目的 risk_index 预测；样本不足返回 None（不落库）。"""
    horizon = horizon_days or settings.forecast_horizon_days
    history = history_days or settings.forecast_history_days
    series = _load_series(db, "project", str(project_id), METRIC_RISK_INDEX, days=history)
    if len(series) < settings.forecast_min_points:
        return None
    model_version = model_version or _resolve_default_model()
    ext = _load_external_features(db, "project", str(project_id), days=history)
    data = _fit_and_forecast(
        series, METRIC_RISK_INDEX, horizon, model_version=model_version, external_features=ext
    )
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
    model_version: str | None = None,
) -> dict | None:
    """单个设备的 health_score 预测（M2）；样本不足返回 None。"""
    horizon = horizon_days or settings.forecast_horizon_days
    history = history_days or settings.forecast_history_days
    series = _load_series(db, "device", device_no, METRIC_HEALTH_SCORE, days=history)
    if len(series) < settings.forecast_min_points:
        return None
    model_version = model_version or _resolve_default_model()
    ext = _load_external_features(db, "device", device_no, days=history)
    data = _fit_and_forecast(
        series, METRIC_HEALTH_SCORE, horizon, model_version=model_version, external_features=ext
    )
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
    metric: str | None = None,
    model_version: str | None = None,
) -> dict | None:
    """序列预览（M2，供前端画图）：历史点 + 拟合参数 + 预测点 + 置信带 + 可解释化贡献。

    样本不足时仍返回历史序列（forecast 为 None），前端可提示"数据积累中"。
    ``metric`` 缺省时按 scope 推断（project→risk_index / device→health_score），亦可由前端
    显式指定（多指标切换）。
    """
    horizon = horizon_days or settings.forecast_horizon_days
    history = history_days or settings.forecast_history_days
    metric = metric or (METRIC_RISK_INDEX if scope_type == "project" else METRIC_HEALTH_SCORE)
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
        model_version = model_version or _resolve_default_model()
        ext = _load_external_features(db, scope_type, ref_id, days=history)
        fit = _fit_and_forecast(
            series, metric, horizon, model_version=model_version, external_features=ext
        )
        if fit is not None:
            fit["forecast_at"] = fit["forecast_at"].isoformat()
            fit["computed_at"] = fit["computed_at"].isoformat()
            if fit.get("contributions"):
                fit["explanation"] = _explain_contributions(metric, fit["contributions"])
            out["forecast"] = fit
    return out


# ---------------------------------------------------------------------------
# 落库
# ---------------------------------------------------------------------------


def upsert_forecast(db: Session, data: dict, name: str | None = None) -> Forecast:
    """按唯一键 (scope_type, ref_id, metric, horizon_days) upsert。

    剔除仅用于解释/预览、不落库的字段（如 contributions）。
    """
    data = dict(data)
    data.pop("contributions", None)
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
    db: Session, horizon_days: int | None = None, model_version: str | None = None
) -> dict:
    """全量预测（项目 risk_index + 设备 health_score），批量加载防 N+1。

    不 commit，由调用方提交。返回 {computed, skipped, projects, devices}。
    """
    horizon = horizon_days or settings.forecast_horizon_days
    history = settings.forecast_history_days
    min_pts = settings.forecast_min_points
    model_version = model_version or _resolve_default_model()
    computed = skipped = 0

    # 项目级指标（按注册表遍历，未来新增指标自动覆盖）
    for meta in fm.metrics_for_scope("project"):
        proj_series = _load_series_bulk(db, "project", meta.key, days=history)
        projects = db.execute(
            select(Project.id, Project.name).where(Project.is_deleted.is_(False))
        ).all()
        for pid, pname in projects:
            series = proj_series.get(str(pid), [])
            if len(series) < min_pts:
                skipped += 1
                continue
            ext = _load_external_features(db, "project", str(pid), days=history)
            data = _fit_and_forecast(
                series, meta.key, horizon, model_version=model_version, external_features=ext
            )
            if data is None:
                skipped += 1
                continue
            data.update(project_id=pid, scope_type="project", ref_id=str(pid))
            upsert_forecast(db, data, name=pname)
            computed += 1

    # 设备级指标（M2，按注册表遍历）
    devices: list[tuple[str, str, int | None]] = []
    for m in _DEVICE_MODELS:
        devices.extend(
            db.execute(
                select(m.device_no, m.name, m.project_id).where(m.is_deleted.is_(False))
            ).all()
        )
    for meta in fm.metrics_for_scope("device"):
        dev_series = _load_series_bulk(db, "device", meta.key, days=history)
        for dno, dname, dpid in devices:
            series = dev_series.get(dno, [])
            if len(series) < min_pts:
                skipped += 1
                continue
            ext = _load_external_features(db, "device", dno, days=history)
            data = _fit_and_forecast(
                series, meta.key, horizon, model_version=model_version, external_features=ext
            )
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
    """越阈判据委托指标注册表（支持多指标、与预防式口径统一）。"""
    return fm.breach_for(metric, forecast_value, forecast_level)


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


def _explain_contributions(metric: str, contributions: list[dict]) -> str:
    """确定性模板解读：基于 top 贡献生成中文解释（可解释化）。

    contributions 已按 |impact| 降序；排除截距基线项，取前 3 个显著影响者。
    impact>0 推动预测值上升，<0 压低；按指标方向（low/high_good）措辞「恶化/改善」。
    """
    meta = fm.get_metric_meta(metric)
    if not meta:
        return ""
    top = [c for c in contributions if c.get("feature") != "intercept" and abs(c["impact"]) >= 0.5][
        :3
    ]
    if not top:
        return "预测主要由历史趋势决定，外部特征影响不显著。"
    parts = []
    for c in top:
        rising = c["impact"] > 0
        if meta.direction == fm.DIRECTION_LOW_GOOD:
            verdict = "上升（风险走高）" if rising else "下降（风险走低）"
            good = "不利" if rising else "有利"
        else:
            verdict = "上升（健康改善）" if rising else "下降（健康恶化）"
            good = "有利" if rising else "不利"
        parts.append(f"{c['label']}{verdict}（{good}）")
    return "；".join(parts) + "。"


def run_preventive_alerts(db: Session) -> dict[str, Any]:
    """预防式告警（置信带联动）：遍历 forecast 表，对预测置信区间将越过告警阈值的
    对象生成 ``preventive_alert`` 告警，比点预测越阈更早预警。

    判据见 :func:`forecast_metrics.preventive_breach`：low_good 指标（risk_index）看上界、
    high_good 指标（health_score）看下界。幂等唯一键
    ``preventive:{metric}:{ref_id}:{horizon_days}``（跨 Redis-TTL 仍生效）。
    复用既有告警流（落库 + 站内信 + 告警页）。
    """
    from app.core.constants import ALARM_TYPE_PREVENTIVE
    from app.service import alarm_service

    rows = db.scalars(select(Forecast)).all()
    created_ids: list[int] = []
    for fc in rows:
        if fc.forecast_value is None or fc.forecast_level is None:
            continue
        breach, level = fm.preventive_breach(fc.metric, fc.forecast_lower, fc.forecast_upper)
        if not breach or level is None:
            continue
        device_no = f"preventive:{fc.metric}:{fc.ref_id}:{fc.horizon_days}"
        existing = db.scalar(select(Alarm.id).where(Alarm.device_no == device_no).limit(1))
        if existing is not None:
            continue
        horizon = fc.horizon_days
        lower = fc.forecast_lower if fc.forecast_lower is not None else fc.forecast_value
        upper = fc.forecast_upper if fc.forecast_upper is not None else fc.forecast_value
        fa_str = fc.forecast_at.strftime("%Y-%m-%d") if fc.forecast_at else "—"
        meta = fm.get_metric_meta(fc.metric)
        metric_label = meta.label if meta else fc.metric
        if meta and meta.direction == fm.DIRECTION_LOW_GOOD:
            trend_phrase = f"将升至 {fc.forecast_value:.0f}（预测区间上限 {upper:.0f}）"
        else:
            trend_phrase = f"将跌至 {fc.forecast_value:.0f}（预测区间下限 {lower:.0f}）"
        info = (
            f"预防式预警：{metric_label}《{fc.name}》预测 {horizon} 天后{trend_phrase}，"
            f"95% 置信区间 [{lower:.0f}, {upper:.0f}] 将越过告警阈值，预计 {fa_str} 前触及，"
            f"建议提前介入处置。"
        )
        alarm = alarm_service.create_alarm(
            db,
            project_id=fc.project_id,
            alarm_type=ALARM_TYPE_PREVENTIVE,
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
