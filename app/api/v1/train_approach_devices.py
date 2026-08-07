"""列车接近报警设备列表路由（原型《列车接近报警设备列表》）。

管理 train_approach_device 表（模型 TrainApproachDevice，即「列车接近报警设备」），
提供按 项目 / 设备名称(左右模糊) / 设备编号(精确) / 设备状态(精确) 过滤的分页列表，
以及详情 / 新增 / 编辑 / 删除(软删) / 批量删除。

- 数据隔离：VIA_PROJECT（经 project.dept_id 过滤），复用 data_scope._MODEL_DEPT_LINK 注册。
- 权限：train_approach_device:list / :add / :edit / :delete。
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
from app.model.device import TrainApproachDevice
from app.model.project import Project
from app.model.system import User
from app.schema.common import IdList
from app.schema.train_approach_device import (
    TrainApproachDeviceCreate,
    TrainApproachDeviceOut,
    TrainApproachDevicePage,
    TrainApproachDeviceUpdate,
)
from app.service.batch_ops import batch_soft_delete

router = APIRouter(tags=["列车接近报警设备"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "train-approach-devices", "status": "skeleton"}


def _out(obj: TrainApproachDevice) -> TrainApproachDeviceOut:
    """转响应对象并冗余项目名；防 detached（后台任务在 Session 关闭后序列化）。"""
    out = TrainApproachDeviceOut.model_validate(obj)
    try:
        if inspect(obj).session is not None and obj.project is not None:
            out.project_name = obj.project.name
    except DetachedInstanceError:
        pass
    return out


def _load(db: Session, scope: DataScope, device_id: int) -> TrainApproachDevice:
    """按 ID + 数据范围取单条；不存在/越权统一 404（真实状态码）。"""
    stmt = select(TrainApproachDevice).where(
        TrainApproachDevice.id == device_id, TrainApproachDevice.is_deleted.is_(False)
    )
    stmt = apply_data_scope(stmt, TrainApproachDevice, scope)
    obj = db.scalars(stmt).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在或无权访问")
    return obj


@router.get(
    "",
    response_model=ApiResponse[TrainApproachDevicePage],
    summary="列车接近报警设备列表",
    dependencies=[Depends(require_permissions("train_approach_device:list"))],
)
def list_train_approach_devices(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = Query(None, description="归属项目ID"),
    name: str | None = Query(None, description="设备名称(左右模糊)"),
    device_no: str | None = Query(None, description="设备编号(精确)"),
    status: str | None = Query(None, description="设备状态(精确)"),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=200),
) -> ApiResponse:
    """按创建时间倒序分页；过滤条件对齐原型《列车接近报警设备列表》搜索区。"""
    stmt = select(TrainApproachDevice).where(TrainApproachDevice.is_deleted.is_(False))
    if project_id is not None:
        stmt = stmt.where(TrainApproachDevice.project_id == project_id)
    if name:
        stmt = stmt.where(TrainApproachDevice.name.ilike(f"%{name}%"))
    if device_no:
        stmt = stmt.where(TrainApproachDevice.device_no == device_no)
    if status:
        stmt = stmt.where(TrainApproachDevice.status == status)
    stmt = apply_data_scope(stmt, TrainApproachDevice, scope)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(TrainApproachDevice.created_at.desc(), TrainApproachDevice.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return ApiResponse.success(
        TrainApproachDevicePage(
            items=[_out(r) for r in rows],
            total=total,
            page=page,
            size=size,
        ),
        message="查询成功",
    )


@router.get(
    "/{device_id}",
    response_model=ApiResponse[TrainApproachDeviceOut],
    summary="列车接近报警设备详情",
    dependencies=[Depends(require_permissions("train_approach_device:list"))],
)
def get_train_approach_device(
    device_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    obj = _load(db, scope, device_id)
    return ApiResponse.success(_out(obj), message="获取成功")


@router.post(
    "",
    response_model=ApiResponse[TrainApproachDeviceOut],
    summary="新增列车接近报警设备",
    dependencies=[Depends(require_permissions("train_approach_device:add"))],
)
def create_train_approach_device(
    req: TrainApproachDeviceCreate,
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
            select(TrainApproachDevice.id).where(
                TrainApproachDevice.device_no == req.device_no,
                TrainApproachDevice.is_deleted.is_(False),
            )
        )
        is not None
    ):
        raise BusinessError("设备编号已存在", code=400)
    obj = TrainApproachDevice(
        project_id=req.project_id,
        name=req.name,
        device_no=req.device_no,
        sn=req.sn,
        direction=req.direction,
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
    response_model=ApiResponse[TrainApproachDeviceOut],
    summary="编辑列车接近报警设备",
    dependencies=[Depends(require_permissions("train_approach_device:edit"))],
)
def update_train_approach_device(
    device_id: int,
    req: TrainApproachDeviceUpdate,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    obj = _load(db, scope, device_id)
    data = req.model_dump(exclude_unset=True)
    if "device_no" in data and data["device_no"] != obj.device_no:
        if (
            db.scalar(
                select(TrainApproachDevice.id).where(
                    TrainApproachDevice.device_no == data["device_no"],
                    TrainApproachDevice.is_deleted.is_(False),
                    TrainApproachDevice.id != device_id,
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
    summary="删除列车接近报警设备(软删)",
    dependencies=[Depends(require_permissions("train_approach_device:delete"))],
)
def delete_train_approach_device(
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
    summary="批量删除列车接近报警设备(软删)",
    dependencies=[Depends(require_permissions("train_approach_device:delete"))],
)
def batch_delete_train_approach_devices(
    items: IdList,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    deleted = batch_soft_delete(TrainApproachDevice, db, scope, items.ids)
    db.commit()
    total = len(items.ids)
    return ApiResponse.success(
        data={"deleted": deleted, "total": total, "skipped": total - deleted},
        message=f"已删除 {deleted} 条",
    )
