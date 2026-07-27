"""根因派单闭环服务（#80）。

把跨设备共因事件组 / 告警 / 人工建单转为可跟踪的处置工单（DispatchOrder），
经状态机（待派→处理中→已闭环）流转，并对处理人下发站内信通知。
遵循 SOP：服务内不提交事务，由调用端点统一 commit。
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import (
    DISPATCH_SOURCE_ALARM,
    DISPATCH_SOURCE_CORRELATION,
    DISPATCH_TRANSITIONS,
)
from app.core.data_scope import DataScope, apply_data_scope
from app.core.exceptions import BusinessError
from app.core.notify import notify
from app.model.alarm import Alarm
from app.model.correlation import CorrelatedEventGroup
from app.model.dispatch import DispatchOrder
from app.model.project import Project
from app.model.system import User

logger = logging.getLogger("rail_monitor.dispatch")


def _base_stmt(scope: DataScope):
    stmt = select(DispatchOrder).where(DispatchOrder.is_deleted.is_(False))
    return apply_data_scope(stmt, DispatchOrder, scope)


def _resolve_source(db: Session, source_type: str, source_id: int | None) -> dict:
    """解析来源记录，返回 {project_id, root_cause_hint, level}；来源缺失返回空字典。"""
    out: dict = {}
    if not source_id:
        return out
    if source_type == DISPATCH_SOURCE_CORRELATION:
        g = db.get(CorrelatedEventGroup, source_id)
        if g is not None:
            out["project_id"] = g.project_id
            out["root_cause_hint"] = g.root_cause_hint
            out["level"] = g.max_level
    elif source_type == DISPATCH_SOURCE_ALARM:
        a = db.get(Alarm, source_id)
        if a is not None:
            out["project_id"] = a.project_id
            out["level"] = a.alarm_level
    return out


def _user_name(db: Session, uid: int | None) -> str | None:
    if uid is None:
        return None
    u = db.get(User, uid)
    return (u.nickname or u.username) if u else None


def create_order(db: Session, scope: DataScope, creator_id: int | None, data) -> DispatchOrder:
    """创建派单（可来自共因事件组/告警/人工）。返回新建订单（未提交）。"""
    src = _resolve_source(db, data.source_type, data.source_id)
    project_id = data.project_id if data.project_id is not None else src.get("project_id")
    if project_id is None and data.source_type != "manual":
        # 来源解析不到项目时退回 manual 处理；manual 必须有 project_id
        pass
    if project_id is None:
        raise BusinessError("派单必须归属项目（manual 来源请填写 project_id）")

    # 归属项目存在性校验：避免不存在的 project_id 触发外键违反（500）。
    # 兼容 data_scope：超管可访问任意项目；受限用户须满足部门/创建人隔离。
    proj = db.scalar(
        select(Project.id).where(Project.id == project_id, Project.is_deleted.is_(False))
    )
    if proj is None:
        raise BusinessError(
            f"归属项目不存在或已被删除（project_id={project_id}），请重新选择",
            code=400,
        )

    assignee_name = _user_name(db, data.assignee_id)
    order = DispatchOrder(
        project_id=project_id,
        source_type=data.source_type,
        source_id=data.source_id,
        title=data.title,
        root_cause_hint=data.root_cause_hint or src.get("root_cause_hint"),
        level=data.level or src.get("level"),
        status="待派",
        assignee_id=data.assignee_id,
        assignee_name=assignee_name,
        deadline=data.deadline,
        description=data.description,
        created_by=creator_id,
    )
    db.add(order)
    db.flush()
    if data.assignee_id is not None:
        notify(
            db,
            [data.assignee_id],
            f"新派单：{order.title}",
            content=order.root_cause_hint or "请及时处理",
            link="/dispatch",
            category="dispatch",
            channels=("in_app",),
        )
    return order


def list_orders(
    db: Session,
    scope: DataScope,
    *,
    status: str | None = None,
    source_type: str | None = None,
    project_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    """分页列表（受数据范围约束），返回 {total, items, page, size}。"""
    page = max(1, page)
    size = max(1, min(size, 200))
    stmt = _base_stmt(scope)
    if status is not None:
        stmt = stmt.where(DispatchOrder.status == status)
    if source_type is not None:
        stmt = stmt.where(DispatchOrder.source_type == source_type)
    if project_id is not None:
        stmt = stmt.where(DispatchOrder.project_id == project_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(DispatchOrder.created_at.desc().nullslast(), DispatchOrder.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return {"total": total, "items": rows, "page": page, "size": size}


def get_order(db: Session, scope: DataScope, order_id: int) -> DispatchOrder | None:
    return db.scalars(_base_stmt(scope).where(DispatchOrder.id == order_id)).first()


def apply_action(
    db: Session,
    scope: DataScope,
    order_id: int,
    action: str,
    note: str | None,
    actor_id: int | None,
) -> DispatchOrder | None:
    """状态机动作流转（start/close/reopen）。返回更新后的订单。"""
    if action not in DISPATCH_TRANSITIONS:
        from app.core.exceptions import BusinessError

        raise BusinessError(f"非法动作：{action}")
    order = get_order(db, scope, order_id)
    if order is None:
        return None
    cur, target = DISPATCH_TRANSITIONS[action]
    if order.status != cur:
        from app.core.exceptions import BusinessError

        raise BusinessError(f"当前状态[{order.status}]不可执行[{action}]（需[{cur}]）")
    order.status = target
    order.last_action_note = note
    if action == "close":
        from datetime import datetime, timezone

        order.closed_at = datetime.now(timezone.utc)
        if order.assignee_id is not None:
            notify(
                db,
                [order.assignee_id],
                f"派单已闭环：{order.title}",
                content=note or "共因处置完成",
                link="/dispatch",
                category="dispatch",
                channels=("in_app",),
            )
    elif action == "reopen":
        order.closed_at = None
    db.flush()
    return order


def reassign(
    db: Session, scope: DataScope, order_id: int, assignee_id: int, note: str | None
) -> DispatchOrder | None:
    """改派处理人，并通知新处理人。"""
    order = get_order(db, scope, order_id)
    if order is None:
        return None
    order.assignee_id = assignee_id
    order.assignee_name = _user_name(db, assignee_id)
    order.last_action_note = note
    db.flush()
    if assignee_id is not None:
        notify(
            db,
            [assignee_id],
            f"派单改派：{order.title}",
            content=note or "该派单已转派给您",
            link="/dispatch",
            category="dispatch",
            channels=("in_app",),
        )
    return order


def dispatch_stats(db: Session, scope: DataScope) -> dict:
    """按状态/级别统计（受数据范围约束）。"""
    from collections import Counter

    rows = db.scalars(_base_stmt(scope)).all()
    by_status: Counter = Counter()
    by_level: Counter = Counter()
    for o in rows:
        by_status[o.status] += 1
        by_level[o.level or "未分级"] += 1
    return {
        "total": len(rows),
        "by_status": dict(by_status),
        "by_level": dict(by_level),
    }
