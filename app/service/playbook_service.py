"""处置预案服务（🅱 M5 处置预案/知识库联动）。

- CRUD：列表（按项目/类型/级别/启用过滤）、详情、新增、编辑、逻辑删除；
- 匹配引擎 ``resolve_playbooks``：按「项目×类型×级别」特异性为某条告警推荐处置预案，
  供告警处置时联动展示（闭环处置指导）；
- 遵循 SOP：服务内不提交事务，由调用端点 / job 统一 commit。
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope, apply_data_scope
from app.core.exceptions import BusinessError
from app.model.alarm import Alarm
from app.model.playbook import Playbook
from app.model.project import Project
from app.schema.playbook import encode_json

logger = logging.getLogger("rail_monitor.playbook")

_VALID_LEVELS = ("提示", "警告", "严重")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def _base_stmt(scope: DataScope):
    stmt = select(Playbook).where(Playbook.is_deleted.is_(False))
    return apply_data_scope(stmt, Playbook, scope)


def _validate(db: Session, project_id: int | None, alarm_level: str | None) -> None:
    if project_id is not None:
        proj = db.scalar(
            select(Project.id).where(Project.id == project_id, Project.is_deleted.is_(False))
        )
        if proj is None:
            raise BusinessError(f"归属项目不存在或已删除（project_id={project_id}）", code=400)
    # 空串 "" 视为「不限级别」(None)，不校验
    if alarm_level and alarm_level not in _VALID_LEVELS:
        raise BusinessError(f"关联级别须为 {'/'.join(_VALID_LEVELS)}", code=400)


def create_playbook(db: Session, scope: DataScope, creator_id: int | None, data) -> Playbook:
    _validate(db, data.project_id, data.alarm_level)
    obj = Playbook(
        name=data.name,
        project_id=data.project_id,
        alarm_type=data.alarm_type or None,
        alarm_level=data.alarm_level,
        enabled=data.enabled,
        summary=data.summary,
        steps=encode_json(data.steps),
        trigger_condition=data.trigger_condition,
        references=encode_json(data.references),
        tags=data.tags,
        owner_role=data.owner_role,
        est_minutes=data.est_minutes,
        note=data.note,
        created_by=creator_id,
    )
    db.add(obj)
    db.flush()
    return obj


def list_playbooks(
    db: Session,
    scope: DataScope,
    *,
    project_id: int | None = None,
    alarm_type: str | None = None,
    alarm_level: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    page = max(1, page)
    size = max(1, min(size, 200))
    stmt = _base_stmt(scope)
    if project_id is not None:
        stmt = stmt.where(Playbook.project_id == project_id)
    if alarm_type is not None:
        stmt = stmt.where(Playbook.alarm_type == alarm_type)
    if alarm_level is not None:
        stmt = stmt.where(Playbook.alarm_level == alarm_level)
    if enabled is not None:
        stmt = stmt.where(Playbook.enabled.is_(enabled))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Playbook.id.desc()).offset((page - 1) * size).limit(size)).all()
    return {"total": total, "items": rows, "page": page, "size": size}


def get_playbook(db: Session, scope: DataScope, pid: int) -> Playbook | None:
    return db.scalars(_base_stmt(scope).where(Playbook.id == pid)).first()


def update_playbook(db: Session, scope: DataScope, pid: int, data) -> Playbook | None:
    obj = get_playbook(db, scope, pid)
    if obj is None:
        return None
    _validate(db, data.project_id, data.alarm_level)
    # 标量字段：None = 不变，空串 "" = 清除
    for f in (
        "name",
        "project_id",
        "alarm_type",
        "alarm_level",
        "summary",
        "tags",
        "owner_role",
        "note",
    ):
        v = getattr(data, f, None)
        if v is None:
            continue
        if f in ("alarm_type", "alarm_level"):
            v = v or None
        setattr(obj, f, v)
    if data.enabled is not None:
        obj.enabled = data.enabled
    if data.steps is not None:
        obj.steps = encode_json(data.steps)
    if data.references is not None:
        obj.references = encode_json(data.references)
    if data.trigger_condition is not None:
        obj.trigger_condition = data.trigger_condition or None
    if data.est_minutes is not None:
        obj.est_minutes = data.est_minutes or None
    db.flush()
    return obj


def delete_playbook(db: Session, scope: DataScope, pid: int) -> bool:
    obj = get_playbook(db, scope, pid)
    if obj is None:
        return False
    obj.is_deleted = True
    db.flush()
    return True


def to_out(db: Session, obj: Playbook) -> dict:
    out = obj.__dict__.copy()
    out.pop("_sa_instance_state", None)
    out["project_name"] = None
    if obj.project_id is not None:
        p = db.get(Project, obj.project_id)
        out["project_name"] = p.name if p else None
    return out


# ---------------------------------------------------------------------------
# 匹配引擎：为某条告警推荐处置预案
# ---------------------------------------------------------------------------


def _specificity(
    p: Playbook, project_id: int | None, alarm_type: str | None, alarm_level: str | None
) -> tuple[int, int, int, int]:
    """特异性评分：项目命中 > 类型命中 > 级别命中 > id（越大越新）。

    级别匹配语义：查询指定级别时，级别精确匹配的预案优先；查询不限级别时，
    级别通配(``alarm_level=None``)的通用预案优先于绑定了具体级别的预案。
    """
    proj_match = 1 if (project_id is not None and p.project_id == project_id) else 0
    type_match = 1 if (alarm_type is not None and p.alarm_type == alarm_type) else 0
    if alarm_level is not None:
        level_match = 1 if (p.alarm_level is not None and p.alarm_level == alarm_level) else 0
    else:
        # 查询不限级别：通配(None)优先，绑定具体级别视为 -1
        level_match = 0 if p.alarm_level is None else -1
    return (proj_match, type_match, level_match, p.id)


def resolve_playbooks(
    db: Session,
    scope: DataScope,
    project_id: int | None,
    alarm_type: str | None,
    alarm_level: str | None,
    limit: int = 5,
) -> list[Playbook]:
    """为 (project_id, alarm_type, alarm_level) 推荐处置预案。

    命中规则：启用 + 未删除 + 当前数据范围可见，且
    - 类型：预案 ``alarm_type`` 为空(通用) 或 与告警类型相同；
    - 级别：预案 ``alarm_level`` 为空(不限) 或 与告警级别相同。
    排序：特异性（项目>类型>级别）降序，同分取 id 大者；截断 ``limit``。
    """
    rows = db.scalars(_base_stmt(scope)).all()
    candidates = [
        p
        for p in rows
        if p.enabled
        and (p.project_id is None or (project_id is not None and p.project_id == project_id))
        and (p.alarm_type is None or (alarm_type is not None and p.alarm_type == alarm_type))
        and (p.alarm_level is None or (alarm_level is not None and p.alarm_level == alarm_level))
    ]
    candidates.sort(
        key=lambda p: _specificity(p, project_id, alarm_type, alarm_level),
        reverse=True,
    )
    return candidates[:limit]


def recommend_for_alarm(
    db: Session, scope: DataScope, alarm_id: int, limit: int = 5
) -> list[Playbook]:
    """按告警 ID 直接推荐处置预案（取其 project_id/type/level）。"""
    alarm = db.get(Alarm, alarm_id)
    if alarm is None:
        return []
    return resolve_playbooks(
        db, scope, alarm.project_id, alarm.alarm_type, alarm.alarm_level, limit=limit
    )
