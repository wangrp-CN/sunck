"""设备管理路由（对应需求 §2.7）。

三类设备（人机定位 / 大机防侵限 / 列车接近）共用统一接口：
- 列表/详情/更新/删除通过 ``device_type`` 参数在三类 ORM 模型间派发。
- 全部接入数据隔离（VIA_PROJECT：经 project.dept_id 过滤）。
- 权限：device:list / device:add / device:edit / device:delete。
  （device:command 属实时监控下行，不在此处实现。）
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.model.device import (
    AntiIntrusionDevice,
    LocateDevice,
    TrainApproachDevice,
)
from app.model.project import Project
from app.model.system import User
from app.schema.device import (
    DeviceCreate,
    DeviceOut,
    DevicePage,
    DeviceUpdate,
    validate_device_type,
)

router = APIRouter(tags=["设备管理"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "devices", "status": "skeleton"}


_DEVICE_MODELS = {
    "locate": LocateDevice,
    "anti_intrusion": AntiIntrusionDevice,
    "train_approach": TrainApproachDevice,
}


def _candidate_models(device_type: str | None):
    if device_type:
        validate_device_type(device_type)
        return [_DEVICE_MODELS[device_type]]
    return list(_DEVICE_MODELS.values())


def _find_device(db: Session, scope: DataScope, device_id: int, device_type: str | None):
    for m in _candidate_models(device_type):
        stmt = select(m).where(m.id == device_id, m.is_deleted.is_(False))
        stmt = apply_data_scope(stmt, m, scope)
        obj = db.scalars(stmt).first()
        if obj is not None:
            return obj
    return None


@router.get(
    "",
    response_model=ApiResponse[DevicePage],
    summary="设备列表",
    dependencies=[Depends(require_permissions("device:list"))],
)
def list_devices(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    device_type: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    """分页查询设备；device_type 为空时跨三类合并后排序分页。"""
    models = _candidate_models(device_type)
    rows: list = []
    for m in models:
        stmt = select(m).where(m.is_deleted.is_(False))
        if keyword:
            kw = f"%{keyword}%"
            stmt = stmt.where(or_(m.name.ilike(kw), m.device_no.ilike(kw)))
        stmt = apply_data_scope(stmt, m, scope)
        rows.extend(db.scalars(stmt).all())
    # 跨表合并后按 id 倒序分页（主数据量级小，内存分页可接受）
    rows.sort(key=lambda x: x.id, reverse=True)
    total = len(rows)
    page_rows = rows[(page - 1) * size : (page - 1) * size + size]
    return ApiResponse.success(
        DevicePage(
            items=[DeviceOut.model_validate(r) for r in page_rows],
            total=total,
            page=page,
            size=size,
        ),
        message="查询成功",
    )


@router.get(
    "/{device_id}",
    response_model=ApiResponse[DeviceOut],
    summary="设备详情",
    dependencies=[Depends(require_permissions("device:list"))],
)
def get_device(
    device_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    device_type: str | None = None,
) -> ApiResponse:
    """返回单个设备；不在数据范围内返回 404。"""
    obj = _find_device(db, scope, device_id, device_type)
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在或无权访问")
    return ApiResponse.success(DeviceOut.model_validate(obj), message="获取成功")


@router.post(
    "",
    response_model=ApiResponse[DeviceOut],
    summary="新建设备",
    dependencies=[Depends(require_permissions("device:add"))],
)
def create_device(
    req: DeviceCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    """按 device_type 派发到对应模型；写入 created_by 与归属项目。"""
    validate_device_type(req.device_type)
    if (
        db.scalar(
            select(Project.id).where(Project.id == req.project_id, Project.is_deleted.is_(False))
        )
        is None
    ):
        raise BusinessError("归属项目不存在", code=400)
    m = _DEVICE_MODELS[req.device_type]
    cols = {c.name for c in m.__table__.columns}
    data = {k: v for k, v in req.model_dump(exclude={"device_type"}).items() if k in cols}
    if "device_type" in cols:
        data["device_type"] = req.device_type
    data["created_by"] = current.id
    obj = m(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return ApiResponse.success(DeviceOut.model_validate(obj), message="设备创建成功")


@router.put(
    "/{device_id}",
    response_model=ApiResponse[DeviceOut],
    summary="更新设备",
    dependencies=[Depends(require_permissions("device:edit"))],
)
def update_device(
    device_id: int,
    req: DeviceUpdate,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    device_type: str | None = None,
) -> ApiResponse:
    """更新设备；device_type 用于定位正确模型。"""
    obj = _find_device(db, scope, device_id, device_type)
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在或无权访问")
    cols = {c.name for c in obj.__table__.columns}
    for field, value in req.model_dump(exclude_unset=True).items():
        if field in cols:
            setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return ApiResponse.success(DeviceOut.model_validate(obj), message="设备更新成功")


@router.delete(
    "/{device_id}",
    response_model=ApiResponse,
    summary="删除设备",
    dependencies=[Depends(require_permissions("device:delete"))],
)
def delete_device(
    device_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    device_type: str | None = None,
) -> ApiResponse:
    """软删设备（is_deleted=True）。"""
    obj = _find_device(db, scope, device_id, device_type)
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在或无权访问")
    obj.is_deleted = True
    db.commit()
    return ApiResponse.success(message="设备已删除")
