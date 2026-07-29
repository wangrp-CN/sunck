"""根因派单闭环路由（#80）。

权限：
- dispatch:list  列表/详情/统计/枚举
- dispatch:create 创建派单
- dispatch:handle 状态流转(start/close/reopen) 与改派

端点：
- GET    /options            枚举选项（dispatch:list）
- GET    /stats             统计（dispatch:list）
- GET    /                  分页列表（dispatch:list）
- GET    /{id}              详情（dispatch:list）
- POST   /                  创建（dispatch:create）
- PATCH  /{id}              状态流转（dispatch:handle）
- POST   /{id}/reassign     改派（dispatch:handle）
"""

from fastapi import APIRouter, Depends, Query

from app.core.data_scope import DataScope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.responses import ApiResponse
from app.model.system import User
from app.schema.dispatch import (
    DISPATCH_LEVEL_OPTIONS,
    DISPATCH_SOURCE_OPTIONS,
    DISPATCH_STATUS_OPTIONS,
    DispatchAction,
    DispatchCreate,
    DispatchOut,
    DispatchReassign,
)
from app.service import dispatch_service as svc

router = APIRouter(tags=["根因派单"])


@router.get(
    "/options",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dispatch:list"))],
)
def options() -> ApiResponse:
    """派单枚举选项（状态/来源/级别）。"""
    return ApiResponse.success(
        data={
            "statuses": DISPATCH_STATUS_OPTIONS,
            "sources": DISPATCH_SOURCE_OPTIONS,
            "levels": DISPATCH_LEVEL_OPTIONS,
        }
    )


@router.get(
    "/stats",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dispatch:list"))],
)
def stats(db=Depends(get_db), scope: DataScope = Depends(get_data_scope)) -> ApiResponse:
    return ApiResponse.success(data=svc.dispatch_stats(db, scope))


@router.get(
    "/", response_model=ApiResponse, dependencies=[Depends(require_permissions("dispatch:list"))]
)
def list_orders(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    status: str | None = Query(None, description="状态过滤"),
    source_type: str | None = Query(None, description="来源过滤"),
    project_id: int | None = Query(None, description="项目过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> ApiResponse:
    result = svc.list_orders(
        db,
        scope,
        status=status,
        source_type=source_type,
        project_id=project_id,
        page=page,
        size=size,
    )
    return ApiResponse.success(
        data={
            "total": result["total"],
            "items": [DispatchOut.model_validate(o).model_dump() for o in result["items"]],
            "page": result["page"],
            "size": result["size"],
        }
    )


@router.get(
    "/{order_id}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dispatch:list"))],
)
def detail(
    order_id: int, db=Depends(get_db), scope: DataScope = Depends(get_data_scope)
) -> ApiResponse:
    order = svc.get_order(db, scope, order_id)
    if order is None:
        return ApiResponse.fail(code=404, message="派单不存在或无权访问")
    return ApiResponse.success(data=DispatchOut.model_validate(order).model_dump())


@router.post(
    "/", response_model=ApiResponse, dependencies=[Depends(require_permissions("dispatch:create"))]
)
def create(
    payload: DispatchCreate,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    order = svc.create_order(db, scope, user.id, payload)
    db.commit()
    return ApiResponse.success(data=DispatchOut.model_validate(order).model_dump())


@router.patch(
    "/{order_id}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dispatch:handle"))],
)
def action(
    order_id: int,
    payload: DispatchAction,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    order = svc.apply_action(db, scope, order_id, payload.action, payload.note, user.id)
    if order is None:
        return ApiResponse.fail(code=404, message="派单不存在或无权访问")
    db.commit()
    return ApiResponse.success(data=DispatchOut.model_validate(order).model_dump())


@router.post(
    "/{order_id}/reassign",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("dispatch:handle"))],
)
def reassign(
    order_id: int,
    payload: DispatchReassign,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    order = svc.reassign(db, scope, order_id, payload.assignee_id, payload.note)
    if order is None:
        return ApiResponse.fail(code=404, message="派单不存在或无权访问")
    db.commit()
    return ApiResponse.success(data=DispatchOut.model_validate(order).model_dump())
