"""处置预案路由（🅱 M5 处置预案/知识库联动）。

权限：
- playbook:list   列表/详情/元数据/推荐
- playbook:manage 新增/编辑/删除

端点：
- GET    /                       分页列表（playbook:list）
- GET    /meta                   枚举选项（告警类型/级别）（playbook:list）
- GET    /recommend              按 (project_id,alarm_type,alarm_level) 推荐预案（playbook:list）
- GET    /recommend-by-alarm/{id} 按告警 ID 推荐预案（playbook:list）
- GET    /{id}                   详情（playbook:list）
- POST   /                       新增（playbook:manage）
- PUT    /{id}                   编辑（playbook:manage）
- DELETE /{id}                   删除（playbook:manage，逻辑删除）
"""

from fastapi import APIRouter, Depends, Query

from app.core.constants import (
    ALARM_TYPE_ANOMALY,
    ALARM_TYPE_DEVICE,
    ALARM_TYPE_DISTANCE,
    ALARM_TYPE_FENCE,
    ALARM_TYPE_FORECAST,
    ALARM_TYPE_TRAIN,
)
from app.core.data_scope import DataScope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.responses import ApiResponse
from app.model.system import User
from app.schema.playbook import PlaybookCreate, PlaybookOut, PlaybookUpdate
from app.service import playbook_service as svc

router = APIRouter(tags=["处置预案"])

_ALARM_TYPES = [
    {"key": ALARM_TYPE_FENCE, "label": "围栏侵入"},
    {"key": ALARM_TYPE_DISTANCE, "label": "间距过近"},
    {"key": ALARM_TYPE_DEVICE, "label": "设备自报"},
    {"key": ALARM_TYPE_TRAIN, "label": "列车接近预警"},
    {"key": ALARM_TYPE_ANOMALY, "label": "趋势异常"},
    {"key": ALARM_TYPE_FORECAST, "label": "预测预警"},
]
_LEVELS = ["提示", "警告", "严重"]


def _out(db, obj) -> dict:
    return PlaybookOut.model_validate(svc.to_out(db, obj)).model_dump()


@router.get(
    "/",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("playbook:list"))],
)
def list_playbooks(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = Query(None, description="按项目过滤"),
    alarm_type: str | None = Query(None, description="按告警类型过滤"),
    alarm_level: str | None = Query(None, description="按告警级别过滤"),
    enabled: bool | None = Query(None, description="按启用状态过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> ApiResponse:
    result = svc.list_playbooks(
        db,
        scope,
        project_id=project_id,
        alarm_type=alarm_type,
        alarm_level=alarm_level,
        enabled=enabled,
        page=page,
        size=size,
    )
    return ApiResponse.success(
        data={
            "total": result["total"],
            "items": [_out(db, o) for o in result["items"]],
            "page": result["page"],
            "size": result["size"],
        }
    )


@router.get(
    "/meta",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("playbook:list"))],
)
def meta() -> ApiResponse:
    return ApiResponse.success(data={"alarm_types": _ALARM_TYPES, "levels": _LEVELS})


@router.get(
    "/recommend",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("playbook:list"))],
)
def recommend(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = Query(None, description="告警所属项目"),
    alarm_type: str | None = Query(None, description="告警类型"),
    alarm_level: str | None = Query(None, description="告警级别"),
    limit: int = Query(5, ge=1, le=20),
) -> ApiResponse:
    rows = svc.resolve_playbooks(db, scope, project_id, alarm_type, alarm_level, limit=limit)
    return ApiResponse.success(data=[_out(db, r) for r in rows])


@router.get(
    "/recommend-by-alarm/{alarm_id}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("playbook:list"))],
)
def recommend_by_alarm(
    alarm_id: int,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    limit: int = Query(5, ge=1, le=20),
) -> ApiResponse:
    rows = svc.recommend_for_alarm(db, scope, alarm_id, limit=limit)
    return ApiResponse.success(data=[_out(db, r) for r in rows])


@router.get(
    "/{pid}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("playbook:list"))],
)
def detail(pid: int, db=Depends(get_db), scope: DataScope = Depends(get_data_scope)) -> ApiResponse:
    obj = svc.get_playbook(db, scope, pid)
    if obj is None:
        return ApiResponse.fail(code=404, message="预案不存在或无权访问")
    return ApiResponse.success(data=_out(db, obj))


@router.post(
    "/",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("playbook:manage"))],
)
def create(
    payload: PlaybookCreate,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    obj = svc.create_playbook(db, scope, user.id, payload)
    db.commit()
    return ApiResponse.success(data=_out(db, obj))


@router.put(
    "/{pid}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("playbook:manage"))],
)
def update(
    pid: int,
    payload: PlaybookUpdate,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    obj = svc.update_playbook(db, scope, pid, payload)
    if obj is None:
        return ApiResponse.fail(code=404, message="预案不存在或无权访问")
    db.commit()
    return ApiResponse.success(data=_out(db, obj))


@router.delete(
    "/{pid}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("playbook:manage"))],
)
def delete(pid: int, db=Depends(get_db), scope: DataScope = Depends(get_data_scope)) -> ApiResponse:
    ok = svc.delete_playbook(db, scope, pid)
    if not ok:
        return ApiResponse.fail(code=404, message="预案不存在或无权访问")
    db.commit()
    return ApiResponse.success(data={"deleted": True})
