"""项目管理路由（对应需求 §2.4），已接入部门数据隔离。

- 列表/详情：project:list 权限 + 数据范围过滤（按 project.dept_id 或创建人）。
- 创建：project:add 权限，自动写入 created_by 为当前用户。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.model.project import Project
from app.model.system import Department, User
from app.schema.project import ProjectCreate, ProjectOut, ProjectPage, ProjectUpdate

router = APIRouter(tags=["项目管理"])


def _project_out(p: Project) -> ProjectOut:
    return ProjectOut.model_validate(p)


@router.get(
    "",
    response_model=ApiResponse[ProjectPage],
    summary="项目列表",
    dependencies=[Depends(require_permissions("project:list"))],
)
def list_projects(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    """分页查询项目，并施加部门数据隔离（本部门及以下/自定义部门/仅本人）。"""
    stmt = select(Project).where(Project.is_deleted.is_(False))
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(Project.name.ilike(kw))
    stmt = apply_data_scope(stmt, Project, scope)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Project.id.desc()).offset((page - 1) * size).limit(size)).all()
    return ApiResponse.success(
        ProjectPage(
            items=[_project_out(p) for p in rows],
            total=total or 0,
            page=page,
            size=size,
        ),
        message="查询成功",
    )


@router.get(
    "/{project_id}",
    response_model=ApiResponse[ProjectOut],
    summary="项目详情",
    dependencies=[Depends(require_permissions("project:list"))],
)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """返回单个项目；不在当前用户数据范围内则返回 404（对外不暴露越权）。"""
    stmt = select(Project).where(Project.id == project_id, Project.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, Project, scope)
    project = db.scalars(stmt).first()
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")
    return ApiResponse.success(_project_out(project), message="获取成功")


@router.post(
    "",
    response_model=ApiResponse[ProjectOut],
    summary="新建项目",
    dependencies=[Depends(require_permissions("project:add"))],
)
def create_project(
    req: ProjectCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    """创建项目，自动记录归属部门与创建人（供数据范围过滤）。"""
    if (
        db.scalar(
            select(Department.id).where(
                Department.id == req.dept_id, Department.is_deleted.is_(False)
            )
        )
        is None
    ):
        raise BusinessError("归属部门不存在", code=400)
    project = Project(
        name=req.name,
        dept_id=req.dept_id,
        short_name=req.short_name,
        intro=req.intro,
        start_date=req.start_date,
        end_date=req.end_date,
        duration=req.duration,
        mileage=req.mileage,
        section=req.section,
        coordinate=req.coordinate,
        status=req.status,
        created_by=current.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return ApiResponse.success(_project_out(project), message="项目创建成功")


@router.put(
    "/{project_id}",
    response_model=ApiResponse[ProjectOut],
    summary="更新项目",
    dependencies=[Depends(require_permissions("project:edit"))],
)
def update_project(
    project_id: int,
    req: ProjectUpdate,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """更新项目；仅当前数据范围内的项目可更新。"""
    stmt = select(Project).where(Project.id == project_id, Project.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, Project, scope)
    project = db.scalars(stmt).first()
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return ApiResponse.success(_project_out(project), message="项目更新成功")


@router.delete(
    "/{project_id}",
    response_model=ApiResponse,
    summary="删除项目",
    dependencies=[Depends(require_permissions("project:delete"))],
)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """软删项目（is_deleted=True）；仅当前数据范围内的项目可删。"""
    stmt = select(Project).where(Project.id == project_id, Project.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, Project, scope)
    project = db.scalars(stmt).first()
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在或无权访问")
    project.is_deleted = True
    db.commit()
    return ApiResponse.success(message="项目已删除")
