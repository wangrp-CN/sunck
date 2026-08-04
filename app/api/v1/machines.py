"""大型机械管理路由（对应需求 §2.8）。

- 列表/详情：machine:list 权限 + 数据范围过滤（VIA_PROJECT：经 project.dept_id）。
- 创建：machine:add 权限，自动写入 created_by。
- 更新/删除：machine:edit / machine:delete。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.model.person import Machine
from app.model.project import Project
from app.model.system import User
from app.schema.common import IdList
from app.schema.machine import MachineCreate, MachineOut, MachinePage, MachineUpdate
from app.service.batch_ops import batch_soft_delete

router = APIRouter(tags=["机械管理"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "machines", "status": "skeleton"}


def _machine_out(m: Machine) -> MachineOut:
    return MachineOut.model_validate(m)


@router.get(
    "",
    response_model=ApiResponse[MachinePage],
    summary="机械列表",
    dependencies=[Depends(require_permissions("machine:list"))],
)
def list_machines(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    """分页查询大型机械，并施加数据范围过滤。"""
    stmt = select(Machine).where(Machine.is_deleted.is_(False))
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(or_(Machine.machine_no.ilike(kw), Machine.machine_type.ilike(kw)))
    stmt = apply_data_scope(stmt, Machine, scope)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Machine.id.desc()).offset((page - 1) * size).limit(size)).all()
    return ApiResponse.success(
        MachinePage(
            items=[_machine_out(m) for m in rows],
            total=total or 0,
            page=page,
            size=size,
        ),
        message="查询成功",
    )


@router.get(
    "/{machine_id}",
    response_model=ApiResponse[MachineOut],
    summary="机械详情",
    dependencies=[Depends(require_permissions("machine:list"))],
)
def get_machine(
    machine_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """返回单个机械；不在数据范围内返回 404。"""
    stmt = select(Machine).where(Machine.id == machine_id, Machine.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, Machine, scope)
    machine = db.scalars(stmt).first()
    if machine is None:
        raise HTTPException(status_code=404, detail="机械不存在或无权访问")
    return ApiResponse.success(_machine_out(machine), message="获取成功")


@router.post(
    "",
    response_model=ApiResponse[MachineOut],
    summary="新建机械",
    dependencies=[Depends(require_permissions("machine:add"))],
)
def create_machine(
    req: MachineCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    """创建机械，写入归属项目与创建人。"""
    if (
        db.scalar(
            select(Project.id).where(Project.id == req.project_id, Project.is_deleted.is_(False))
        )
        is None
    ):
        raise BusinessError("归属项目不存在", code=400)
    machine = Machine(
        project_id=req.project_id,
        machine_no=req.machine_no,
        machine_type=req.machine_type,
        spec_model=req.spec_model,
        description=req.description,
        created_by=current.id,
    )
    db.add(machine)
    db.commit()
    db.refresh(machine)
    return ApiResponse.success(_machine_out(machine), message="机械创建成功")


@router.put(
    "/{machine_id}",
    response_model=ApiResponse[MachineOut],
    summary="更新机械",
    dependencies=[Depends(require_permissions("machine:edit"))],
)
def update_machine(
    machine_id: int,
    req: MachineUpdate,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """更新机械；仅数据范围内的可更新。"""
    stmt = select(Machine).where(Machine.id == machine_id, Machine.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, Machine, scope)
    machine = db.scalars(stmt).first()
    if machine is None:
        raise HTTPException(status_code=404, detail="机械不存在或无权访问")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(machine, field, value)
    db.commit()
    db.refresh(machine)
    return ApiResponse.success(_machine_out(machine), message="机械更新成功")


@router.delete(
    "/{machine_id}",
    response_model=ApiResponse,
    summary="删除机械",
    dependencies=[Depends(require_permissions("machine:delete"))],
)
def delete_machine(
    machine_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """软删机械（is_deleted=True）。"""
    stmt = select(Machine).where(Machine.id == machine_id, Machine.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, Machine, scope)
    machine = db.scalars(stmt).first()
    if machine is None:
        raise HTTPException(status_code=404, detail="机械不存在或无权访问")
    machine.is_deleted = True
    db.commit()
    return ApiResponse.success(message="机械已删除")


@router.post(
    "/batch-delete",
    response_model=ApiResponse,
    summary="批量删除机械（软删）",
    dependencies=[Depends(require_permissions("machine:delete"))],
)
def batch_delete(
    items: IdList,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """批量软删：仅删除数据范围内、尚未删除的记录；返回删除条数与跳过条数。"""
    deleted = batch_soft_delete(Machine, db, scope, items.ids)
    total = len(items.ids)
    db.commit()
    return ApiResponse.success(
        data={"deleted": deleted, "total": total, "skipped": total - deleted},
        message=f"已删除 {deleted} 条",
    )
