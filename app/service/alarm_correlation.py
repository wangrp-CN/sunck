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
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.data_scope import DataScope, apply_data_scope
from app.model.alarm import Alarm
from app.model.correlation import CorrelatedEventGroup, _json_list
from app.model.project import Project
from app.model.realtime import DeviceLocation

logger = logging.getLogger("rail_monitor.correlation")

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


def _build_groups(
    db: Session,
    alarms: list[Alarm],
    cluster_gap_minutes: int = 30,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """把告警按「项目 + 空间范围 + 时间近邻」聚合成事件组中间字典（不落库）。

    返回每个事件组的字典（含 ``project_name``、``device_nos`` 为列表等），供
    ``compute_correlations`` 落库，或 ``get_correlation_heatmap_windowed`` /
    ``compare_correlation_windows`` 做任意历史时间窗的窗口化重算复用。
    """
    if not alarms:
        return []
    now = now or datetime.now(timezone.utc)

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
    groups: list[dict[str, Any]] = []

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

            grp: dict[str, Any] = {
                "project_id": project_id,
                "project_name": proj_names.get(project_id),
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
            groups.append(grp)

    return groups


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

    groups = _build_groups(db, alarms, cluster_gap_minutes, now=now)

    # 全量重算：先清后插（派生滚动表语义）
    rows = [
        CorrelatedEventGroup(
            project_id=g["project_id"],
            project_name=g["project_name"],
            spatial_type=g["spatial_type"],
            scope_key=g["scope_key"],
            fence_name=g["fence_name"],
            grid_cell=g["grid_cell"],
            started_at=g["started_at"],
            ended_at=g["ended_at"],
            alarm_count=g["alarm_count"],
            device_count=g["device_count"],
            is_cross_device=g["is_cross_device"],
            max_level=g["max_level"],
            device_nos=json.dumps(g["device_nos"], ensure_ascii=False),
            levels=json.dumps(g["levels"], ensure_ascii=False),
            alarm_types=json.dumps(g["alarm_types"], ensure_ascii=False),
            alarm_ids=json.dumps(g["alarm_ids"], ensure_ascii=False),
            root_cause_hint=g["root_cause_hint"],
            computed_at=now,
        )
        for g in groups
    ]
    db.execute(delete(CorrelatedEventGroup))
    db.add_all(rows)
    db.commit()

    # 实时推送：把新增的跨设备共因事件组经 Redis 桥发往 WebSocket（指纹去重）。
    # 无论本次计算运行在 snapshot_job 还是 API 进程，前端都能经订阅线程收到。
    if settings.ws_correlation_enabled:
        try:
            from app.ws.correlation_pubsub import publish_new_cross_device_groups

            publish_new_cross_device_groups(rows)
        except Exception as exc:  # noqa: BLE001
            logger.warning("关联事件 WS 发布失败(已忽略): %s", exc)

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


def get_correlation_summary(
    db: Session,
    allowed_project_ids: set[int],
    today: datetime | None = None,
) -> dict[str, Any]:
    """跨设备关联汇总（受数据范围约束），供大屏「今日新增跨设备共因」卡片。

    - ``today_cross_device``：事件窗 ``started_at`` 落在「今天」的跨设备共因数
      （按 UTC 日期边界，与前端把时间戳按北京墙钟直读展示的既有约定一致）；
    - ``cross_device_total`` / ``total``：累计跨设备 / 全部事件组；
    - ``by_level``：按最高级别计数。
    """
    empty = {
        "total": 0,
        "cross_device_total": 0,
        "today_cross_device": 0,
        "today_projects": 0,
        "by_level": {},
    }
    if not allowed_project_ids:
        return empty
    if today is None:
        today = datetime.now(timezone.utc)
    today_mid = today.replace(hour=0, minute=0, second=0, microsecond=0)

    rows = db.scalars(
        select(CorrelatedEventGroup).where(CorrelatedEventGroup.project_id.in_(allowed_project_ids))
    ).all()

    total = len(rows)
    cross = [r for r in rows if r.is_cross_device]
    today_cross = [r for r in cross if r.started_at and r.started_at >= today_mid]
    by_level: dict[str, int] = {}
    for r in rows:
        lv = r.max_level or "未知"
        by_level[lv] = by_level.get(lv, 0) + 1
    today_projects = len({r.project_id for r in today_cross if r.project_id})
    return {
        "total": total,
        "cross_device_total": len(cross),
        "today_cross_device": len(today_cross),
        "today_projects": today_projects,
        "by_level": by_level,
    }


def _decode_grid_cell(cell: str | None) -> tuple[float, float] | None:
    """反解 geo 网格键 ``"row,col"`` → (lng, lat) 网格中心（WGS-84）。

    与 :func:`_scope_of` 的编码 ``f"{round(lat/GRID):.0f},{round(lng/GRID):.0f}"`` 对称。
    """
    if not cell:
        return None
    try:
        row_s, col_s = cell.split(",")
        lat = int(round(float(row_s))) * GRID_SIZE_DEG
        lng = int(round(float(col_s))) * GRID_SIZE_DEG
        return lng, lat
    except (ValueError, AttributeError):
        return None


def _orm_to_norm(g: CorrelatedEventGroup) -> dict[str, Any]:
    """把 ORM 事件组行转为 ``_points_from_groups`` 需要的中间字典。"""
    return {
        "id": g.id,
        "project_id": g.project_id,
        "project_name": g.project_name,
        "spatial_type": g.spatial_type,
        "fence_name": g.fence_name,
        "grid_cell": g.grid_cell,
        "device_nos": _json_list(g.device_nos),
        "alarm_count": g.alarm_count,
        "device_count": g.device_count,
        "is_cross_device": g.is_cross_device,
        "max_level": g.max_level,
        "root_cause_hint": g.root_cause_hint,
    }


def get_correlation_heatmap(
    db: Session,
    allowed_project_ids: set[int],
    only_cross_device: bool = True,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """跨设备共因事件组的空间热力点（WGS-84，受数据范围约束）。

    为每个事件组解析一个代表经纬度：
    - ``geo`` 组：由 ``grid_cell`` 反解网格中心；
    - ``fence`` / ``device`` 组：取成员设备最新定位的均值（经 ``DeviceLocation``）。

    仅返回可解析出坐标的点。``weight`` 取告警数（供前端映射热力强度）。
    默认 ``only_cross_device=True``——热力图聚焦「跨设备共因」的空间聚集。
    """
    if not allowed_project_ids:
        return []
    stmt = select(CorrelatedEventGroup).where(
        CorrelatedEventGroup.project_id.in_(allowed_project_ids)
    )
    if only_cross_device:
        stmt = stmt.where(CorrelatedEventGroup.is_cross_device.is_(True))
    stmt = stmt.order_by(CorrelatedEventGroup.alarm_count.desc())
    if limit:
        stmt = stmt.limit(limit)
    groups = db.scalars(stmt).all()
    return _points_from_groups(db, [_orm_to_norm(g) for g in groups], limit)


def _points_from_groups(
    db: Session,
    norm_groups: list[dict[str, Any]],
    limit: int = 500,
) -> list[dict[str, Any]]:
    """把事件组中间字典解析为空间热力点（WGS-84，不含 gcj02）。

    ``norm_groups`` 元素键：``id`` / ``project_id`` / ``project_name`` /
    ``spatial_type`` / ``fence_name`` / ``grid_cell`` / ``device_nos``(list) /
    ``alarm_count`` / ``device_count`` / ``is_cross_device`` / ``max_level`` /
    ``root_cause_hint``。供滚动表热力与窗口化/对比重算复用，避免坐标解析逻辑重复。
    """
    if not norm_groups:
        return []

    need_devices: set[str] = set()
    for g in norm_groups:
        if g["spatial_type"] != "geo":
            for dno in g.get("device_nos") or []:
                if dno:
                    need_devices.add(dno)
    dev_loc: dict[str, tuple[float, float]] = {}
    if need_devices:
        loc_rows = db.execute(
            select(
                DeviceLocation.device_no,
                DeviceLocation.longitude,
                DeviceLocation.latitude,
            )
            .where(DeviceLocation.device_no.in_(need_devices))
            .distinct(DeviceLocation.device_no)
            .order_by(DeviceLocation.device_no, DeviceLocation.report_time.desc())
        ).all()
        for dno, lng, lat in loc_rows:
            if lng is not None and lat is not None:
                dev_loc[dno] = (lng, lat)

    points: list[dict[str, Any]] = []
    for g in norm_groups:
        lng: float | None = None
        lat: float | None = None
        if g["spatial_type"] == "geo":
            coord = _decode_grid_cell(g["grid_cell"])
            if coord:
                lng, lat = coord
        else:
            dnos = [d for d in (g.get("device_nos") or []) if d in dev_loc]
            if dnos:
                lng = sum(dev_loc[d][0] for d in dnos) / len(dnos)
                lat = sum(dev_loc[d][1] for d in dnos) / len(dnos)
        if lng is None or lat is None:
            continue
        points.append(
            {
                "id": g["id"],
                "project_id": g["project_id"],
                "project_name": g["project_name"],
                "spatial_type": g["spatial_type"],
                "fence_name": g["fence_name"],
                "grid_cell": g["grid_cell"],
                "lng": lng,
                "lat": lat,
                "weight": g["alarm_count"],
                "alarm_count": g["alarm_count"],
                "device_count": g["device_count"],
                "max_level": g["max_level"],
                "is_cross_device": g["is_cross_device"],
                "root_cause_hint": g["root_cause_hint"],
            }
        )
    return points


def get_correlation_heatmap_windowed(
    db: Session,
    allowed_project_ids: set[int],
    start: datetime,
    end: datetime,
    only_cross_device: bool = True,
    limit: int = 500,
    gap_minutes: int = 30,
) -> list[dict[str, Any]]:
    """在指定 ``[start, end]`` 窗口内对原始告警重算聚类，返回空间热力点（不落库）。

    用于「对比大屏关联热力」：可在任意历史时间窗内重算跨设备共因热力，不受派生
    滚动表（仅保留最近 ``correlation_window_hours``）的限制。
    """
    if not allowed_project_ids:
        return []
    alarms = db.scalars(
        select(Alarm).where(
            Alarm.project_id.in_(allowed_project_ids),
            Alarm.alarm_time >= start,
            Alarm.alarm_time <= end,
        )
    ).all()
    groups = _build_groups(db, list(alarms), gap_minutes)
    norm: list[dict[str, Any]] = []
    for i, g in enumerate(groups):
        if only_cross_device and not g["is_cross_device"]:
            continue
        norm.append({**g, "id": -(i + 1)})  # 合成 id（负数避免与 ORM id 冲突）
    return _points_from_groups(db, norm, limit)


def compare_correlation_windows(
    db: Session,
    allowed_project_ids: set[int],
    start_a: datetime,
    end_a: datetime,
    start_b: datetime,
    end_b: datetime,
    only_cross_device: bool = True,
    limit: int = 500,
    gap_minutes: int = 30,
) -> dict[str, Any]:
    """对比两个时间窗的关联热力：返回两窗各自热力点 + 变化摘要（新增/消失/增强减弱）。

    匹配键 = ``project_id|spatial_type|scope_key``，用于跨窗识别同一空间热点的演变。
    """
    if not allowed_project_ids:
        empty = {
            "start": "",
            "end": "",
            "total": 0,
            "cross_device_total": 0,
            "alarm_total": 0,
            "points": [],
        }
        return {
            "window_a": {**empty, "start": start_a.isoformat(), "end": end_a.isoformat()},
            "window_b": {**empty, "start": start_b.isoformat(), "end": end_b.isoformat()},
            "diff": {"new": [], "removed": [], "changed": []},
        }

    def _window(s: datetime, e: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        alarms = db.scalars(
            select(Alarm).where(
                Alarm.project_id.in_(allowed_project_ids),
                Alarm.alarm_time >= s,
                Alarm.alarm_time <= e,
            )
        ).all()
        groups = _build_groups(db, list(alarms), gap_minutes)
        norm: list[dict[str, Any]] = []
        for i, g in enumerate(groups):
            if only_cross_device and not g["is_cross_device"]:
                continue
            norm.append(
                {
                    **g,
                    "id": -(i + 1),
                    "key": f"{g['project_id']}|{g['spatial_type']}|{g['scope_key']}",
                }
            )
        return norm, _points_from_groups(db, norm, limit)

    def _scope_text(g: dict[str, Any]) -> str:
        if g["spatial_type"] == "fence":
            return g["fence_name"] or "围栏"
        if g["spatial_type"] == "geo":
            return f"地理网格 {g['grid_cell'] or ''}".strip()
        return "单机"

    def _summary(norm: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "total": len(norm),
            "cross_device_total": sum(1 for g in norm if g["is_cross_device"]),
            "alarm_total": sum(g["alarm_count"] for g in norm),
        }

    def _to_diff(g: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": g["key"],
            "project_id": g["project_id"],
            "project_name": g["project_name"],
            "spatial_type": g["spatial_type"],
            "scope_text": _scope_text(g),
            "fence_name": g["fence_name"],
            "grid_cell": g["grid_cell"],
            "weight": g["alarm_count"],
            "alarm_count": g["alarm_count"],
            "device_count": g["device_count"],
            "max_level": g["max_level"],
        }

    norm_a, points_a = _window(start_a, end_a)
    norm_b, points_b = _window(start_b, end_b)

    map_a = {g["key"]: g for g in norm_a}
    map_b = {g["key"]: g for g in norm_b}
    keys_a = set(map_a)
    keys_b = set(map_b)

    new_items = [_to_diff(map_b[k]) for k in keys_b - keys_a]
    removed_items = [_to_diff(map_a[k]) for k in keys_a - keys_b]
    changed_items = []
    for k in keys_a & keys_b:
        ga, gb = map_a[k], map_b[k]
        delta = gb["alarm_count"] - ga["alarm_count"]
        changed_items.append(
            {
                **_to_diff(gb),
                "a_weight": ga["alarm_count"],
                "b_weight": gb["alarm_count"],
                "delta": delta,
                "a_max_level": ga["max_level"],
                "b_max_level": gb["max_level"],
                "a_device_count": ga["device_count"],
                "b_device_count": gb["device_count"],
            }
        )

    return {
        "window_a": {
            "start": start_a.isoformat(),
            "end": end_a.isoformat(),
            "points": points_a,
            **_summary(norm_a),
        },
        "window_b": {
            "start": start_b.isoformat(),
            "end": end_b.isoformat(),
            "points": points_b,
            **_summary(norm_b),
        },
        "diff": {
            "new": new_items,
            "removed": removed_items,
            "changed": changed_items,
        },
    }


def get_correlation_trend(
    db: Session,
    allowed_project_ids: set[int],
    days: int = 30,
    only_cross_device: bool = False,
    today: datetime | None = None,
) -> list[dict[str, Any]]:
    """关联事件组每日计数趋势（受数据范围约束），供 sparkline 绘制。

    按 ``started_at`` 的 UTC 日期分桶；返回最近 ``days`` 天（含今天）的逐日计数，
    缺数据的日期补 0，保证曲线连续。``only_cross_device=True`` 时仅统计跨设备共因。
    """
    if not allowed_project_ids:
        return []
    if today is None:
        today = datetime.now(timezone.utc)
    today_mid = today.replace(hour=0, minute=0, second=0, microsecond=0)
    start = today_mid - timedelta(days=days - 1)

    rows = db.scalars(
        select(CorrelatedEventGroup).where(CorrelatedEventGroup.project_id.in_(allowed_project_ids))
    ).all()

    buckets: dict[str, int] = defaultdict(int)
    for r in rows:
        if only_cross_device and not r.is_cross_device:
            continue
        if not r.started_at:
            continue
        if r.started_at < start or r.started_at > today_mid + timedelta(days=1):
            continue
        d = r.started_at.astimezone(timezone.utc).date().isoformat()
        buckets[d] += 1

    series: list[dict[str, Any]] = []
    cur = start
    for _ in range(days):
        d = cur.date().isoformat()
        series.append({"date": d, "count": buckets.get(d, 0)})
        cur += timedelta(days=1)
    return series
