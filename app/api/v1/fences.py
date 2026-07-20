"""电子围栏管理路由（对应需求 §2.5，基于高德地图绘制多边形区域）。

- 列表/详情：fence:list 权限 + 数据范围过滤（VIA_PROJECT：经 project.dept_id）。
- 创建：fence:add 权限，自动写入 created_by。
- 更新/删除：fence:edit / fence:delete。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.model.fence import ElectronicFence
from app.model.project import Project
from app.model.system import User
from app.schema.fence import FenceCreate, FenceOut, FencePage, FenceUpdate

router = APIRouter(tags=["电子围栏"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "fences", "status": "skeleton"}


def _fence_out(f: ElectronicFence) -> FenceOut:
    return FenceOut.model_validate(f)


@router.get(
    "",
    response_model=ApiResponse[FencePage],
    summary="围栏列表",
    dependencies=[Depends(require_permissions("fence:list"))],
)
def list_fences(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    """分页查询电子围栏，并施加数据范围过滤。"""
    stmt = select(ElectronicFence).where(ElectronicFence.is_deleted.is_(False))
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(or_(ElectronicFence.name.ilike(kw), ElectronicFence.fence_type.ilike(kw)))
    stmt = apply_data_scope(stmt, ElectronicFence, scope)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(
        stmt.order_by(ElectronicFence.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return ApiResponse.success(
        FencePage(
            items=[_fence_out(f) for f in rows],
            total=total or 0,
            page=page,
            size=size,
        ),
        message="查询成功",
    )


@router.get(
    "/{fence_id}",
    response_model=ApiResponse[FenceOut],
    summary="围栏详情",
    dependencies=[Depends(require_permissions("fence:list"))],
)
def get_fence(
    fence_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """返回单个围栏；不在数据范围内返回 404。"""
    stmt = select(ElectronicFence).where(
        ElectronicFence.id == fence_id, ElectronicFence.is_deleted.is_(False)
    )
    stmt = apply_data_scope(stmt, ElectronicFence, scope)
    fence = db.scalars(stmt).first()
    if fence is None:
        raise HTTPException(status_code=404, detail="围栏不存在或无权访问")
    return ApiResponse.success(_fence_out(fence), message="获取成功")


@router.post(
    "",
    response_model=ApiResponse[FenceOut],
    summary="新建围栏",
    dependencies=[Depends(require_permissions("fence:add"))],
)
def create_fence(
    req: FenceCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    """创建围栏，写入归属项目与创建人。"""
    if (
        db.scalar(
            select(Project.id).where(Project.id == req.project_id, Project.is_deleted.is_(False))
        )
        is None
    ):
        raise BusinessError("归属项目不存在", code=400)
    fence = ElectronicFence(
        project_id=req.project_id,
        name=req.name,
        fence_type=req.fence_type,
        enabled=req.enabled,
        geometry_wkt=req.geometry_wkt,
        created_by=current.id,
    )
    db.add(fence)
    db.commit()
    db.refresh(fence)
    return ApiResponse.success(_fence_out(fence), message="围栏创建成功")


@router.put(
    "/{fence_id}",
    response_model=ApiResponse[FenceOut],
    summary="更新围栏",
    dependencies=[Depends(require_permissions("fence:edit"))],
)
def update_fence(
    fence_id: int,
    req: FenceUpdate,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """更新围栏；仅数据范围内的可更新。"""
    stmt = select(ElectronicFence).where(
        ElectronicFence.id == fence_id, ElectronicFence.is_deleted.is_(False)
    )
    stmt = apply_data_scope(stmt, ElectronicFence, scope)
    fence = db.scalars(stmt).first()
    if fence is None:
        raise HTTPException(status_code=404, detail="围栏不存在或无权访问")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(fence, field, value)
    db.commit()
    db.refresh(fence)
    return ApiResponse.success(_fence_out(fence), message="围栏更新成功")


@router.delete(
    "/{fence_id}",
    response_model=ApiResponse,
    summary="删除围栏",
    dependencies=[Depends(require_permissions("fence:delete"))],
)
def delete_fence(
    fence_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """软删围栏（is_deleted=True）。"""
    stmt = select(ElectronicFence).where(
        ElectronicFence.id == fence_id, ElectronicFence.is_deleted.is_(False)
    )
    stmt = apply_data_scope(stmt, ElectronicFence, scope)
    fence = db.scalars(stmt).first()
    if fence is None:
        raise HTTPException(status_code=404, detail="围栏不存在或无权访问")
    fence.is_deleted = True
    db.commit()
    return ApiResponse.success(message="围栏已删除")
