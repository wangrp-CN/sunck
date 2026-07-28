"""设备指令下发记录查询与重试接口（闭环可观测）。

- GET    /          指令记录列表（按项目数据范围过滤 + 设备/类型/状态筛选 + 分页）
- GET    /{id}      指令详情
- POST   /{id}/retry 手动重试（运维在「指令下发记录」页触发；已回执不可重试）

权限：列表/详情需 ``command:list``；重试需 ``device:command``（与下发同源）。
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.model.command import DeviceCommand
from app.model.project import Project
from app.schema.command import DeviceCommandOut
from app.service import command_service

router = APIRouter()


def _scope_project_ids(db: Session, scope: DataScope) -> set[int] | None:
    """返回当前用户可见的项目 ID 集合；is_all 返回 None（不过滤）。"""
    if scope.is_all or not scope.dept_ids:
        return None
    ids = db.scalars(select(Project.id).where(Project.dept_id.in_(scope.dept_ids))).all()
    return set(ids)


@router.get(
    "",
    summary="指令下发记录列表",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("command:list"))],
)
def list_commands(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    device_no: str | None = Query(None, description="设备编号筛选"),
    device_type: str | None = Query(None, description="设备类型筛选"),
    status: str | None = Query(None, description="状态筛选(pending/sent/acked/failed)"),
    alarm_id: int | None = Query(None, description="关联告警筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> ApiResponse:
    stmt = select(DeviceCommand)
    allowed = _scope_project_ids(db, scope)
    if allowed is not None:
        stmt = stmt.where(DeviceCommand.project_id.in_(allowed))
    if device_no:
        stmt = stmt.where(DeviceCommand.device_no == device_no)
    if device_type:
        stmt = stmt.where(DeviceCommand.device_type == device_type)
    if status:
        stmt = stmt.where(DeviceCommand.status == status)
    if alarm_id is not None:
        stmt = stmt.where(DeviceCommand.alarm_id == alarm_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(DeviceCommand.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return ApiResponse.success(
        data={
            "items": [DeviceCommandOut.model_validate(r).model_dump() for r in rows],
            "total": total,
            "page": page,
            "size": size,
        }
    )


@router.get(
    "/{command_id}",
    summary="指令详情",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("command:list"))],
)
def get_command(
    command_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    cmd = db.get(DeviceCommand, command_id)
    if cmd is None:
        raise BusinessError("指令记录不存在", code=404)
    allowed = _scope_project_ids(db, scope)
    if allowed is not None and cmd.project_id not in allowed:
        raise BusinessError("指令记录不存在", code=404)
    return ApiResponse.success(data=DeviceCommandOut.model_validate(cmd).model_dump())


@router.post(
    "/{command_id}/retry",
    summary="手动重试指令",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("device:command"))],
)
def retry_command(
    command_id: int,
    db: Session = Depends(get_db),
    _: object = Depends(get_current_user),
) -> ApiResponse:
    cmd = command_service.retry_command(db, command_id)
    return ApiResponse.success(
        data=DeviceCommandOut.model_validate(cmd).model_dump(),
        message="已重新下发",
    )
