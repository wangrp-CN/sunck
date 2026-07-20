"""人员管理路由（对应需求 §2.8）。

- 列表/详情：person:list 权限 + 数据范围过滤（VIA_PROJECT：经 project.dept_id）。
- 创建：person:add 权限，自动写入 created_by。
- 更新/删除：person:edit / person:delete。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.model.person import Person
from app.model.project import Project
from app.model.system import User
from app.schema.person import PersonCreate, PersonOut, PersonPage, PersonUpdate

router = APIRouter(tags=["人员管理"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "persons", "status": "skeleton"}


def _person_out(p: Person) -> PersonOut:
    return PersonOut.model_validate(p)


@router.get(
    "",
    response_model=ApiResponse[PersonPage],
    summary="人员列表",
    dependencies=[Depends(require_permissions("person:list"))],
)
def list_persons(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    """分页查询人员，并施加数据范围过滤。"""
    stmt = select(Person).where(Person.is_deleted.is_(False))
    if keyword:
        kw = f"%{keyword}%"
        stmt = stmt.where(or_(Person.name.ilike(kw), Person.person_no.ilike(kw)))
    stmt = apply_data_scope(stmt, Person, scope)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Person.id.desc()).offset((page - 1) * size).limit(size)).all()
    return ApiResponse.success(
        PersonPage(
            items=[_person_out(p) for p in rows],
            total=total or 0,
            page=page,
            size=size,
        ),
        message="查询成功",
    )


@router.get(
    "/{person_id}",
    response_model=ApiResponse[PersonOut],
    summary="人员详情",
    dependencies=[Depends(require_permissions("person:list"))],
)
def get_person(
    person_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """返回单个人员；不在数据范围内返回 404。"""
    stmt = select(Person).where(Person.id == person_id, Person.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, Person, scope)
    person = db.scalars(stmt).first()
    if person is None:
        raise HTTPException(status_code=404, detail="人员不存在或无权访问")
    return ApiResponse.success(_person_out(person), message="获取成功")


@router.post(
    "",
    response_model=ApiResponse[PersonOut],
    summary="新建人员",
    dependencies=[Depends(require_permissions("person:add"))],
)
def create_person(
    req: PersonCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    """创建人员，写入归属项目与创建人。"""
    if (
        db.scalar(
            select(Project.id).where(Project.id == req.project_id, Project.is_deleted.is_(False))
        )
        is None
    ):
        raise BusinessError("归属项目不存在", code=400)
    person = Person(
        project_id=req.project_id,
        person_no=req.person_no,
        name=req.name,
        gender=req.gender,
        phone=req.phone,
        person_type=req.person_type,
        device_no=req.device_no,
        created_by=current.id,
    )
    db.add(person)
    db.commit()
    db.refresh(person)
    return ApiResponse.success(_person_out(person), message="人员创建成功")


@router.put(
    "/{person_id}",
    response_model=ApiResponse[PersonOut],
    summary="更新人员",
    dependencies=[Depends(require_permissions("person:edit"))],
)
def update_person(
    person_id: int,
    req: PersonUpdate,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """更新人员；仅数据范围内的可更新。"""
    stmt = select(Person).where(Person.id == person_id, Person.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, Person, scope)
    person = db.scalars(stmt).first()
    if person is None:
        raise HTTPException(status_code=404, detail="人员不存在或无权访问")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(person, field, value)
    db.commit()
    db.refresh(person)
    return ApiResponse.success(_person_out(person), message="人员更新成功")


@router.delete(
    "/{person_id}",
    response_model=ApiResponse,
    summary="删除人员",
    dependencies=[Depends(require_permissions("person:delete"))],
)
def delete_person(
    person_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """软删人员（is_deleted=True）。"""
    stmt = select(Person).where(Person.id == person_id, Person.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, Person, scope)
    person = db.scalars(stmt).first()
    if person is None:
        raise HTTPException(status_code=404, detail="人员不存在或无权访问")
    person.is_deleted = True
    db.commit()
    return ApiResponse.success(message="人员已删除")
