"""指标快照路由（智能核心 v2）。

- ``GET /risk-trend``：项目风险指数时间序列（受数据范围约束）；
- ``GET /health-trend``：单设备健康分时间序列；
- ``GET /risk-latest``：对比大屏用，各项目最新风险快照（受数据范围约束）；
- ``POST /snapshot/run``：手动触发一次快照（仅超级管理员）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db, get_read_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.model.project import Project
from app.model.system import User
from app.service import alarm_correlation as corr_svc
from app.service import metrics_snapshot as svc
from app.service import risk_alert as alert_svc

router = APIRouter()


@router.get("/risk-trend", dependencies=[Depends(require_permissions("dashboard:view"))])
def risk_trend(
    db: Session = Depends(get_read_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int = Query(..., description="项目ID"),
    days: int = Query(30, ge=1, le=365, description="回溯天数"),
):
    """项目风险指数时间序列（受数据范围约束）。"""
    proj_stmt = apply_data_scope(select(Project.id).where(Project.id == project_id), Project, scope)
    if db.scalar(proj_stmt) is None:
        raise BusinessError("项目不存在或无权限", code=404)
    series = svc.get_risk_trend(db, project_id, days)
    return ApiResponse.success(data={"project_id": project_id, "days": days, "series": series})


@router.get("/health-trend", dependencies=[Depends(require_permissions("dashboard:view"))])
def health_trend(
    db: Session = Depends(get_read_db),
    device_no: str = Query(..., description="设备编号"),
    days: int = Query(30, ge=1, le=365, description="回溯天数"),
):
    """单设备健康分时间序列。"""
    series = svc.get_health_trend(db, device_no, days)
    return ApiResponse.success(data={"device_no": device_no, "days": days, "series": series})


@router.get("/risk-latest", dependencies=[Depends(require_permissions("dashboard:view"))])
def risk_latest(
    db: Session = Depends(get_read_db),
    scope: DataScope = Depends(get_data_scope),
    limit: int = Query(50, ge=1, le=200),
):
    """对比大屏用：各项目最新风险快照（受数据范围约束，按风险指数降序）。"""
    proj_stmt = apply_data_scope(
        select(Project.id).where(Project.is_deleted.is_(False)), Project, scope
    )
    allowed = [row[0] for row in db.execute(proj_stmt).all()]
    if not allowed:
        return ApiResponse.success(data={"total": 0, "items": []})
    items = svc.get_latest_risk_snapshots(db, project_ids=allowed)
    items.sort(key=lambda x: -(x["risk_index"] or 0))
    return ApiResponse.success(data={"total": len(items), "items": items[:limit]})


@router.post("/snapshot/run")
def snapshot_run(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
    hours: int = Query(24, ge=1, le=720, description="设备健康统计窗口(小时)"),
    days: int = Query(7, ge=1, le=90, description="项目风险统计窗口(天)"),
):
    """手动触发一次风险/健康快照（仅超级管理员）。"""
    if not current.is_superuser:
        raise BusinessError("仅超级管理员可手动触发快照", code=403)
    result = svc.run_snapshot(db, hours=hours, days=days)
    return ApiResponse.success(data=result, message="快照已生成")


@router.get("/risk-alerts", dependencies=[Depends(require_permissions("dashboard:view"))])
def risk_alerts(
    db: Session = Depends(get_read_db),
    scope: DataScope = Depends(get_data_scope),
):
    """当前越阈项目列表（受数据范围约束，按风险指数降序）。

    每项含 ``is_new``（上升沿新越阈标记），供对比大屏 / 预警面板高亮。
    """
    proj_stmt = apply_data_scope(
        select(Project.id).where(Project.is_deleted.is_(False)), Project, scope
    )
    allowed = {row[0] for row in db.execute(proj_stmt).all()}
    if not allowed:
        return ApiResponse.success(data={"total": 0, "items": []})
    breaches = alert_svc.evaluate_risk_alerts(db)
    items = [b for b in breaches if b["project_id"] in allowed]
    return ApiResponse.success(data={"total": len(items), "items": items})


@router.post("/risk-alerts/notify")
def risk_alerts_notify(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """手动触发一次「新越阈」项目站内信预警（仅超级管理员）。

    基于 RiskAlertState 去重：同一越阈快照不会重复下发（降噪）。
    返回实际触发通知的项目数。
    """
    if not current.is_superuser:
        raise BusinessError("仅超级管理员可手动触发预警通知", code=403)
    sent = alert_svc.alert_newly_breached(db)
    return ApiResponse.success(data={"notified_projects": sent}, message="预警通知已下发")


# ---------------------------------------------------------------------------
# 跨设备根因关联（#77）
# ---------------------------------------------------------------------------


@router.get("/correlations", dependencies=[Depends(require_permissions("dashboard:view"))])
def correlations(
    db: Session = Depends(get_read_db),
    scope: DataScope = Depends(get_data_scope),
    only_cross_device: bool = Query(False, description="仅返回跨设备关联组"),
    limit: int = Query(100, ge=1, le=500, description="返回条数上限"),
):
    """当前跨设备根因关联事件组（受数据范围约束，按告警数降序）。

    每个事件组代表「同项目 + 同空间范围 + 时间近邻」的一簇告警，
    用于揭示多台设备在同一围栏 / 同一地理区域短时集中告警的共因。
    """
    proj_stmt = apply_data_scope(
        select(Project.id).where(Project.is_deleted.is_(False)), Project, scope
    )
    allowed = {row[0] for row in db.execute(proj_stmt).all()}
    if not allowed:
        return ApiResponse.success(data={"total": 0, "items": []})
    items = corr_svc.get_correlations(db, allowed, only_cross_device=only_cross_device, limit=limit)
    return ApiResponse.success(data={"total": len(items), "items": items})


@router.get(
    "/correlations/summary",
    dependencies=[Depends(require_permissions("dashboard:view"))],
)
def correlations_summary(
    db: Session = Depends(get_read_db),
    scope: DataScope = Depends(get_data_scope),
):
    """跨设备关联汇总（受数据范围约束）。

    用于大屏「今日新增跨设备共因」卡片：今日跨设备共因数、累计跨设备、按级别计数等。
    """
    proj_stmt = apply_data_scope(
        select(Project.id).where(Project.is_deleted.is_(False)), Project, scope
    )
    allowed = {row[0] for row in db.execute(proj_stmt).all()}
    summary = corr_svc.get_correlation_summary(db, allowed)
    return ApiResponse.success(data=summary)


@router.get(
    "/correlations/trend",
    dependencies=[Depends(require_permissions("dashboard:view"))],
)
def correlations_trend(
    db: Session = Depends(get_read_db),
    scope: DataScope = Depends(get_data_scope),
    days: int = Query(30, ge=1, le=365, description="回溯天数"),
    only_cross_device: bool = Query(False, description="仅统计跨设备共因"),
):
    """关联事件组每日计数趋势（受数据范围约束），供 sparkline 绘制。

    按事件窗 ``started_at`` 的 UTC 日期分桶；返回最近 ``days`` 天的逐日计数。
    """
    proj_stmt = apply_data_scope(
        select(Project.id).where(Project.is_deleted.is_(False)), Project, scope
    )
    allowed = {row[0] for row in db.execute(proj_stmt).all()}
    series = corr_svc.get_correlation_trend(
        db, allowed, days=days, only_cross_device=only_cross_device
    )
    return ApiResponse.success(
        data={"days": days, "only_cross_device": only_cross_device, "series": series}
    )


@router.get(
    "/correlations/{group_id}/members",
    dependencies=[Depends(require_permissions("dashboard:view"))],
)
def correlation_members(
    group_id: int,
    db: Session = Depends(get_read_db),
    scope: DataScope = Depends(get_data_scope),
):
    """某事件组的成员告警明细（受数据范围约束），供前端展开行查看。"""
    members = corr_svc.get_correlation_members(db, group_id, scope)
    if members is None:
        raise BusinessError("事件组不存在", code=404)
    return ApiResponse.success(data={"group_id": group_id, "total": len(members), "items": members})


@router.post("/correlations/run")
def correlations_run(
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
    window_hours: int = Query(24, ge=1, le=720, description="回溯窗口(小时)"),
    gap_minutes: int = Query(30, ge=1, le=1440, description="时间窗聚类间隔(分钟)"),
):
    """手动触发一次跨设备关联计算（仅超级管理员）。

    全量重算 ``correlated_event_group`` 派生表；快照定时任务每日也会自动执行。
    """
    if not current.is_superuser:
        raise BusinessError("仅超级管理员可手动触发关联计算", code=403)
    result = corr_svc.run_correlations(
        db, window_hours=window_hours, cluster_gap_minutes=gap_minutes
    )
    return ApiResponse.success(data=result, message="关联计算完成")
