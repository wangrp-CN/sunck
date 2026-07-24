"""风险/健康分时序快照：聚合与查询（智能核心 v2）。

聚合口径与 ``devices/health``、``dashboard/project-compare`` 两个端点**完全一致**：

- 设备健康：``reported`` = 窗口内 DeviceLocation 上报数 > 0（非告警数）；在线状态
  fresh/stale/offline 按 ``last_seen`` 与 ``settings.online_threshold_seconds`` 判定；
- 项目风险：未处理告警 ``handle_status=='待处理'`` 按级别加权；超期/存量隐患用
  ``status.notin_(["已销号","已驳回"])``。

保证快照数字与前端大屏同源，趋势/预警才不会与实时视图脱节。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.config import settings
from app.core.scoring import (
    device_health_level,
    device_health_score,
    project_risk_score,
)
from app.model.alarm import Alarm
from app.model.device import AntiIntrusionDevice, LocateDevice, TrainApproachDevice
from app.model.hazard import Hazard
from app.model.project import Project
from app.model.realtime import DeviceLocation
from app.model.snapshot import RiskHealthSnapshot

DEVICE_MODELS = [AntiIntrusionDevice, LocateDevice, TrainApproachDevice]
HAZARD_CLOSED = ["已销号", "已驳回"]


def compute_device_healths(db, hours: int = 24) -> list[dict]:
    """遍历三类设备，复刻 devices/health 的聚合口径，返回健康分列表。"""
    now = datetime.now(timezone.utc)
    since = now - timedelta(hours=hours)
    threshold = settings.online_threshold_seconds

    device_nos: list[str] = []
    meta: dict[str, dict] = {}
    for m in DEVICE_MODELS:
        rows = db.execute(select(m.device_no, m.name).where(m.is_deleted.is_(False))).all()
        for no, name in rows:
            device_nos.append(no)
            meta[no] = {"name": name}

    if not device_nos:
        return []

    loc_rows = db.execute(
        select(
            DeviceLocation.device_no,
            func.count(DeviceLocation.id),
            func.max(DeviceLocation.report_time),
        )
        .where(DeviceLocation.device_no.in_(device_nos), DeviceLocation.report_time >= since)
        .group_by(DeviceLocation.device_no)
    ).all()
    report_stats = {r[0]: (r[1], r[2]) for r in loc_rows}

    last_rows = db.execute(
        select(DeviceLocation.device_no, func.max(DeviceLocation.report_time))
        .where(DeviceLocation.device_no.in_(device_nos))
        .group_by(DeviceLocation.device_no)
    ).all()
    last_seen = {r[0]: r[1] for r in last_rows}

    alarm_rows = db.execute(
        select(Alarm.device_no, Alarm.alarm_level, func.count(Alarm.id))
        .where(Alarm.device_no.in_(device_nos), Alarm.alarm_time >= since)
        .group_by(Alarm.device_no, Alarm.alarm_level)
    ).all()
    alarm_sev: dict[str, dict[str, int]] = defaultdict(dict)
    for no, lvl, cnt in alarm_rows:
        alarm_sev[no][lvl or "提示"] = cnt

    out = []
    for no in device_nos:
        rpt_count, _ = report_stats.get(no, (0, None))
        last = last_seen.get(no)
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = (now - last).total_seconds() if last is not None else None
        if age is None:
            state = "offline"
        elif age <= threshold:
            state = "fresh"
        elif age <= 2 * threshold:
            state = "stale"
        else:
            state = "offline"
        sev = alarm_sev.get(no, {})
        score = device_health_score(
            online_state=state, reported=rpt_count > 0, alarm_severity_counts=sev
        )
        out.append(
            {
                "device_no": no,
                "name": meta[no]["name"],
                "online_state": state,
                "health_score": score,
                "health_level": device_health_level(score),
            }
        )
    return out


def compute_project_risks(db, days: int = 7) -> list[dict]:
    """遍历项目，复刻 dashboard/project-compare 的聚合口径，返回风险分列表。"""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    projects = db.scalars(select(Project).where(Project.is_deleted.is_(False))).all()
    if not projects:
        return []
    pids = [p.id for p in projects]

    unhandled_rows = db.execute(
        select(Alarm.project_id, Alarm.alarm_level, func.count(Alarm.id))
        .where(
            Alarm.project_id.in_(pids),
            Alarm.alarm_time >= since,
            Alarm.handle_status == "待处理",
        )
        .group_by(Alarm.project_id, Alarm.alarm_level)
    ).all()
    unhandled_by_level: dict[int, dict[str, int]] = defaultdict(dict)
    for pid, lvl, cnt in unhandled_rows:
        unhandled_by_level[pid][lvl or "提示"] = cnt

    overdue_rows = db.execute(
        select(Hazard.project_id, Hazard.level, func.count(Hazard.id))
        .where(
            Hazard.project_id.in_(pids),
            Hazard.is_deleted.is_(False),
            Hazard.status.notin_(HAZARD_CLOSED),
            Hazard.due_at.is_not(None),
            Hazard.due_at < now,
        )
        .group_by(Hazard.project_id, Hazard.level)
    ).all()
    overdue_by_level: dict[int, dict[str, int]] = defaultdict(dict)
    for pid, lvl, cnt in overdue_rows:
        overdue_by_level[pid][lvl or "一般"] = cnt

    open_rows = db.execute(
        select(Hazard.project_id, func.count(Hazard.id))
        .where(
            Hazard.project_id.in_(pids),
            Hazard.is_deleted.is_(False),
            Hazard.status.notin_(HAZARD_CLOSED),
        )
        .group_by(Hazard.project_id)
    ).all()
    open_by_pid = {pid: cnt for pid, cnt in open_rows}

    out = []
    for p in projects:
        raw, idx, level = project_risk_score(
            unhandled_by_level=unhandled_by_level.get(p.id, {}),
            overdue_by_level=overdue_by_level.get(p.id, {}),
            open_hazards=open_by_pid.get(p.id, 0),
        )
        out.append(
            {
                "project_id": p.id,
                "name": p.name,
                "risk_index": idx,
                "risk_level": level,
                "raw_score": raw,
            }
        )
    return out


def run_snapshot(db, hours: int = 24, days: int = 7, snapshot_at: datetime | None = None) -> dict:
    """计算并落库一次快照（项目风险 + 设备健康）。"""
    snapshot_at = snapshot_at or datetime.now(timezone.utc)
    dev = compute_device_healths(db, hours=hours)
    proj = compute_project_risks(db, days=days)
    for d in dev:
        db.add(
            RiskHealthSnapshot(
                scope_type="device",
                ref_id=d["device_no"],
                name=d["name"],
                health_score=d["health_score"],
                health_level=d["health_level"],
                online_state=d["online_state"],
                snapshot_at=snapshot_at,
            )
        )
    for p in proj:
        db.add(
            RiskHealthSnapshot(
                scope_type="project",
                ref_id=str(p["project_id"]),
                name=p["name"],
                risk_index=p["risk_index"],
                risk_level=p["risk_level"],
                raw_score=p["raw_score"],
                snapshot_at=snapshot_at,
            )
        )
    db.commit()
    return {
        "devices": len(dev),
        "projects": len(proj),
        "snapshot_at": snapshot_at.isoformat(),
    }


def get_risk_trend(db, project_id: int, days: int = 30) -> list[dict]:
    """项目风险指数时间序列（旧→新）。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(
            RiskHealthSnapshot.snapshot_at,
            RiskHealthSnapshot.risk_index,
            RiskHealthSnapshot.risk_level,
        )
        .where(
            RiskHealthSnapshot.scope_type == "project",
            RiskHealthSnapshot.ref_id == str(project_id),
            RiskHealthSnapshot.snapshot_at >= since,
        )
        .order_by(RiskHealthSnapshot.snapshot_at.asc())
    ).all()
    return [{"snapshot_at": r[0].isoformat(), "risk_index": r[1], "risk_level": r[2]} for r in rows]


def get_health_trend(db, device_no: str, days: int = 30) -> list[dict]:
    """单设备健康分时间序列（旧→新）。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(
            RiskHealthSnapshot.snapshot_at,
            RiskHealthSnapshot.health_score,
            RiskHealthSnapshot.health_level,
            RiskHealthSnapshot.online_state,
        )
        .where(
            RiskHealthSnapshot.scope_type == "device",
            RiskHealthSnapshot.ref_id == device_no,
            RiskHealthSnapshot.snapshot_at >= since,
        )
        .order_by(RiskHealthSnapshot.snapshot_at.asc())
    ).all()
    return [
        {
            "snapshot_at": r[0].isoformat(),
            "health_score": r[1],
            "health_level": r[2],
            "online_state": r[3],
        }
        for r in rows
    ]


def get_latest_risk_snapshots(db, project_ids: list[int] | None = None) -> list[dict]:
    """每个项目最新一条风险快照（对比大屏趋势入口）。

    ``project_ids`` 为空列表时返回空（无数据范围）；为 ``None`` 时不限（系统级）。
    """
    if project_ids is not None and not project_ids:
        return []
    stmt = select(RiskHealthSnapshot).where(RiskHealthSnapshot.scope_type == "project")
    if project_ids is not None:
        stmt = stmt.where(RiskHealthSnapshot.ref_id.in_([str(i) for i in project_ids]))
    rows = db.execute(stmt.order_by(RiskHealthSnapshot.snapshot_at.desc())).scalars().all()
    latest: dict[str, RiskHealthSnapshot] = {}
    for r in rows:
        if r.ref_id not in latest:
            latest[r.ref_id] = r
    return [
        {
            "project_id": int(r.ref_id),
            "name": r.name,
            "risk_index": r.risk_index,
            "risk_level": r.risk_level,
            "raw_score": r.raw_score,
            "snapshot_at": r.snapshot_at.isoformat() if r.snapshot_at else None,
        }
        for r in latest.values()
    ]
