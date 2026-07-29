"""风险预测路由（Phase 5 智能化预测 M1）。

权限：
- forecast:view  预测列表 / 单项目重算

端点：
- GET  /            预测列表（可按项目/指标过滤；数据范围经 project 隔离）
- POST /recompute   重算（全部或指定项目）并返回最新结果
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import get_data_scope, require_permissions
from app.core.responses import ApiResponse
from app.model.forecast import Forecast
from app.schema.forecast import ForecastOut
from app.service import forecast_service as svc

router = APIRouter(tags=["风险预测"])


@router.get(
    "/",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("forecast:view"))],
)
def list_forecasts(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = Query(None, description="按项目过滤"),
    metric: str | None = Query(None, description="按指标过滤(risk_index)"),
) -> ApiResponse:
    stmt = select(Forecast)
    if project_id is not None:
        stmt = stmt.where(Forecast.project_id == project_id)
    if metric:
        stmt = stmt.where(Forecast.metric == metric)
    stmt = apply_data_scope(stmt, Forecast, scope)
    rows = db.scalars(stmt.order_by(Forecast.forecast_value.desc())).all()
    return ApiResponse.success(
        data={"items": [ForecastOut.model_validate(r).model_dump() for r in rows]}
    )


@router.post(
    "/recompute",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("forecast:view"))],
)
def recompute(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = Query(None, description="仅重算指定项目；缺省为全部"),
    horizon_days: int | None = Query(None, ge=1, le=90, description="预测跨度(天)"),
) -> ApiResponse:
    """基于最新快照序列重算预测并落库，返回统计。"""
    if project_id is not None:
        data = svc.compute_forecast(db, project_id, horizon_days=horizon_days)
        if data is None:
            return ApiResponse.fail(code=1001, message="快照样本不足，无法预测")
        obj = svc.upsert_forecast(db, data)
        db.commit()
        return ApiResponse.success(data=ForecastOut.model_validate(obj).model_dump())
    stats = svc.run_forecasts(db, horizon_days=horizon_days)
    db.commit()
    return ApiResponse.success(data=stats)
