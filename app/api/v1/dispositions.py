"""告警处置记录路由（处置效果闭环）。

- GET  /            处置记录列表（项目/处置人/结果/时间窗过滤 + 分页 + 数据隔离）
- GET  /stats       处置效能统计（闭环率、平均闭环时长、按处置人/项目/结果分布）
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope
from app.core.database import get_db
from app.core.deps import get_data_scope, require_permissions
from app.core.responses import ApiResponse
from app.service import disposition_service as svc

router = APIRouter(tags=["告警处置"])


@router.get(
    "",
    summary="处置记录列表",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm:list"))],
)
def list_dispositions(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = Query(None, description="按项目过滤"),
    handler_id: int | None = Query(None, description="按处置人过滤"),
    outcome: str | None = Query(None, description="按处置结果过滤"),
    start: datetime | None = Query(None, description="起始时间(ISO8601)"),
    end: datetime | None = Query(None, description="结束时间(ISO8601)"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> ApiResponse:
    """按条件分页查询处置记录，施加部门数据隔离。"""
    total, items = svc.list_dispositions(
        db,
        scope,
        project_id=project_id,
        handler_id=handler_id,
        outcome=outcome,
        start=start,
        end=end,
        page=page,
        size=size,
    )
    return ApiResponse.success(
        data={
            "total": total,
            "items": [svc.to_disposition_out(d) for d in items],
            "page": page,
            "size": size,
        }
    )


@router.get(
    "/stats",
    summary="处置效能统计",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm:list"))],
)
def disposition_stats(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = Query(None, description="按项目下钻"),
    days: int = Query(30, ge=1, le=365, description="统计窗口(天)"),
) -> ApiResponse:
    """聚合处置效能：闭环率、平均闭环时长、按处置人/项目/结果分布。"""
    data = svc.disposition_stats(db, scope, project_id=project_id, days=days)
    return ApiResponse.success(data=data)
