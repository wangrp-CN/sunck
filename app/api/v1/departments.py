"""部门管理路由：列表、树形、创建、更新、删除（部门数据隔离的基础数据）。

权限：dept:list / dept:add / dept:edit / dept:delete（见种子权限 system 模块）。
部门树本身不做数据范围过滤——部门管理属于组织管理职能，由具备权限者维护；
真正的数据隔离体现在业务数据（项目/设备等）查询时。
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.model.system import Department, User
from app.schema.department import DepartmentCreate, DepartmentOut, DepartmentTree, DepartmentUpdate

router = APIRouter(tags=["部门管理"])


def _dept_out(d: Department) -> DepartmentOut:
    return DepartmentOut.model_validate(d)


@router.get(
    "",
    response_model=ApiResponse[list[DepartmentOut]],
    summary="部门列表(扁平)",
    dependencies=[Depends(require_permissions("dept:list"))],
)
def list_departments(
    db: Session = Depends(get_db),
    keyword: str | None = None,
) -> ApiResponse:
    """返回全部（未删除）部门，支持按名称/编码模糊搜索。"""
    stmt = select(Department).where(Department.is_deleted.is_(False))
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(Department.name.ilike(kw) | Department.code.ilike(kw))
    rows = db.scalars(stmt.order_by(Department.sort, Department.id)).all()
    return ApiResponse.success([_dept_out(d) for d in rows], message="查询成功")


@router.get(
    "/tree",
    response_model=ApiResponse[list[DepartmentTree]],
    summary="部门树形结构",
    dependencies=[Depends(require_permissions("dept:list"))],
)
def department_tree(db: Session = Depends(get_db)) -> ApiResponse:
    """将扁平部门列表组装为树形结构返回。"""
    rows = db.scalars(
        select(Department)
        .where(Department.is_deleted.is_(False))
        .order_by(Department.sort, Department.id)
    ).all()
    by_id = {d.id: DepartmentTree.model_validate(d) for d in rows}
    roots: list[DepartmentTree] = []
    for node in by_id.values():
        parent = by_id.get(node.parent_id) if node.parent_id else None
        if parent is not None:
            parent.children.append(node)
        else:
            roots.append(node)
    return ApiResponse.success(roots, message="查询成功")


@router.post(
    "",
    response_model=ApiResponse[DepartmentOut],
    summary="新建部门",
    dependencies=[Depends(require_permissions("dept:add"))],
)
def create_department(req: DepartmentCreate, db: Session = Depends(get_db)) -> ApiResponse:
    """创建部门，校验编码唯一性与上级部门存在性。"""
    if db.scalar(
        select(Department.id).where(Department.code == req.code, Department.is_deleted.is_(False))
    ):
        raise BusinessError("部门编码已存在", code=409)
    if req.parent_id is not None:
        parent = db.get(Department, req.parent_id)
        if parent is None or parent.is_deleted:
            raise BusinessError("上级部门不存在", code=400)
    dept = Department(
        name=req.name,
        code=req.code,
        parent_id=req.parent_id,
        leader=req.leader,
        phone=req.phone,
        sort=req.sort,
        status=req.status,
        remark=req.remark,
    )
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return ApiResponse.success(_dept_out(dept), message="部门创建成功")


@router.put(
    "/{dept_id}",
    response_model=ApiResponse[DepartmentOut],
    summary="更新部门",
    dependencies=[Depends(require_permissions("dept:edit"))],
)
def update_department(
    dept_id: int, req: DepartmentUpdate, db: Session = Depends(get_db)
) -> ApiResponse:
    dept = db.get(Department, dept_id)
    if dept is None or dept.is_deleted:
        raise BusinessError("部门不存在", code=404)
    if req.name is not None:
        dept.name = req.name
    if req.parent_id is not None and req.parent_id != dept.id:
        parent = db.get(Department, req.parent_id)
        if parent is None or parent.is_deleted:
            raise BusinessError("上级部门不存在", code=400)
        # 防止将部门挂到自己的子孙下（形成环）
        if req.parent_id in _descendant_ids(db, dept.id):
            raise BusinessError("不能将部门挂到其下级部门之下", code=400)
        dept.parent_id = req.parent_id
    elif req.parent_id is None:
        dept.parent_id = None
    if req.leader is not None:
        dept.leader = req.leader
    if req.phone is not None:
        dept.phone = req.phone
    if req.sort is not None:
        dept.sort = req.sort
    if req.status is not None:
        dept.status = req.status
    if req.remark is not None:
        dept.remark = req.remark
    db.commit()
    db.refresh(dept)
    return ApiResponse.success(_dept_out(dept), message="部门更新成功")


@router.delete(
    "/{dept_id}",
    response_model=ApiResponse[None],
    summary="删除部门(软删)",
    dependencies=[Depends(require_permissions("dept:delete"))],
)
def delete_department(dept_id: int, db: Session = Depends(get_db)) -> ApiResponse:
    dept = db.get(Department, dept_id)
    if dept is None or dept.is_deleted:
        raise BusinessError("部门不存在", code=404)
    # 保护：存在下级部门禁止删除
    if db.scalar(
        select(Department.id).where(
            Department.parent_id == dept_id, Department.is_deleted.is_(False)
        )
    ):
        raise BusinessError("该部门下存在子部门，请先处理子部门", code=409)
    # 保护：仍有用户归属该部门
    if db.scalar(select(User.id).where(User.dept_id == dept_id, User.is_deleted.is_(False))):
        raise BusinessError("仍有用户归属该部门，无法删除", code=409)
    dept.is_deleted = True
    db.commit()
    return ApiResponse.success(message="部门已删除")


def _descendant_ids(db: Session, root_id: int) -> set[int]:
    """返回 root 的所有后代部门 ID（不含自身），用于环检测。"""
    result: set[int] = set()
    current: set[int] = {root_id}
    while current:
        rows = db.scalars(
            select(Department.id).where(
                Department.parent_id.in_(current), Department.is_deleted.is_(False)
            )
        ).all()
        current = set(rows)
        result |= current
    return result
