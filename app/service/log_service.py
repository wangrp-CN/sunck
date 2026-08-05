"""系统日志服务层：写入、分页查询、元数据检索。

与操作审计（AuditLog）的服务层独立，SystemLog 面向运维监控场景。
"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.model.log import SystemLog
from app.schema.log import (
    SystemLogMetaOut,
    SystemLogOut,
    SystemLogPage,
)

# 导出级别枚举常量
LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _model_to_out(m: SystemLog) -> SystemLogOut:
    return SystemLogOut.model_validate(m)


# ── 写入 ──────────────────────────────────────────────────


def write_system_log(
    db: Session,
    *,
    level: str = "INFO",
    module: str,
    message: str,
    detail: str | None = None,
    traceback: str | None = None,
    source: str | None = None,
    user_id: int | None = None,
) -> SystemLog:
    """写入一条系统日志。不 commit，由调用方决定事务边界。"""
    if level not in LOG_LEVELS:
        level = "INFO"
    rec = SystemLog(
        level=level,
        module=module,
        message=message,
        detail=detail,
        traceback=traceback,
        source=source,
        user_id=user_id,
    )
    db.add(rec)
    db.flush()
    return rec


# ── 查询 ──────────────────────────────────────────────────


def list_system_logs(
    db: Session,
    *,
    level: str | None = None,
    module: str | None = None,
    keyword: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = 1,
    size: int = 20,
) -> SystemLogPage:
    """分页查询系统日志，支持按级别/模块/关键词/时间范围过滤。"""
    page = max(1, page)
    size = max(1, size)
    stmt = select(SystemLog)
    if level:
        stmt = stmt.where(SystemLog.level == level.upper())
    if module:
        stmt = stmt.where(SystemLog.module == module)
    if keyword:
        stmt = stmt.where(SystemLog.message.ilike(f"%{keyword}%"))
    if start is not None:
        stmt = stmt.where(SystemLog.created_at >= start)
    if end is not None:
        stmt = stmt.where(SystemLog.created_at <= end)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(SystemLog.created_at.desc().nullslast(), SystemLog.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return SystemLogPage(
        total=total,
        items=[_model_to_out(r) for r in rows],
        page=page,
        size=size,
    )


def get_system_log_meta(db: Session) -> SystemLogMetaOut:
    """返回库中已出现的日志级别和模块，供前端下拉筛选。"""
    from sqlalchemy import distinct

    levels = [
        lvl
        for lvl in db.scalars(select(distinct(SystemLog.level)).where(SystemLog.level != "")).all()
        if lvl
    ]
    modules = [
        mod
        for mod in db.scalars(
            select(distinct(SystemLog.module)).where(SystemLog.module != "")
        ).all()
        if mod
    ]
    return SystemLogMetaOut(levels=levels, modules=modules)


# ── 清理 ──────────────────────────────────────────────────


def clean_old_logs(db: Session, *, before: datetime) -> int:
    """清理指定时间之前的系统日志（物理删除），返回删除条数。"""
    from sqlalchemy import delete

    result = db.execute(delete(SystemLog).where(SystemLog.created_at < before))
    return int(result.rowcount or 0)
