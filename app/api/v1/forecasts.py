"""风险预测路由（Phase 5 智能化预测 M1+M2）。

权限：
- forecast:view  预测列表 / 预览 / 重算

端点：
- GET  /            预测列表（项目/指标/scope 过滤；数据范围经 project 隔离）
- GET  /preview     单对象序列预览：历史点+拟合+预测点+置信带（前端画图用）
- POST /recompute   重算（全部或指定项目）并返回最新结果
"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cache import get_cached_json, set_cached_json
from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db, get_read_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.responses import ApiResponse
from app.model.forecast import Forecast
from app.model.project import Project
from app.model.system import User
from app.schema.forecast import ForecastOut
from app.service import forecast_service as svc
from app.service import prediction_hitrate as hitrate_svc

router = APIRouter(tags=["风险预测"])


def _can_access_project(db, scope: DataScope, project_id: int | None) -> bool:
    """预览端点的数据范围校验：项目须在当前用户可见范围内。"""
    if scope.is_all:
        return True
    if project_id is None:
        return False
    stmt = apply_data_scope(select(Project.id).where(Project.id == project_id), Project, scope)
    return db.scalars(stmt).first() is not None


@router.get(
    "/",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("forecast:view"))],
)
def list_forecasts(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = Query(None, description="按项目过滤"),
    scope_type: str | None = Query(None, description="project|device"),
    metric: str | None = Query(None, description="risk_index|health_score"),
) -> ApiResponse:
    stmt = select(Forecast)
    if project_id is not None:
        stmt = stmt.where(Forecast.project_id == project_id)
    if scope_type:
        stmt = stmt.where(Forecast.scope_type == scope_type)
    if metric:
        stmt = stmt.where(Forecast.metric == metric)
    stmt = apply_data_scope(stmt, Forecast, scope)
    rows = db.scalars(stmt.order_by(Forecast.forecast_value.desc())).all()
    return ApiResponse.success(
        data={"items": [ForecastOut.model_validate(r).model_dump() for r in rows]}
    )


@router.get(
    "/preview",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("forecast:view"))],
)
def preview(
    ref_id: str = Query(..., description="project.id 或 device_no"),
    scope_type: str = Query("project", description="project|device"),
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    horizon_days: int | None = Query(None, ge=1, le=90, description="预测跨度(天)"),
    history_days: int | None = Query(None, ge=3, le=365, description="回看窗口(天)"),
) -> ApiResponse:
    """历史序列 + 拟合参数 + 预测点 + 置信带（M2，供驾驶舱预测卡画图）。

    样本不足时 forecast 为 null，series 照常返回（前端提示"数据积累中"）。
    """
    if scope_type not in ("project", "device"):
        return ApiResponse.fail(code=400, message="scope_type 须为 project|device")
    # 数据范围校验：解析归属项目
    if scope_type == "project":
        try:
            pid: int | None = int(ref_id)
        except ValueError:
            return ApiResponse.fail(code=400, message="project 预览的 ref_id 须为项目 ID")
    else:
        pid = svc._device_project_id(db, ref_id)
    if not _can_access_project(db, scope, pid):
        return ApiResponse.fail(code=403, message="对象不存在或无权访问")
    data = svc.preview_forecast(
        db, scope_type, ref_id, horizon_days=horizon_days, history_days=history_days
    )
    return ApiResponse.success(data=data)


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


@router.get(
    "/hit-rate",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("forecast:view"))],
)
def hit_rate(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_read_db),
    scope: DataScope = Depends(get_data_scope),
    days: int = Query(30, ge=7, le=365, description="统计窗口(天)"),
    project_id: int | None = Query(None, ge=1, description="按项目下钻"),
    metric: str | None = Query(None, description="risk_index|health_score"),
) -> ApiResponse:
    """预测命中率报表：度量预测性预警的准确度（命中率/平均提前量/误报/待验证）。

    仅统计「实际触发预测性预警的预测」（越阈），窗口已结束者计入命中率分母，
    窗口未结束者列为 pending。数据范围隔离；复用 3s 响应缓存。
    """
    _cached = get_cached_json(current_user.id, request.url.path, request.url.query)
    if _cached is not None:
        return ApiResponse(**_cached)

    data = hitrate_svc.compute_prediction_hitrate(
        db, scope, days=days, project_id=project_id, metric=metric
    )
    resp = ApiResponse.success(data=data)
    set_cached_json(current_user.id, request.url.path, request.url.query, resp.model_dump())
    return resp
