"""值班排班路由（🅱 告警治理与值班体系）。

权限：
- duty:list   列表/详情/当前值班/元数据
- duty:manage 新增/编辑/删除排班

端点：
- GET    /            分页列表（duty:list）
- GET    /on-duty     查询某项目当前值班人（duty:list）
- GET    /meta        枚举选项（班次）（duty:list）
- GET    /{id}        详情（duty:list）
- POST   /            新增（duty:manage）
- PUT    /{id}        编辑（duty:manage）
- DELETE /{id}        删除（duty:manage，逻辑删除）
"""

from fastapi import APIRouter, Depends, Query

from app.core.data_scope import DataScope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.responses import ApiResponse
from app.model.system import User
from app.schema.duty import DutyRosterCreate, DutyRosterUpdate
from app.service import duty_service as svc

router = APIRouter(tags=["值班排班"])

_DUTY_SHIFTS = ["白班", "夜班", "早班", "中班", "晚班"]


@router.get(
    "/", response_model=ApiResponse, dependencies=[Depends(require_permissions("duty:list"))]
)
def list_rosters(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = Query(None, description="按项目过滤"),
    user_id: int | None = Query(None, description="按值班人过滤"),
    active: bool | None = Query(None, description="仅查当前在班"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> ApiResponse:
    result = svc.list_rosters(
        db, scope, project_id=project_id, user_id=user_id, active=active, page=page, size=size
    )
    return ApiResponse.success(
        data={
            "total": result["total"],
            "items": [svc.to_out(db, o).model_dump() for o in result["items"]],
            "page": result["page"],
            "size": result["size"],
        }
    )


@router.get(
    "/on-duty", response_model=ApiResponse, dependencies=[Depends(require_permissions("duty:list"))]
)
def on_duty(
    project_id: int = Query(..., description="项目 ID"),
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """查询某项目当前在班（now 落在值班时间窗内）的值班人；无则返回 null。"""
    uid, name = svc.resolve_on_duty(db, project_id)
    return ApiResponse.success(data={"project_id": project_id, "user_id": uid, "user_name": name})


@router.get(
    "/meta", response_model=ApiResponse, dependencies=[Depends(require_permissions("duty:list"))]
)
def meta() -> ApiResponse:
    return ApiResponse.success(data={"shifts": _DUTY_SHIFTS})


@router.get(
    "/{rid}", response_model=ApiResponse, dependencies=[Depends(require_permissions("duty:list"))]
)
def detail(rid: int, db=Depends(get_db), scope: DataScope = Depends(get_data_scope)) -> ApiResponse:
    obj = svc.get_roster(db, scope, rid)
    if obj is None:
        return ApiResponse.fail(code=404, message="排班不存在或无权访问")
    return ApiResponse.success(data=svc.to_out(db, obj).model_dump())


@router.post(
    "/", response_model=ApiResponse, dependencies=[Depends(require_permissions("duty:manage"))]
)
def create(
    payload: DutyRosterCreate,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    obj = svc.create_roster(db, scope, user.id, payload)
    db.commit()
    return ApiResponse.success(data=svc.to_out(db, obj).model_dump())


@router.put(
    "/{rid}", response_model=ApiResponse, dependencies=[Depends(require_permissions("duty:manage"))]
)
def update(
    rid: int,
    payload: DutyRosterUpdate,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    obj = svc.update_roster(db, scope, rid, payload)
    if obj is None:
        return ApiResponse.fail(code=404, message="排班不存在或无权访问")
    db.commit()
    return ApiResponse.success(data=svc.to_out(db, obj).model_dump())


@router.delete(
    "/{rid}", response_model=ApiResponse, dependencies=[Depends(require_permissions("duty:manage"))]
)
def delete(rid: int, db=Depends(get_db), scope: DataScope = Depends(get_data_scope)) -> ApiResponse:
    ok = svc.delete_roster(db, scope, rid)
    if not ok:
        return ApiResponse.fail(code=404, message="排班不存在或无权访问")
    db.commit()
    return ApiResponse.success(data={"deleted": True})
