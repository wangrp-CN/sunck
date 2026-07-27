"""趋势异常检测服务（#81 扩展）：把四类时间序列的异常转成业务告警。

复用前端 ``web/src/utils/anomaly.ts`` 的统计基线算法（滚动均值 ±k·std z-score），
在后端独立实现一份（零额外依赖），保证检测口径与大屏高亮**完全一致**。

触发：随 ``scripts/snapshot_job.py`` 每日定时运行（与风险快照/关联计算同节拍），
把检测到的异常写入 ``alarm`` 表（新告警类型 ``trend_anomaly``），并复用既有告警流
（站内信通知 + 可在告警管理页「一键派单」接入根因派单闭环）。

设计要点：
- 每项目逐序列检测；每个（项目, 序列）仅对**最近一个异常周期**落一条告警，
  避免历史尖刺一次性刷出大量告警；以 ``device_no`` 编码 ``(序列,项目,周期)`` 保证
  幂等（已存在同 device_no 告警则跳过，不重复派警）。
- 日序列按 UTC 日界对齐（零填充），使「告警量骤降 / 大批设备掉线」等 drop 异常可被识别；
  风险序列仅取有快照的日子（缺失≠风险归零，避免误报 drop）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.constants import ALARM_TYPE_ANOMALY
from app.core.data_scope import DataScope, apply_data_scope
from app.model.alarm import Alarm
from app.model.correlation import CorrelatedEventGroup
from app.model.project import Project
from app.model.realtime import DeviceLocation
from app.model.snapshot import RiskHealthSnapshot
from app.service import alarm_service

logger = logging.getLogger("rail_monitor.anomaly")

#: 序列中文名（用于告警信息 + 派单根因提示）
SERIES_LABELS: dict[str, str] = {
    "alarm": "告警量",
    "risk": "风险指数",
    "correlation": "跨设备共因",
    "device": "设备活跃",
}


# ---------------------------------------------------------------------------
# 工具：UTC 日界周期 key + 配置化检测超参
# ---------------------------------------------------------------------------
def _utc_day(dt: datetime) -> str:
    """把 tz-aware 时间归一到 UTC 日界 ``YYYY-MM-DD``，保证零填充键与聚合桶同源。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _day_periods(start: datetime, end: datetime) -> list[str]:
    """生成 [start, end]（含）的 UTC 日界周期键列表，供零填充对齐。"""
    s = start.astimezone(timezone.utc) if start.tzinfo else start.replace(tzinfo=timezone.utc)
    e = end.astimezone(timezone.utc) if end.tzinfo else end.replace(tzinfo=timezone.utc)
    keys: list[str] = []
    cur = s
    guard = 0
    while cur <= e and guard < 4000:
        keys.append(cur.strftime("%Y-%m-%d"))
        cur += timedelta(days=1)
        guard += 1
    return keys


def _opts() -> dict[str, Any]:
    """检测超参（与前端 anomaly.ts 默认 + 后端 config 对齐）。"""
    return {
        "window": settings.anomaly_window,
        "k": settings.anomaly_k,
        "min_trailing": settings.anomaly_min_trailing,
        "min_points": settings.anomaly_min_points,
    }


# ---------------------------------------------------------------------------
# 检测核心（前端 detectAnomalies 的 Python 同口径实现）
# ---------------------------------------------------------------------------
def detect_series(
    values: list[float],
    *,
    window: int,
    k: float,
    min_trailing: int,
    min_points: int,
) -> list[dict[str, Any]]:
    """对单条序列逐点计算基线 z-score 并判异常（与前端 ``detectAnomalies`` 完全一致）。

    返回每个点的 ``{value, baseline_mean, baseline_std, z, is_anomaly, direction}``。
    - 历史样本不足 ``min_trailing`` 或序列过短 ``< min_points``：该点不判异常。
    - 基线恒定（std≈0）时任何偏离常量即判异常（避免平稳后突跳漏检），z 记为 ±Infinity。
    """
    n = len(values)
    if n < min_points:
        return [
            {
                "value": v,
                "baseline_mean": v,
                "baseline_std": 0.0,
                "z": 0.0,
                "is_anomaly": False,
                "direction": None,
            }
            for v in values
        ]
    out: list[dict[str, Any]] = []
    for i in range(n):
        start = max(0, i - window)
        prev = values[start:i]
        v = values[i]
        if len(prev) < min_trailing:
            out.append(
                {
                    "value": v,
                    "baseline_mean": v,
                    "baseline_std": 0.0,
                    "z": 0.0,
                    "is_anomaly": False,
                    "direction": None,
                }
            )
            continue
        mean = sum(prev) / len(prev)
        variance = sum((x - mean) ** 2 for x in prev) / len(prev)
        std = variance**0.5
        z = 0.0
        is_anomaly = False
        direction: str | None = None
        if std > 1e-9:
            z = (v - mean) / std
            is_anomaly = abs(z) > k
            direction = "spike" if z > 0 else "drop" if is_anomaly else None
        else:
            dev = abs(v - mean)
            if dev > 1e-9:
                is_anomaly = True
                direction = "spike" if v > mean else "drop"
                z = (1.0 if v > mean else -1.0) * float("inf")
        out.append(
            {
                "value": v,
                "baseline_mean": mean,
                "baseline_std": std,
                "z": z,
                "is_anomaly": is_anomaly,
                "direction": direction,
            }
        )
    return out


#: z 的 JSON 安全哨兵值：±inf（常量基线偏离）序列化前替换为 ±Z_INF
#: （starlette JSONResponse 的 json.dumps(allow_nan=False) 不接受 Infinity）。
Z_INF = 9999.0


def _level_for(z: float) -> str:
    """按偏离程度映射告警级别（与前端卡片方向配色一致：严重/警告/提示）。"""
    az = abs(z)
    if az >= Z_INF or az >= 3:
        return "严重"
    if az >= 2:
        return "警告"
    return "提示"


def _json_z(z: float) -> float:
    """把 ±inf 替换为 ±Z_INF 哨兵，保证 API 响应可 JSON 序列化。"""
    if z == float("inf"):
        return Z_INF
    if z == float("-inf"):
        return -Z_INF
    return round(z, 2)


def _fmt_z(z: float) -> str:
    return "∞" if abs(z) >= Z_INF else f"{z:.1f}"


# ---------------------------------------------------------------------------
# 四类序列计算（每项目、日粒度、零填充到 UTC 日界）
# ---------------------------------------------------------------------------
def _series_alarm(
    db: Session, pid: int, keys: list[str], start: datetime, end: datetime
) -> tuple[list[float], list[str]]:
    bucket = func.date_trunc("day", Alarm.alarm_time)
    rows = db.execute(
        select(bucket.label("b"), func.count().label("c"))
        .where(Alarm.project_id == pid, Alarm.alarm_time >= start, Alarm.alarm_time <= end)
        .group_by(bucket)
        .order_by(bucket.asc())
    ).all()
    m = {_utc_day(b): int(c) for b, c in rows}
    return [float(m.get(key, 0)) for key in keys], keys


def _series_risk(
    db: Session, pid: int, start: datetime, end: datetime
) -> tuple[list[float], list[str]]:
    """风险指数序列：仅取有快照的日子（缺失≠风险归零），避免误报 drop。"""
    rows = db.execute(
        select(RiskHealthSnapshot.snapshot_at, RiskHealthSnapshot.risk_index)
        .where(
            RiskHealthSnapshot.scope_type == "project",
            RiskHealthSnapshot.ref_id == str(pid),
            RiskHealthSnapshot.snapshot_at >= start,
            RiskHealthSnapshot.snapshot_at <= end,
        )
        .order_by(RiskHealthSnapshot.snapshot_at.asc())
    ).all()
    vals = [float(r[1] if r[1] is not None else 0) for r in rows]
    periods = [_utc_day(r[0]) for r in rows]
    return vals, periods


def _series_correlation(
    db: Session, pid: int, keys: list[str], start: datetime, end: datetime
) -> tuple[list[float], list[str]]:
    bucket = func.date_trunc("day", CorrelatedEventGroup.started_at)
    rows = db.execute(
        select(bucket.label("b"), func.count().label("c"))
        .where(
            CorrelatedEventGroup.project_id == pid,
            CorrelatedEventGroup.is_cross_device.is_(True),
            CorrelatedEventGroup.started_at >= start,
            CorrelatedEventGroup.started_at <= end,
        )
        .group_by(bucket)
        .order_by(bucket.asc())
    ).all()
    m = {_utc_day(b): int(c) for b, c in rows}
    return [float(m.get(key, 0)) for key in keys], keys


def _series_device(
    db: Session, pid: int, keys: list[str], start: datetime, end: datetime
) -> tuple[list[float], list[str]]:
    bucket = func.date_trunc("day", DeviceLocation.report_time)
    rows = db.execute(
        select(bucket.label("b"), func.count(func.distinct(DeviceLocation.device_no)).label("c"))
        .where(
            DeviceLocation.project_id == pid,
            DeviceLocation.report_time >= start,
            DeviceLocation.report_time <= end,
        )
        .group_by(bucket)
        .order_by(bucket.asc())
    ).all()
    m = {_utc_day(b): int(c) for b, c in rows}
    return [float(m.get(key, 0)) for key in keys], keys


def compute_series(
    db: Session, pid: int, keys: list[str], start: datetime, end: datetime
) -> dict[str, tuple[list[float], list[str]]]:
    """返回四类序列（values, periods）元组，periods 与 values 等长。"""
    return {
        "alarm": _series_alarm(db, pid, keys, start, end),
        "risk": _series_risk(db, pid, start, end),
        "correlation": _series_correlation(db, pid, keys, start, end),
        "device": _series_device(db, pid, keys, start, end),
    }


# ---------------------------------------------------------------------------
# 异常聚合 + 告警落库
# ---------------------------------------------------------------------------
def _project_name(db: Session, pid: int) -> str | None:
    return db.scalar(select(Project.name).where(Project.id == pid))


def collect_project_anomalies(
    db: Session,
    pid: int,
    name: str | None,
    keys: list[str],
    start: datetime,
    end: datetime,
    opts: dict[str, Any],
) -> list[dict[str, Any]]:
    """汇总某项目四类序列的全部异常点（用于大屏预览 / 调试，不落库）。"""
    series = compute_series(db, pid, keys, start, end)
    out: list[dict[str, Any]] = []
    for skey, (vals, periods) in series.items():
        if len(vals) < opts["min_points"]:
            continue
        det = detect_series(vals, **opts)
        for i, a in enumerate(det):
            if a["is_anomaly"]:
                out.append(
                    {
                        "project_id": pid,
                        "project_name": name,
                        "series_key": skey,
                        "series_label": SERIES_LABELS.get(skey, skey),
                        "period": periods[i],
                        "value": a["value"],
                        "baseline_mean": round(a["baseline_mean"], 2),
                        "z": _json_z(a["z"]),
                        "direction": a["direction"],
                        "level": _level_for(a["z"]),
                    }
                )
    return out


def _emit_anomaly_alarm(db: Session, rec: dict[str, Any]) -> Alarm | None:
    """把单条异常记录落为 trend_anomaly 告警（幂等：同 device_no 已存在则跳过）。"""
    pid = rec["project_id"]
    skey = rec["series_key"]
    period = rec["period"]
    device_no = f"anomaly:{skey}:{pid}:{period}"
    # 幂等：避免每日定时重复派警（Alarm 无软删，直接按 device_no 去重）
    existing = db.scalar(select(Alarm.id).where(Alarm.device_no == device_no).limit(1))
    if existing:
        return None
    label = rec["series_label"]
    direction = "突增" if rec["direction"] == "spike" else "突降"
    info = (
        f"[{label}] 周期 {period} 检测到趋势异常（{direction}）："
        f"实测 {rec['value']:.0f} / 基线 {rec['baseline_mean']:.0f}，z={_fmt_z(rec['z'])}"
    )
    alarm_time = datetime(int(period[:4]), int(period[5:7]), int(period[8:10]), tzinfo=timezone.utc)
    return alarm_service.create_alarm(
        db,
        project_id=pid,
        alarm_type=ALARM_TYPE_ANOMALY,
        device_no=device_no,
        device_name=label,
        alarm_info=info,
        alarm_level=rec["level"],
        alarm_time=alarm_time,
        handle_status="待处理",
    )


def run_anomaly_detection(
    db: Session, *, lookback_days: int | None = None, project_id: int | None = None
) -> dict[str, Any]:
    """检测并落库趋势异常告警。

    - 每项目逐序列检测；每个（项目, 序列）仅对**最近一个异常周期**落一条告警，
      以 ``device_no`` 编码 ``(序列,项目,周期)`` 保证跨日运行幂等。
    - 返回 ``{created, alarm_ids}``。调用方负责 commit（与 snapshot_job 同节拍）。
    """
    opts = _opts()
    lookback = lookback_days or settings.anomaly_lookback_days
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback)
    keys = _day_periods(start, end)

    if project_id is not None:
        pids = [project_id]
    else:
        pids = list(db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).all())

    created_ids: list[int] = []
    for pid in pids:
        name = _project_name(db, pid)
        all_anoms = collect_project_anomalies(db, pid, name, keys, start, end, opts)
        # 每个 (项目, 序列) 仅保留最近一个异常周期
        latest: dict[tuple[int, str], dict[str, Any]] = {}
        for a in all_anoms:
            key = (pid, a["series_key"])
            prev = latest.get(key)
            if prev is None or a["period"] > prev["period"]:
                latest[key] = a
        for rec in latest.values():
            alarm = _emit_anomaly_alarm(db, rec)
            if alarm is not None:
                created_ids.append(alarm.id)
    return {"created": len(created_ids), "alarm_ids": created_ids}


def get_anomaly_detections(
    db: Session, scope: DataScope, *, lookback_days: int | None = None
) -> list[dict[str, Any]]:
    """预览当前数据范围内的趋势异常（不落库），供大屏 /metrics/anomalies 使用。"""
    opts = _opts()
    lookback = lookback_days or settings.anomaly_lookback_days
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback)
    keys = _day_periods(start, end)

    stmt = select(Project.id, Project.name).where(Project.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, Project, scope)
    projects = db.execute(stmt).all()

    out: list[dict[str, Any]] = []
    for pid, name in projects:
        out.extend(collect_project_anomalies(db, pid, name, keys, start, end, opts))
    # 按 |z| 降序，最显著的排前（z 已经 _json_z 哨兵化，无 inf）
    out.sort(key=lambda x: abs(x["z"]), reverse=True)
    return out
