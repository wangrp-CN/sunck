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
