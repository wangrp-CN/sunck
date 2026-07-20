"""大屏路由：全局监控聚合统计与最近告警流（对应需求 §2.3 监控大屏）。

统计与告警流均按当前用户的部门数据范围（data_scope）隔离：
- 超级管理员或 data_scope==1 可见全部；
- 其余用户仅可见所属部门（及其下级部门）或「仅本人」范围内的数据。
权限 dashboard:view。前端携带 JWT 即可自动生效，无需额外改造。
"""

import calendar
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import LOCAL_TZ, day_end_local, day_start_local, ensure_aware_local, today_local
from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.model.alarm import Alarm
from app.model.device import (
    AntiIntrusionDevice,
    LocateDevice,
    TrainApproachDevice,
)
from app.model.fence import ElectronicFence
from app.model.job import WorkPlan, WorkPlanFence
from app.model.person import Machine, Person
from app.model.project import Project
from app.model.realtime import DeviceLocation
from app.service.alarm_service import (
    _period_key,
    aggregate_alarms_sql,
)
from app.service.location_service import latest_locations

router = APIRouter(tags=["大屏"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "dashboard", "status": "ready"}


# 三类设备：device_type 编码 -> ORM 模型
_DEVICE_TYPES = [
    ("locate", LocateDevice),
    ("anti_intrusion", AntiIntrusionDevice),
    ("train_approach", TrainApproachDevice),
]


def _count_active(db: Session, model, scope: DataScope) -> int:
    """统计未删除记录数，施加部门数据隔离。"""
    stmt = apply_data_scope(
        select(func.count()).select_from(model).where(model.is_deleted.is_(False)),
        model,
        scope,
    )
    return db.scalar(stmt) or 0


def _count_online(db: Session, model, scope: DataScope) -> int:
    """统计在线设备数，施加部门数据隔离。"""
    stmt = apply_data_scope(
        select(func.count())
        .select_from(model)
        .where(model.is_deleted.is_(False), model.status == "在线"),
        model,
        scope,
    )
    return db.scalar(stmt) or 0


def _scope_project_ids(db: Session, scope: DataScope) -> set[int] | None:
    """返回当前用户可见的项目 ID 集合；is_all 返回 None（与 realtime 同口径）。"""
    if scope.is_all or not scope.dept_ids:
        return None
    ids = db.scalars(select(Project.id).where(Project.dept_id.in_(scope.dept_ids))).all()
    return set(ids)


def _compute_device_stats(db: Session, scope: DataScope, s: datetime, e: datetime) -> dict:
    """设备在线率（实时心跳）+ 区间活跃设备数（按所选窗口周期联动）。

    - total：三类设备表未删除记录合计（部门隔离）。
    - online：以 latest_locations 的最新上报时间为准，距 now 不超过
      settings.online_threshold_seconds 视为在线（与 /online-status 同口径）。
    - online_rate：online / total（百分比，1 位小数）。
    - window_active：窗口 [s,e] 内至少上报一次的设备数（随窗口周期联动）。
    """
    total = 0
    for _, model in _DEVICE_TYPES:
        total += _count_active(db, model, scope)
    allowed = _scope_project_ids(db, scope)
    threshold = settings.online_threshold_seconds
    now = datetime.now(timezone.utc)
    online = 0
    for r in latest_locations(db):
        if allowed is not None and r.project_id not in allowed:
            continue
        last = r.report_time
        if last is None:
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = (now - last).total_seconds()
        if age <= threshold:
            online += 1
    online_rate = round(online / total * 100, 1) if total else 0.0
    stmt = select(func.count(func.distinct(DeviceLocation.device_no))).where(
        DeviceLocation.report_time >= s, DeviceLocation.report_time <= e
    )
    if allowed is not None:
        stmt = stmt.where(DeviceLocation.project_id.in_(allowed))
    window_active = db.scalar(stmt) or 0
    return {
        "total": total,
        "online": online,
        "online_rate": online_rate,
        "window_active": window_active,
    }


def _compute_fence_stats(db: Session, scope: DataScope, s: datetime, e: datetime) -> dict:
    """围栏统计 + 窗口内监控围栏数（按所选窗口周期联动）。

    - total：未删除围栏数（部门隔离）。
    - enabled：启用中的围栏数。
    - by_type：按 fence_type 分组计数（None 记为「未分类」）。
    - monitored_in_window：绑定到「在窗口 [s,e] 内激活」作业计划的围栏数；
      计划激活判定：is_start=True 且 status='执行中' 且时间窗与 [s,e] 重叠。
    """
    total = _count_active(db, ElectronicFence, scope)
    stmt_en = apply_data_scope(
        select(func.count())
        .select_from(ElectronicFence)
        .where(ElectronicFence.is_deleted.is_(False), ElectronicFence.enabled.is_(True)),
        ElectronicFence,
        scope,
    )
    enabled = db.scalar(stmt_en) or 0
    stmt_type = apply_data_scope(
        select(ElectronicFence.fence_type, func.count())
        .where(ElectronicFence.is_deleted.is_(False))
        .group_by(ElectronicFence.fence_type),
        ElectronicFence,
        scope,
    )
    by_type = [{"type": (t or "未分类"), "count": c} for t, c in db.execute(stmt_type).all()]
    allowed = _scope_project_ids(db, scope)
    stmt_mon = (
        select(func.count(func.distinct(WorkPlanFence.fence_id)))
        .join(WorkPlan, WorkPlan.id == WorkPlanFence.plan_id)
        .where(
            WorkPlan.is_start.is_(True),
            WorkPlan.status == "执行中",
            WorkPlan.is_deleted.is_(False),
            (WorkPlan.plan_start.is_(None)) | (WorkPlan.plan_start <= e),
            (WorkPlan.plan_end.is_(None)) | (WorkPlan.plan_end >= s),
        )
    )
    if allowed is not None:
        stmt_mon = stmt_mon.join(
            ElectronicFence, ElectronicFence.id == WorkPlanFence.fence_id
        ).where(
            ElectronicFence.project_id.in_(allowed),
            ElectronicFence.is_deleted.is_(False),
        )
    monitored = db.scalar(stmt_mon) or 0
    return {
        "total": total,
        "enabled": enabled,
        "monitored_in_window": monitored,
        "by_type": by_type,
    }


@router.get(
    "/stats",
    summary="监控大屏聚合统计",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dashboard:view"))],
)
def stats(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    granularity: str | None = Query(
        None,
        description="趋势聚合粒度：day|week|month（与告警报表/导出同一分桶口径，保证周期联动一致）",
    ),
    start: str | None = Query(None, description="趋势时间窗起点 ISO（缺省按粒度给默认窗）"),
    end: str | None = Query(None, description="趋势时间窗终点 ISO"),
) -> ApiResponse:
    """返回大屏所需的各项计数与分布，按当前用户部门数据范围隔离。

    趋势图支持按 天/周/月 + 时间范围联动：传入 granularity(+start/end) 时，
    alarm_trend_period 为对应窗口内按周期聚合的分布（与 /alarms/report 的 by_period
    完全一致），供前端「趋势图按周期切换 + 仪表盘一键导出历史快照」联动使用。
    未传参数时回退到原「近 7 天日趋势」(alarm_trend_7d) 以保证向后兼容。
    """
    projects = _count_active(db, Project, scope)
    persons = _count_active(db, Person, scope)
    machines = _count_active(db, Machine, scope)
    fences = _count_active(db, ElectronicFence, scope)

    device_by_type: list[dict] = []
    devices_total = 0
    devices_online = 0
    for dtype, model in _DEVICE_TYPES:
        total = _count_active(db, model, scope)
        online = _count_online(db, model, scope)
        devices_total += total
        devices_online += online
        device_by_type.append({"device_type": dtype, "count": total})

    stmt_alarms_total = apply_data_scope(select(func.count()).select_from(Alarm), Alarm, scope)
    alarms_total = db.scalar(stmt_alarms_total) or 0

    today_start = day_start_local()  # aware 北京日界，与 timestamptz 列比较不依赖 session tz
    stmt_alarms_today = apply_data_scope(
        select(func.count()).select_from(Alarm).where(Alarm.alarm_time >= today_start),
        Alarm,
        scope,
    )
    alarms_today = db.scalar(stmt_alarms_today) or 0

    # 趋势图周期联动：提前计算窗口内 rows 与聚合，供计数卡 / 级别 / 处置分布卡复用，
    # 保证整屏（趋势柱状图 + 区间/本周期计数 + 级别/处置分布）与所选周期完全一致。
    gran = (granularity or "day").lower()
    if gran not in ("day", "week", "month"):
        raise BusinessError("granularity 仅支持 day|week|month", code=400)
    s, e = _resolve_trend_window(gran, start, end)
    agg = aggregate_alarms_sql(db, scope, start=s, end=e, granularity=gran)
    trend_period = agg["by_period"]
    trend_start = s.strftime("%Y-%m-%d")
    trend_end = e.strftime("%Y-%m-%d")

    # 计数卡周期联动：与趋势图同一分桶口径，保证卡片数字与柱状图逐桶自洽
    # - alarms_window: 所选时间窗内告警合计（= 各周期桶计数之和）
    # - alarms_current_period: 当前周期（窗口末端所属周期）的告警数，空桶记 0
    period_map = {p["period"]: p["count"] for p in trend_period}
    current_period = _period_key(e.isoformat(), gran)
    alarms_window = sum(period_map.values())
    alarms_current_period = period_map.get(current_period, 0)

    # 告警级别 / 处置状态分布：复用窗口内 rows 聚合（agg.by_level/by_handle_status 与
    # granularity 无关，只取决于窗口），与趋势图、计数卡同口径联动。
    alarm_by_level = [
        {"level": it["key"] or "未知", "count": it["count"]} for it in agg["by_level"]
    ]
    alarm_by_handle = [
        {"status": it["key"] or "未知", "count": it["count"]} for it in agg["by_handle_status"]
    ]

    stmt_project = apply_data_scope(
        select(Project.status, func.count())
        .where(Project.is_deleted.is_(False))
        .group_by(Project.status),
        Project,
        scope,
    )
    project_rows = db.execute(stmt_project).all()
    project_status = [{"status": st or "未知", "count": c} for st, c in project_rows]

    # 设备在线率 / 围栏统计：与趋势图同一窗口 [s,e] 周期联动，部门隔离一致
    device_stats = _compute_device_stats(db, scope, s, e)
    fence_stats = _compute_fence_stats(db, scope, s, e)

    # 近 7 天每日告警趋势
    trend: list[dict] = []
    for i in range(6, -1, -1):
        d = today_local() - timedelta(days=i)
        d_start = day_start_local(d)  # aware 北京日界
        d_end = day_end_local(d)
        stmt_trend = apply_data_scope(
            select(func.count())
            .select_from(Alarm)
            .where(Alarm.alarm_time >= d_start, Alarm.alarm_time <= d_end),
            Alarm,
            scope,
        )
        c = db.scalar(stmt_trend) or 0
        trend.append({"date": d.strftime("%m-%d"), "count": c})

    # 趋势图周期联动聚合已前移至计数卡/分布卡之前（见上文 agg），此处直接组装返回。
    return ApiResponse.success(
        data={
            "counts": {
                "projects": projects,
                "devices": devices_total,
                "devices_online": devices_online,
                "devices_offline": devices_total - devices_online,
                "persons": persons,
                "machines": machines,
                "fences": fences,
                "alarms": alarms_total,
                "alarms_today": alarms_today,
                "alarms_window": alarms_window,
                "alarms_current_period": alarms_current_period,
            },
            "device_by_type": device_by_type,
            "alarm_by_level": alarm_by_level,
            "alarm_by_handle": alarm_by_handle,
            "project_status": project_status,
            "alarm_trend_7d": trend,
            "alarm_trend_period": trend_period,
            "trend_granularity": gran,
            "trend_start": trend_start,
            "trend_end": trend_end,
            "current_period": current_period,
            "device_stats": device_stats,
            "fence_stats": fence_stats,
        },
        message="查询成功",
    )


def _resolve_trend_window(
    gran: str, start: str | None, end: str | None
) -> tuple[datetime, datetime]:
    """解析趋势时间窗；未传则按粒度给默认窗（day=近7天/week=近13周/month=近12月）。"""
    if start and end:
        try:
            # 用户传入的 ISO 若缺时区，按业务时区（Asia/Shanghai）补全为 aware，
            # 与 timestamptz 列比较不依赖 PG session tz。
            s = ensure_aware_local(datetime.fromisoformat(start))
            e = ensure_aware_local(datetime.fromisoformat(end))
        except ValueError:
            raise BusinessError("趋势时间窗格式非法（应为 ISO 8601）", code=400)
        if s > e:
            raise BusinessError("趋势起始时间不能晚于结束时间", code=400)
        return s, e
    today = today_local()
    if gran == "month":
        # 最近 12 个自然月（含本月）
        sy, sm = today.year, today.month
        for _ in range(11):
            if sm == 1:
                sy, sm = sy - 1, 12
            else:
                sm -= 1
        s = datetime(sy, sm, 1, tzinfo=LOCAL_TZ)
        last = calendar.monthrange(today.year, today.month)[1]
        e = datetime(today.year, today.month, last, 23, 59, 59, 999999, tzinfo=LOCAL_TZ)
    elif gran == "week":
        monday = today - timedelta(days=today.weekday())
        s = day_start_local(monday - timedelta(weeks=12))
        e = day_end_local(monday)
    else:  # day
        s = day_start_local(today - timedelta(days=6))
        e = day_end_local(today)
    return s, e


@router.get(
    "/recent-alarms",
    summary="最近告警流",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dashboard:view"))],
)
def recent_alarms(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    limit: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    """返回最近 limit 条告警（按时间倒序），按当前用户部门数据范围隔离。"""
    stmt = apply_data_scope(
        select(Alarm).order_by(Alarm.alarm_time.desc().nullslast()).limit(limit),
        Alarm,
        scope,
    )
    rows = db.scalars(stmt).all()
    items = [
        {
            "id": a.id,
            "alarm_type": a.alarm_type,
            "device_type": a.device_type,
            "device_name": a.device_name,
            "device_no": a.device_no,
            "alarm_level": a.alarm_level,
            "alarm_info": a.alarm_info,
            "alarm_status": a.alarm_status,
            "handle_status": a.handle_status,
            "fence_name": a.fence_name,
            "alarm_time": a.alarm_time.isoformat() if a.alarm_time else None,
            "project_id": a.project_id,
        }
        for a in rows
    ]
    return ApiResponse.success(data={"items": items, "total": len(items)}, message="查询成功")
