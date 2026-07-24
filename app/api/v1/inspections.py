"""巡检/打卡路由：任务 CRUD、状态流转、打卡、异常转隐患、统计。

- GET    /              任务列表（筛选+分页+数据隔离，inspection:list）
- POST   /              创建任务（inspection:create）
- GET    /stats         统计（inspection:list）
- GET    /{id}          详情（含打卡记录，inspection:list）
- PUT    /{id}          更新（inspection:update）
- DELETE /{id}          软删除（inspection:delete）
- POST   /{id}/transition  状态流转 start/finish/cancel（inspection:update）
- POST   /{id}/checkin  打卡（inspection:checkin）
- POST   /records/{rid}/convert-to-hazard  异常打卡转隐患（inspection:update）
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.data_scope import DataScope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.responses import ApiResponse
from app.model.system import User
from app.schema.inspection import (
    InspectionCheckin,
    InspectionRecordOut,
    InspectionTaskCreate,
    InspectionTaskUpdate,
)
from app.service import inspection_service as svc

router = APIRouter(tags=["巡检打卡"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "inspections", "status": "ready"}


@router.get(
    "/stats",
    summary="巡检统计",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("inspection:list"))],
)
def stats(db=Depends(get_db), scope: DataScope = Depends(get_data_scope)) -> ApiResponse:
    return ApiResponse.success(data=svc.inspection_stats(db, scope))


@router.get(
    "",
    summary="巡检任务列表",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("inspection:list"))],
)
def list_tasks(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    total, rows = svc.list_tasks(
        db, scope, project_id=project_id, status=status, keyword=keyword, page=page, size=size
    )
    return ApiResponse.success(
        data={
            "total": total,
            "items": [svc.to_task_out(db, t).model_dump() for t in rows],
            "page": page,
            "size": size,
        }
    )


@router.post(
    "",
    summary="创建巡检任务",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("inspection:create"))],
)
def create_task(
    payload: InspectionTaskCreate,
    db=Depends(get_db),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    t = svc.create_task(db, payload.model_dump(), current.id)
    db.commit()
    return ApiResponse.success(data=svc.to_task_out(db, t).model_dump())


@router.get(
    "/{task_id}",
    summary="巡检任务详情",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("inspection:list"))],
)
def get_task(
    task_id: int, db=Depends(get_db), scope: DataScope = Depends(get_data_scope)
) -> ApiResponse:
    t = svc.get_task(db, task_id, scope)
    if t is None:
        return ApiResponse.fail(message="巡检任务不存在或无权访问", code=404)
    return ApiResponse.success(data=svc.to_task_out(db, t).model_dump())


@router.put(
    "/{task_id}",
    summary="更新巡检任务",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("inspection:update"))],
)
def update_task(
    task_id: int,
    payload: InspectionTaskUpdate,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    t = svc.update_task(db, task_id, payload.model_dump(exclude_unset=True), scope)
    if t is None:
        return ApiResponse.fail(message="巡检任务不存在或无权访问", code=404)
    db.commit()
    return ApiResponse.success(data=svc.to_task_out(db, t).model_dump())


@router.delete(
    "/{task_id}",
    summary="删除巡检任务",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("inspection:delete"))],
)
def delete_task(
    task_id: int, db=Depends(get_db), scope: DataScope = Depends(get_data_scope)
) -> ApiResponse:
    ok = svc.delete_task(db, task_id, scope)
    if not ok:
        return ApiResponse.fail(message="巡检任务不存在或无权访问", code=404)
    db.commit()
    return ApiResponse.success(message="删除成功")


class TransitionBody(BaseModel):
    action: str = Field(..., description="流转动作(start/finish/cancel)")


@router.post(
    "/{task_id}/transition",
    summary="巡检任务状态流转",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("inspection:update"))],
)
def transition_task(
    task_id: int,
    payload: TransitionBody,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    t = svc.transition_task(db, task_id, payload.action, scope)
    db.commit()
    return ApiResponse.success(data=svc.to_task_out(db, t).model_dump())


@router.post(
    "/{task_id}/checkin",
    summary="巡检打卡",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("inspection:checkin"))],
)
def checkin(
    task_id: int,
    payload: InspectionCheckin,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    rec = svc.checkin(
        db,
        task_id,
        payload.model_dump(),
        scope,
        operator_name=current.nickname or current.username,
    )
    db.commit()
    return ApiResponse.success(data=InspectionRecordOut.model_validate(rec).model_dump())


@router.post(
    "/records/{record_id}/convert-to-hazard",
    summary="异常打卡转隐患（巡检→治理闭环）",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("inspection:update"))],
)
def convert_to_hazard(
    record_id: int,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    hazard_id = svc.convert_checkin_to_hazard(db, record_id, scope, current.id)
    db.commit()
    return ApiResponse.success(data={"hazard_id": hazard_id}, message="已转为隐患")
