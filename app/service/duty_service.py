"""值班排班服务（🅱 告警治理与值班体系）。

提供排班 CRUD、当前值班查询（resolve_on_duty），供告警自动派单与升级通知复用。
遵循 SOP：服务内不提交事务，由调用端点统一 commit。
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope, apply_data_scope
from app.core.exceptions import BusinessError
from app.model.duty_roster import DutyRoster
from app.model.project import Project
from app.model.system import User
from app.schema.duty import DutyRosterOut, DutyRosterUpdate


def _base_stmt(scope: DataScope):
    stmt = select(DutyRoster).where(DutyRoster.is_deleted.is_(False))
    return apply_data_scope(stmt, DutyRoster, scope)


def _validate_refs(db: Session, project_id: int | None, user_id: int | None) -> None:
    if project_id is not None:
        proj = db.scalar(
            select(Project.id).where(Project.id == project_id, Project.is_deleted.is_(False))
        )
        if proj is None:
            raise BusinessError(f"归属项目不存在或已删除（project_id={project_id}）", code=400)
    if user_id is not None:
        u = db.get(User, user_id)
        if u is None or u.is_deleted:
            raise BusinessError(f"值班人不存在或已删除（user_id={user_id}）", code=400)


def create_roster(db: Session, scope: DataScope, creator_id: int | None, data) -> DutyRoster:
    _validate_refs(db, data.project_id, data.user_id)
    if data.end_time <= data.start_time:
        raise BusinessError("值班结束时间须晚于开始时间", code=400)
    obj = DutyRoster(
        project_id=data.project_id,
        user_id=data.user_id,
        shift=data.shift,
        duty_role=data.duty_role,
        start_time=data.start_time,
        end_time=data.end_time,
        note=data.note,
        created_by=creator_id,
    )
    db.add(obj)
    db.flush()
    return obj


def list_rosters(
    db: Session,
    scope: DataScope,
    *,
    project_id: int | None = None,
    user_id: int | None = None,
    active: bool | None = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    page = max(1, page)
    size = max(1, min(size, 200))
    stmt = _base_stmt(scope)
    if project_id is not None:
        stmt = stmt.where(DutyRoster.project_id == project_id)
    if user_id is not None:
        stmt = stmt.where(DutyRoster.user_id == user_id)
    if active is True:
        now = datetime.now(timezone.utc)
        stmt = stmt.where(DutyRoster.start_time <= now, DutyRoster.end_time >= now)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(DutyRoster.start_time.desc(), DutyRoster.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return {"total": total, "items": rows, "page": page, "size": size}


def get_roster(db: Session, scope: DataScope, rid: int) -> DutyRoster | None:
    return db.scalars(_base_stmt(scope).where(DutyRoster.id == rid)).first()


def update_roster(
    db: Session, scope: DataScope, rid: int, data: DutyRosterUpdate
) -> DutyRoster | None:
    obj = get_roster(db, scope, rid)
    if obj is None:
        return None
    if data.project_id is not None or data.user_id is not None:
        _validate_refs(db, data.project_id, data.user_id)
    for f in ("project_id", "user_id", "shift", "duty_role", "start_time", "end_time", "note"):
        v = getattr(data, f, None)
        if v is not None:
            setattr(obj, f, v)
    if obj.end_time <= obj.start_time:
        raise BusinessError("值班结束时间须晚于开始时间", code=400)
    db.flush()
    return obj


def delete_roster(db: Session, scope: DataScope, rid: int) -> bool:
    obj = get_roster(db, scope, rid)
    if obj is None:
        return False
    obj.is_deleted = True
    db.flush()
    return True


def resolve_on_duty(
    db: Session, project_id: int | None, now: datetime | None = None
) -> tuple[int | None, str | None]:
    """返回 (user_id, user_name) 当前在 project 当班的人；无则 (None, None)。

    用于告警自动派单、升级通知当班人。同一时刻多个当班取开始最早的一条。
    """
    if project_id is None:
        return (None, None)
    now = now or datetime.now(timezone.utc)
    row = db.scalars(
        select(DutyRoster)
        .where(
            DutyRoster.is_deleted.is_(False),
            DutyRoster.project_id == project_id,
            DutyRoster.start_time <= now,
            DutyRoster.end_time >= now,
        )
        .order_by(DutyRoster.start_time.asc())
    ).first()
    if row is None or row.user_id is None:
        return (None, None)
    u = db.get(User, row.user_id)
    name = (u.nickname or u.username) if u else None
    return (row.user_id, name)


def to_out(db: Session, obj: DutyRoster, now: datetime | None = None) -> DutyRosterOut:
    """构造带展示字段（值班人/项目名/是否在班）的输出对象。"""
    now = now or datetime.now(timezone.utc)
    out = DutyRosterOut.model_validate(obj)
    if obj.user_id is not None:
        u = db.get(User, obj.user_id)
        out.user_name = (u.nickname or u.username) if u else None
    if obj.project_id is not None:
        p = db.get(Project, obj.project_id)
        out.project_name = p.name if p else None
    out.is_current = bool(obj.start_time <= now <= obj.end_time)
    return out
