"""操作审计服务层：列表检索（受部门数据范围约束）与写辅助。

- 列表查询按当前用户的数据范围过滤：仅可见本部门及以下部门操作员产生的审计记录
  （与全站数据隔离一致）。超级管理员可见全部。
- `write_audit_log` 供显式语义化记录（如指令下发）复用，中间件自动记录亦调用底层落库。
"""

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope
from app.model.audit import AuditLog
from app.schema.audit import AuditLogOut, AuditLogPage


def _scope_stmt(stmt, scope: DataScope):
    """按数据范围过滤审计记录：仅可见本部门及以下操作员的记录。"""
    if scope.is_all:
        return stmt
    conds = []
    if scope.dept_ids:
        conds.append(AuditLog.dept_id.in_(scope.dept_ids))
    if scope.include_self and scope.self_user_id is not None:
        conds.append(AuditLog.user_id == scope.self_user_id)
    if not conds:
        from sqlalchemy import false as sa_false

        return stmt.where(sa_false())
    return stmt.where(or_(*conds))


def list_audit_logs(
    db: Session,
    scope: DataScope,
    *,
    module: str | None = None,
    action: str | None = None,
    username: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = 1,
    size: int = 20,
) -> AuditLogPage:
    page = max(1, page)
    size = max(1, size)
    stmt = select(AuditLog)
    stmt = _scope_stmt(stmt, scope)
    if module:
        stmt = stmt.where(AuditLog.module == module)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if username:
        stmt = stmt.where(AuditLog.username.ilike(f"%{username}%"))
    if start is not None:
        stmt = stmt.where(AuditLog.created_at >= start)
    if end is not None:
        stmt = stmt.where(AuditLog.created_at <= end)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AuditLog.created_at.desc().nullslast(), AuditLog.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return AuditLogPage(
        total=total,
        items=[AuditLogOut.model_validate(r) for r in rows],
        page=page,
        size=size,
    )


def write_audit_log(
    db: Session,
    *,
    user_id: int | None = None,
    username: str | None = None,
    dept_id: int | None = None,
    action: str,
    module: str,
    method: str,
    path: str,
    query: str | None = None,
    status_code: int = 200,
    ip: str | None = None,
    detail: str | None = None,
) -> AuditLog:
    """显式写入一条审计记录（指令下发等语义动作复用）。"""
    rec = AuditLog(
        user_id=user_id,
        username=username,
        dept_id=dept_id,
        action=action,
        module=module,
        method=method,
        path=path,
        query=query,
        status_code=status_code,
        ip=ip,
        detail=detail,
    )
    db.add(rec)
    db.flush()
    return rec
