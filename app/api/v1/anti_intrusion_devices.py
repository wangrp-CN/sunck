"""大机防侵限设备列表路由（原型《大机防侵限设备列表》）。

管理 anti_intrusion_device 表（模型 AntiIntrusionDevice，即「大机防侵限设备」），
提供按 项目 / 设备名称(左右模糊) / 设备编号(精确) / 设备状态(精确) 过滤的分页列表，
以及详情 / 新增 / 编辑 / 删除(软删) / 批量删除。

- 数据隔离：VIA_PROJECT（经 project.dept_id 过滤），复用 data_scope._MODEL_DEPT_LINK 注册。
- 权限：anti_intrusion_device:list / :add / :edit / :delete。
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
from app.model.device import AntiIntrusionDevice
from app.model.project import Project
from app.model.system import User
from app.schema.anti_intrusion_device import (
    AntiIntrusionDeviceCreate,
    AntiIntrusionDeviceOut,
    AntiIntrusionDevicePage,
    AntiIntrusionDeviceUpdate,
)
from app.schema.common import IdList
from app.service.batch_ops import batch_soft_delete

router = APIRouter(tags=["大机防侵限设备"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "anti-intrusion-devices", "status": "skeleton"}


def _out(obj: AntiIntrusionDevice) -> AntiIntrusionDeviceOut:
    """转响应对象并冗余项目名；防 detached（后台任务在 Session 关闭后序列化）。"""
    out = AntiIntrusionDeviceOut.model_validate(obj)
    try:
        if inspect(obj).session is not None and obj.project is not None:
            out.project_name = obj.project.name
    except DetachedInstanceError:
        pass
    return out


def _load(db: Session, scope: DataScope, device_id: int) -> AntiIntrusionDevice:
    """按 ID + 数据范围取单条；不存在/越权统一 404（真实状态码）。"""
    stmt = select(AntiIntrusionDevice).where(
        AntiIntrusionDevice.id == device_id, AntiIntrusionDevice.is_deleted.is_(False)
    )
    stmt = apply_data_scope(stmt, AntiIntrusionDevice, scope)
    obj = db.scalars(stmt).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在或无权访问")
    return obj


@router.get(
    "",
    response_model=ApiResponse[AntiIntrusionDevicePage],
    summary="大机防侵限设备列表",
    dependencies=[Depends(require_permissions("anti_intrusion_device:list"))],
)
def list_anti_intrusion_devices(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = Query(None, description="归属项目ID"),
    name: str | None = Query(None, description="设备名称(左右模糊)"),
    device_no: str | None = Query(None, description="设备编号(精确)"),
    status: str | None = Query(None, description="设备状态(精确)"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=200),
) -> ApiResponse:
    """按创建时间倒序分页；过滤条件对齐原型《大机防侵限设备列表》搜索区。"""
    stmt = select(AntiIntrusionDevice).where(AntiIntrusionDevice.is_deleted.is_(False))
    if project_id is not None:
        stmt = stmt.where(AntiIntrusionDevice.project_id == project_id)
    if name:
        stmt = stmt.where(AntiIntrusionDevice.name.ilike(f"%{name}%"))
    if device_no:
        stmt = stmt.where(AntiIntrusionDevice.device_no == device_no)
    if status:
        stmt = stmt.where(AntiIntrusionDevice.status == status)
    stmt = apply_data_scope(stmt, AntiIntrusionDevice, scope)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AntiIntrusionDevice.created_at.desc(), AntiIntrusionDevice.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return ApiResponse.success(
        AntiIntrusionDevicePage(
            items=[_out(r) for r in rows],
            total=total,
            page=page,
            size=size,
        ),
        message="查询成功",
    )


@router.get(
    "/{device_id}",
    response_model=ApiResponse[AntiIntrusionDeviceOut],
    summary="大机防侵限设备详情",
    dependencies=[Depends(require_permissions("anti_intrusion_device:list"))],
)
def get_anti_intrusion_device(
    device_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    obj = _load(db, scope, device_id)
    return ApiResponse.success(_out(obj), message="获取成功")


@router.post(
    "",
    response_model=ApiResponse[AntiIntrusionDeviceOut],
    summary="新增大机防侵限设备",
    dependencies=[Depends(require_permissions("anti_intrusion_device:add"))],
)
def create_anti_intrusion_device(
    req: AntiIntrusionDeviceCreate,
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
            select(AntiIntrusionDevice.id).where(
                AntiIntrusionDevice.device_no == req.device_no,
                AntiIntrusionDevice.is_deleted.is_(False),
            )
        )
        is not None
    ):
        raise BusinessError("设备编号已存在", code=400)
    obj = AntiIntrusionDevice(
        project_id=req.project_id,
        name=req.name,
        device_no=req.device_no,
        sn=req.sn,
        longitude=req.longitude,
        latitude=req.latitude,
        status=req.status,
        created_by=current.id,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return ApiResponse.success(_out(obj), message="设备创建成功")


@router.put(
    "/{device_id}",
    response_model=ApiResponse[AntiIntrusionDeviceOut],
    summary="编辑大机防侵限设备",
    dependencies=[Depends(require_permissions("anti_intrusion_device:edit"))],
)
def update_anti_intrusion_device(
    device_id: int,
    req: AntiIntrusionDeviceUpdate,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    obj = _load(db, scope, device_id)
    data = req.model_dump(exclude_unset=True)
    if "device_no" in data and data["device_no"] != obj.device_no:
        if (
            db.scalar(
                select(AntiIntrusionDevice.id).where(
                    AntiIntrusionDevice.device_no == data["device_no"],
                    AntiIntrusionDevice.is_deleted.is_(False),
                    AntiIntrusionDevice.id != device_id,
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
    summary="删除大机防侵限设备(软删)",
    dependencies=[Depends(require_permissions("anti_intrusion_device:delete"))],
)
def delete_anti_intrusion_device(
    device_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    obj = _load(db, scope, device_id)
    obj.is_deleted = True
    db.commit()
    return ApiResponse.success(message="设备已删除")


@router.post(
    "/batch-delete",
    response_model=ApiResponse,
    summary="批量删除大机防侵限设备(软删)",
    dependencies=[Depends(require_permissions("anti_intrusion_device:delete"))],
)
def batch_delete_anti_intrusion_devices(
    items: IdList,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    deleted = batch_soft_delete(AntiIntrusionDevice, db, scope, items.ids)
    db.commit()
    total = len(items.ids)
    return ApiResponse.success(
        data={"deleted": deleted, "total": total, "skipped": total - deleted},
        message=f"已删除 {deleted} 条",
    )
