"""告警策略路由（🅱 M4 告警收敛/抑制/升级策略）。

权限：
- alarm_policy:list   列表/详情/元数据
- alarm_policy:manage 新增/编辑/删除/手动触发升级

端点：
- GET    /                 分页列表（alarm_policy:list）
- GET    /meta             枚举选项（告警类型/级别/渠道）（alarm_policy:list）
- GET    /{id}             详情（alarm_policy:list）
- POST   /                 新增（alarm_policy:manage）
- PUT    /{id}             编辑（alarm_policy:manage）
- DELETE /{id}             删除（alarm_policy:manage，逻辑删除）
- POST   /run-escalations  手动触发一轮超时升级扫描（alarm_policy:manage）
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
from app.schema.alarm_policy import AlarmPolicyCreate, AlarmPolicyUpdate
from app.service import alarm_policy_service as svc

router = APIRouter(tags=["告警策略"])

_ALARM_TYPES = [
    {"key": ALARM_TYPE_FENCE, "label": "围栏侵入"},
    {"key": ALARM_TYPE_DISTANCE, "label": "间距过近"},
    {"key": ALARM_TYPE_DEVICE, "label": "设备自报"},
    {"key": ALARM_TYPE_TRAIN, "label": "列车接近预警"},
    {"key": ALARM_TYPE_ANOMALY, "label": "趋势异常"},
    {"key": ALARM_TYPE_FORECAST, "label": "预测预警"},
]
_LEVELS = ["提示", "警告", "严重"]
_CHANNELS = ["in_app", "sms", "voice"]


@router.get(
    "/",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm_policy:list"))],
)
def list_policies(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = Query(None, description="按项目过滤"),
    alarm_type: str | None = Query(None, description="按告警类型过滤"),
    enabled: bool | None = Query(None, description="按启用状态过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> ApiResponse:
    result = svc.list_policies(
        db,
        scope,
        project_id=project_id,
        alarm_type=alarm_type,
        enabled=enabled,
        page=page,
        size=size,
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
    "/meta",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm_policy:list"))],
)
def meta() -> ApiResponse:
    return ApiResponse.success(
        data={"alarm_types": _ALARM_TYPES, "levels": _LEVELS, "channels": _CHANNELS}
    )


@router.post(
    "/run-escalations",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm_policy:manage"))],
)
def run_escalations(db=Depends(get_db)) -> ApiResponse:
    """手动触发一轮超时升级扫描（周期任务外的应急手段）。"""
    result = svc.run_escalations(db)
    db.commit()
    return ApiResponse.success(data=result)


@router.get(
    "/{pid}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm_policy:list"))],
)
def detail(pid: int, db=Depends(get_db), scope: DataScope = Depends(get_data_scope)) -> ApiResponse:
    obj = svc.get_policy(db, scope, pid)
    if obj is None:
        return ApiResponse.fail(code=404, message="策略不存在或无权访问")
    return ApiResponse.success(data=svc.to_out(db, obj).model_dump())


@router.post(
    "/",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm_policy:manage"))],
)
def create(
    payload: AlarmPolicyCreate,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    obj = svc.create_policy(db, scope, user.id, payload)
    db.commit()
    return ApiResponse.success(data=svc.to_out(db, obj).model_dump())


@router.put(
    "/{pid}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm_policy:manage"))],
)
def update(
    pid: int,
    payload: AlarmPolicyUpdate,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    obj = svc.update_policy(db, scope, pid, payload)
    if obj is None:
        return ApiResponse.fail(code=404, message="策略不存在或无权访问")
    db.commit()
    return ApiResponse.success(data=svc.to_out(db, obj).model_dump())


@router.delete(
    "/{pid}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("alarm_policy:manage"))],
)
def delete(pid: int, db=Depends(get_db), scope: DataScope = Depends(get_data_scope)) -> ApiResponse:
    ok = svc.delete_policy(db, scope, pid)
    if not ok:
        return ApiResponse.fail(code=404, message="策略不存在或无权访问")
    db.commit()
    return ApiResponse.success(data={"deleted": True})
