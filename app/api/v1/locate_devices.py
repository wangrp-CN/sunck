"""人机定位设备列表路由（原型《人机定位设备列表》）。

管理 locate_device 表（模型 LocateDevice，即「人机定位设备」），提供
按 项目 / 设备名称(模糊) / 设备类型(精确) / 设备编号(精确) / 设备状态(精确)
过滤的分页列表，以及详情 / 新增 / 编辑 / 删除(软删) / 批量删除。

- 数据隔离：VIA_PROJECT（经 project.dept_id 过滤），复用 data_scope._MODEL_DEPT_LINK 注册。
- 权限：locate_device:list / locate_device:add / locate_device:edit / locate_device:delete。
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import DetachedInstanceError

from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.model.device import LocateDevice
from app.model.project import Project
from app.model.system import User
from app.schema.common import IdList
from app.schema.locate_device import (
    LocateDeviceCreate,
    LocateDeviceOut,
    LocateDevicePage,
    LocateDeviceUpdate,
)
from app.service.batch_ops import batch_soft_delete

router = APIRouter(tags=["人机定位设备"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "locate-devices", "status": "skeleton"}


def _out(obj: LocateDevice) -> LocateDeviceOut:
    """转响应对象并冗余项目名；防 detached（实时管道/后台任务序列化场景）。"""
    out = LocateDeviceOut.model_validate(obj)
    try:
        if inspect(obj).session is not None and obj.project is not None:
            out.project_name = obj.project.name
    except DetachedInstanceError:
        pass
    return out


@router.get(
    "",
    response_model=ApiResponse[LocateDevicePage],
    summary="人机定位设备列表",
    dependencies=[Depends(require_permissions("locate_device:list"))],
)
def list_locate_devices(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = Query(None, description="归属项目ID"),
    name: str | None = Query(None, description="设备名称(左右模糊)"),
    device_type: str | None = Query(None, description="设备类型(精确)"),
    device_no: str | None = Query(None, description="设备编号(精确)"),
    status: str | None = Query(None, description="设备状态(精确)"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=200),
) -> ApiResponse:
    """按创建时间倒序分页；过滤条件对齐原型《人机定位设备列表》搜索区。"""
    stmt = select(LocateDevice).where(LocateDevice.is_deleted.is_(False))
    if project_id is not None:
        stmt = stmt.where(LocateDevice.project_id == project_id)
    if name:
        stmt = stmt.where(LocateDevice.name.ilike(f"%{name}%"))
    if device_type:
        stmt = stmt.where(LocateDevice.device_type == device_type)
    if device_no:
        stmt = stmt.where(LocateDevice.device_no == device_no)
    if status:
        stmt = stmt.where(LocateDevice.status == status)
    stmt = apply_data_scope(stmt, LocateDevice, scope)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(LocateDevice.created_at.desc(), LocateDevice.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return ApiResponse.success(
        LocateDevicePage(
            items=[_out(r) for r in rows],
            total=total,
            page=page,
            size=size,
        ),
        message="查询成功",
    )


@router.get(
    "/{device_id}",
    response_model=ApiResponse[LocateDeviceOut],
    summary="人机定位设备详情",
    dependencies=[Depends(require_permissions("locate_device:list"))],
)
def get_locate_device(
    device_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    stmt = select(LocateDevice).where(
        LocateDevice.id == device_id, LocateDevice.is_deleted.is_(False)
    )
    stmt = apply_data_scope(stmt, LocateDevice, scope)
    obj = db.scalars(stmt).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在或无权访问")
    return ApiResponse.success(_out(obj), message="获取成功")


@router.post(
    "",
    response_model=ApiResponse[LocateDeviceOut],
    summary="新增人机定位设备",
    dependencies=[Depends(require_permissions("locate_device:add"))],
)
def create_locate_device(
    req: LocateDeviceCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    if (
        db.scalar(
            select(Project.id).where(Project.id == req.project_id, Project.is_deleted.is_(False))
        )
        is None
    ):
        raise BusinessError("归属项目不存在", code=400)
    if (
        db.scalar(
            select(LocateDevice.id).where(
                LocateDevice.device_no == req.device_no,
                LocateDevice.is_deleted.is_(False),
            )
        )
        is not None
    ):
        raise BusinessError("设备编号已存在", code=400)
    obj = LocateDevice(
        project_id=req.project_id,
        name=req.name,
        device_no=req.device_no,
        device_type=req.device_type,
        function=req.function,
        sn=req.sn,
        status=req.status,
        created_by=current.id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return ApiResponse.success(_out(obj), message="设备创建成功")


@router.put(
    "/{device_id}",
    response_model=ApiResponse[LocateDeviceOut],
    summary="编辑人机定位设备",
    dependencies=[Depends(require_permissions("locate_device:edit"))],
)
def update_locate_device(
    device_id: int,
    req: LocateDeviceUpdate,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    stmt = select(LocateDevice).where(
        LocateDevice.id == device_id, LocateDevice.is_deleted.is_(False)
    )
    stmt = apply_data_scope(stmt, LocateDevice, scope)
    obj = db.scalars(stmt).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在或无权访问")
    data = req.model_dump(exclude_unset=True)
    if "device_no" in data and data["device_no"] != obj.device_no:
        if (
            db.scalar(
                select(LocateDevice.id).where(
                    LocateDevice.device_no == data["device_no"],
                    LocateDevice.is_deleted.is_(False),
                    LocateDevice.id != device_id,
                )
            )
            is not None
        ):
            raise BusinessError("设备编号已存在", code=400)
    for field, value in data.items():
        setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return ApiResponse.success(_out(obj), message="设备更新成功")


@router.delete(
    "/{device_id}",
    response_model=ApiResponse,
    summary="删除人机定位设备(软删)",
    dependencies=[Depends(require_permissions("locate_device:delete"))],
)
def delete_locate_device(
    device_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    stmt = select(LocateDevice).where(
        LocateDevice.id == device_id, LocateDevice.is_deleted.is_(False)
    )
    stmt = apply_data_scope(stmt, LocateDevice, scope)
    obj = db.scalars(stmt).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在或无权访问")
    obj.is_deleted = True
    db.commit()
    return ApiResponse.success(message="设备已删除")


@router.post(
    "/batch-delete",
    response_model=ApiResponse,
    summary="批量删除人机定位设备(软删)",
    dependencies=[Depends(require_permissions("locate_device:delete"))],
)
def batch_delete_locate_devices(
    items: IdList,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    deleted = batch_soft_delete(LocateDevice, db, scope, items.ids)
    db.commit()
    total = len(items.ids)
    return ApiResponse.success(
        data={"deleted": deleted, "total": total, "skipped": total - deleted},
        message=f"已删除 {deleted} 条",
    )
