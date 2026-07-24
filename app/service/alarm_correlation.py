"""跨设备根因关联服务（智能核心 v2 · #77）。

核心思路：把一段时间窗口内的告警，按「**项目 + 空间范围 + 时间近邻**」聚合成
*事件组*（CorrelatedEventGroup），从而揭示「多台设备在同一围栏 / 同一地理区域
短时集中告警」这类跨设备共因事件。

空间范围（scope）三级判定（优先级从高到低）：
1. ``fence``  —— 告警带 ``fence_name``，按围栏名聚合（最准确的现场共因锚点）；
2. ``geo``    —— 无围栏名但设备有最新定位，按经纬度网格（~1.1km）聚合；
3. ``device`` —— 其余（无围栏名且无定位，或单机持续告警），按设备单聚。

时间窗聚类：同一 (项目, 空间范围) 桶内按 ``alarm_time`` 排序，相邻告警间隔超过
``cluster_gap_minutes`` 即切分为新的事件组。

本服务为**派生滚动表**：``compute_correlations`` 每次全量重算（删旧插新），
``computed_at`` 标记计算时刻。查询侧仅做读取 + 数据范围过滤，不保留历史。
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope, apply_data_scope
from app.model.alarm import Alarm
from app.model.correlation import CorrelatedEventGroup
from app.model.project import Project
from app.model.realtime import DeviceLocation

# 地理网格边长（度）：0.01° ≈ 1.1km @ 赤道，足够把「同一区域施工/侵限」聚到一起
GRID_SIZE_DEG = 0.01

# 告警级别严重度排序（用于取 max_level 与配色）
LEVEL_ORDER: dict[str, int] = {"严重": 3, "警告": 2, "提示": 1}
LEVEL_RANK = {v: k for k, v in LEVEL_ORDER.items()}


def _span_text(started: datetime | None, ended: datetime | None) -> str:
    if not started or not ended:
        return "—"
    minutes = (ended - started).total_seconds() / 60.0
    if minutes < 1:
        return "即时"
    if minutes < 60:
        return f"{int(minutes)}分钟"
    return f"{minutes / 60:.1f}小时"


def _scope_of(alarm: Alarm, dev_loc: dict[str, tuple[float, float]]) -> tuple[str, str]:
    """返回 (spatial_type, scope_value)。dev_loc: device_no -> (lng, lat)。"""
    if alarm.fence_name:
        return "fence", alarm.fence_name
    loc = dev_loc.get(alarm.device_no) if alarm.device_no else None
    if loc and loc[0] is not None and loc[1] is not None:
        lng, lat = loc
        cell = f"{round(lat / GRID_SIZE_DEG):.0f},{round(lng / GRID_SIZE_DEG):.0f}"
        return "geo", cell
    # 兜底：按设备（或告警 id，防止 device_no 为空时互相合并）
    return "device", alarm.device_no or f"none:{alarm.id}"


def _build_hint(group: dict[str, Any]) -> str:
    st = group["spatial_type"]
    span = _span_text(group["started_at"], group["ended_at"])
    n_dev = group["device_count"]
    n_al = group["alarm_count"]
    if st == "fence":
        name = group.get("fence_name") or "未知围栏"
        if group["is_cross_device"]:
            return (
                f"同一围栏「{name}」在 {span} 内聚集 {n_dev} 台设备共 {n_al} 条告警，"
                f"疑似现场作业扰动或围栏误报集中"
            )
        return f"围栏「{name}」内单机持续告警（{n_al} 条 / {span}）"
    if st == "geo":
        cell = group.get("grid_cell") or "?"
        if group["is_cross_device"]:
            return (
                f"地理邻近区域（网格 {cell}）在 {span} 内 {n_dev} 台设备集中告警，"
                f"疑似同一区域施工或侵限事件"
            )
        return f"地理邻近区域单机持续告警（{n_al} 条 / {span}）"
    # device
    dev = (group.get("device_nos") or ["?"])[0]
    return f"设备 {dev} 持续告警（{n_al} 条 / {span}），建议排查设备本身或链路"


def compute_correlations(
    db: Session,
    window_hours: int = 24,
    cluster_gap_minutes: int = 30,
) -> dict[str, Any]:
    """全量重算跨设备关联事件组，写入 ``correlated_event_group`` 表。

    返回汇总：{groups, cross_device_groups, window_hours, gap_minutes, computed_at}。
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)

    alarms = (
        db.scalars(select(Alarm).where(Alarm.alarm_time >= cutoff)).all()
        if cutoff
        else db.scalars(select(Alarm)).all()
    )
    if not alarms:
        # 无告警：清空旧关联组（保持派生表与现状一致）
        db.execute(delete(CorrelatedEventGroup))
        db.commit()
        return {
            "groups": 0,
            "cross_device_groups": 0,
            "window_hours": window_hours,
            "gap_minutes": cluster_gap_minutes,
            "computed_at": now.isoformat(),
        }

    # 设备最新定位（DISTINCT ON device_no，取 report_time 最近一条；Postgres 支持）
    device_nos = [a.device_no for a in alarms if a.device_no]
    dev_loc: dict[str, tuple[float, float]] = {}
    if device_nos:
        loc_rows = db.execute(
            select(
                DeviceLocation.device_no,
                DeviceLocation.longitude,
                DeviceLocation.latitude,
            )
            .where(DeviceLocation.device_no.in_(device_nos))
            .distinct(DeviceLocation.device_no)
            .order_by(DeviceLocation.device_no, DeviceLocation.report_time.desc())
        ).all()
        for dno, lng, lat in loc_rows:
            dev_loc[dno] = (lng, lat)

    # 项目名映射（含已软删项目也保留，因告警可能归属历史项目）
    proj_names = {pid: pname for pid, pname in db.execute(select(Project.id, Project.name)).all()}

    # 分桶：(project_id, spatial_type, scope_value) -> [alarm, ...]
    buckets: dict[tuple, list[Alarm]] = defaultdict(list)
    for a in alarms:
        st, sv = _scope_of(a, dev_loc)
        buckets[(a.project_id, st, sv)].append(a)

    gap = timedelta(minutes=cluster_gap_minutes)
    rows: list[CorrelatedEventGroup] = []

    for (project_id, st, sv), items in buckets.items():
        items.sort(key=lambda x: (x.alarm_time or datetime.min.replace(tzinfo=timezone.utc)))
        # 时间窗切分
        clusters: list[list[Alarm]] = []
        cur: list[Alarm] = []
        last_t: datetime | None = None
        for a in items:
            t = a.alarm_time or datetime.min.replace(tzinfo=timezone.utc)
            if last_t is not None and (t - last_t) > gap:
                clusters.append(cur)
                cur = []
            cur.append(a)
            last_t = t
        if cur:
            clusters.append(cur)

        for cl in clusters:
            dev_nos = sorted({a.device_no for a in cl if a.device_no})
            levels = [a.alarm_level for a in cl if a.alarm_level]
            types = [a.alarm_type for a in cl if a.alarm_type]
            ids = [a.id for a in cl]
            max_rank = max((LEVEL_ORDER.get(lv, 0) for lv in levels), default=0)
            max_level = LEVEL_RANK.get(max_rank)
            started = min((a.alarm_time for a in cl if a.alarm_time), default=None)
            ended = max((a.alarm_time for a in cl if a.alarm_time), default=None)

            grp = {
                "project_id": project_id,
                "spatial_type": st,
                "scope_key": sv,
                "fence_name": sv if st == "fence" else None,
                "grid_cell": sv if st == "geo" else None,
                "started_at": started,
                "ended_at": ended,
                "alarm_count": len(cl),
                "device_count": len(dev_nos),
                "is_cross_device": len(dev_nos) >= 2,
                "max_level": max_level,
                "device_nos": dev_nos,
                "levels": levels,
                "alarm_types": types,
                "alarm_ids": ids,
            }
            grp["root_cause_hint"] = _build_hint(grp)

            rows.append(
                CorrelatedEventGroup(
                    project_id=project_id,
                    project_name=proj_names.get(project_id),
                    spatial_type=st,
                    scope_key=sv,
                    fence_name=grp["fence_name"],
                    grid_cell=grp["grid_cell"],
                    started_at=started,
                    ended_at=ended,
                    alarm_count=grp["alarm_count"],
                    device_count=grp["device_count"],
                    is_cross_device=grp["is_cross_device"],
                    max_level=max_level,
                    device_nos=json.dumps(dev_nos, ensure_ascii=False),
                    levels=json.dumps(levels, ensure_ascii=False),
                    alarm_types=json.dumps(types, ensure_ascii=False),
                    alarm_ids=json.dumps(ids, ensure_ascii=False),
                    root_cause_hint=grp["root_cause_hint"],
                    computed_at=now,
                )
            )

    # 全量重算：先清后插（派生滚动表语义）
    db.execute(delete(CorrelatedEventGroup))
    db.add_all(rows)
    db.commit()

    cross = sum(1 for r in rows if r.is_cross_device)
    return {
        "groups": len(rows),
        "cross_device_groups": cross,
        "window_hours": window_hours,
        "gap_minutes": cluster_gap_minutes,
        "computed_at": now.isoformat(),
    }


def run_correlations(
    db: Session, window_hours: int = 24, cluster_gap_minutes: int = 30
) -> dict[str, Any]:
    """对外包装：执行一次关联计算并返回汇总（供快照任务 / 手动触发复用）。"""
    return compute_correlations(
        db, window_hours=window_hours, cluster_gap_minutes=cluster_gap_minutes
    )


def get_correlations(
    db: Session,
    allowed_project_ids: set[int],
    only_cross_device: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """读取当前关联事件组（已按数据范围过滤），按告警数降序、时间倒序。"""
    if not allowed_project_ids:
        return []
    stmt = select(CorrelatedEventGroup).where(
        CorrelatedEventGroup.project_id.in_(allowed_project_ids)
    )
    if only_cross_device:
        stmt = stmt.where(CorrelatedEventGroup.is_cross_device.is_(True))
    stmt = stmt.order_by(
        CorrelatedEventGroup.alarm_count.desc(),
        CorrelatedEventGroup.started_at.desc().nullslast(),
    )
    if limit:
        stmt = stmt.limit(limit)
    return [r.to_dict() for r in db.scalars(stmt).all()]


def get_correlation_members(
    db: Session, group_id: int, scope: DataScope
) -> list[dict[str, Any]] | None:
    """返回某事件组的成员告警明细（受数据范围约束）；组不存在返回 None。

    明细供前端展开行展示，字段与告警列表保持最小一致。
    """
    group = db.get(CorrelatedEventGroup, group_id)
    if group is None:
        return None
    try:
        ids = json.loads(group.alarm_ids) if group.alarm_ids else []
    except (json.JSONDecodeError, TypeError):
        ids = []
    if not ids:
        return []
    stmt = select(Alarm).where(Alarm.id.in_(ids))
    stmt = apply_data_scope(stmt, Alarm, scope)
    stmt = stmt.order_by(Alarm.alarm_time.desc().nullslast())
    out: list[dict[str, Any]] = []
    for a in db.scalars(stmt).all():
        out.append(
            {
                "id": a.id,
                "device_no": a.device_no,
                "device_name": a.device_name,
                "alarm_type": a.alarm_type,
                "alarm_level": a.alarm_level,
                "alarm_status": a.alarm_status,
                "handle_status": a.handle_status,
                "alarm_time": a.alarm_time.isoformat() if a.alarm_time else None,
                "alarm_info": a.alarm_info,
                "fence_name": a.fence_name,
                "project_id": a.project_id,
            }
        )
    return out
