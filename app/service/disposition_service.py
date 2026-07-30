"""告警处置记录服务（处置效果闭环）。

负责处置记录的写入、查询与统计：

- ``create_disposition``：在告警处置时记录「谁 / 按哪预案 / 用哪些知识库链接 / 结果 / 动作」，
  并据结果填充 ``resolved_at``（闭环时长统计用）；
- ``list_by_alarm`` / ``list_dispositions``：按告警或按多条件（项目/处置人/结果/时间窗）分页查询；
- ``disposition_stats``：聚合闭环率、平均闭环时长、按处置人/项目/结果分布，
  供后续「处置效能」大屏与报表复用。

所有查询经 ``apply_data_scope`` 数据隔离；服务层只 ``flush``，不 ``commit``（由端点统一提交）。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import DISPOSITION_RESOLVED
from app.core.data_scope import DataScope, apply_data_scope
from app.model.alarm import Alarm
from app.model.disposition import AlarmDisposition


def _parse_knowledge_refs(raw: Any) -> list[dict]:
    """knowledge_refs 库内存为 JSON 字符串，对外统一解析为列表。"""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        return [dict(x) for x in raw]
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [dict(x) for x in parsed]
        except (ValueError, TypeError):
            pass
    return []


def to_disposition_out(d: AlarmDisposition) -> dict[str, Any]:
    """序列化为对外字典。"""
    return {
        "id": d.id,
        "alarm_id": d.alarm_id,
        "project_id": d.project_id,
        "handler_id": d.created_by,
        "playbook_id": d.playbook_id,
        "knowledge_refs": _parse_knowledge_refs(d.knowledge_refs),
        "outcome": d.outcome,
        "action_taken": d.action_taken,
        "note": d.note,
        "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def create_disposition(
    db: Session,
    scope: DataScope,
    *,
    alarm_id: int,
    user_id: int,
    outcome: str | None = None,
    playbook_id: int | None = None,
    knowledge_refs: list[dict] | None = None,
    action_taken: str | None = None,
    note: str | None = None,
) -> AlarmDisposition | None:
    """为某告警创建一条处置记录。

    校验告警在当前用户数据范围内；``outcome=已解决`` 时填充 ``resolved_at``。
    ``user_id`` 为实际处置人（取自当前登录用户，而非数据范围）。
    返回新建记录，告警不存在或无权限返回 None。
    """
    stmt = select(Alarm).where(Alarm.id == alarm_id)
    stmt = apply_data_scope(stmt, Alarm, scope)
    alarm = db.scalar(stmt)
    if alarm is None:
        return None

    resolved_at = datetime.now(timezone.utc) if outcome == DISPOSITION_RESOLVED else None
    refs_json = json.dumps(knowledge_refs, ensure_ascii=False) if knowledge_refs else None
    rec = AlarmDisposition(
        alarm_id=alarm_id,
        project_id=alarm.project_id,
        created_by=user_id,
        playbook_id=playbook_id,
        knowledge_refs=refs_json,
        outcome=outcome,
        action_taken=action_taken,
        note=note,
        resolved_at=resolved_at,
    )
    db.add(rec)
    db.flush()
    return rec


def list_by_alarm(db: Session, alarm_id: int) -> list[AlarmDisposition]:
    """返回某告警的全部处置记录（逻辑未删），时间倒序。"""
    stmt = (
        select(AlarmDisposition)
        .where(
            AlarmDisposition.alarm_id == alarm_id,
            AlarmDisposition.is_deleted.is_(False),
        )
        .order_by(AlarmDisposition.created_at.desc())
    )
    return list(db.scalars(stmt).all())


def list_dispositions(
    db: Session,
    scope: DataScope,
    *,
    project_id: int | None = None,
    handler_id: int | None = None,
    outcome: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[int, list[AlarmDisposition]]:
    """按多条件分页查询处置记录，施加部门数据隔离。返回 (total, items)。"""
    page = max(1, page)
    size = max(1, size)
    base = select(AlarmDisposition).where(AlarmDisposition.is_deleted.is_(False))
    base = apply_data_scope(base, AlarmDisposition, scope)
    if project_id is not None:
        base = base.where(AlarmDisposition.project_id == project_id)
    if handler_id is not None:
        base = base.where(AlarmDisposition.created_by == handler_id)
    if outcome is not None:
        base = base.where(AlarmDisposition.outcome == outcome)
    if start is not None:
        base = base.where(AlarmDisposition.created_at >= start)
    if end is not None:
        base = base.where(AlarmDisposition.created_at <= end)

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(AlarmDisposition.created_at.desc(), AlarmDisposition.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return total, list(rows)


def disposition_stats(
    db: Session,
    scope: DataScope,
    *,
    project_id: int | None = None,
    days: int = 30,
) -> dict[str, Any]:
    """聚合处置效能：闭环率、平均闭环时长、按处置人/项目/结果分布。

    ``days`` 限定统计窗口（按记录创建时间）。时长口径：``resolved_at - 告警 alarm_time``
    （缺失时回退到 ``resolved_at - 记录创建时间``）。
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    stmt = (
        select(AlarmDisposition, Alarm.alarm_time)
        .join(Alarm, AlarmDisposition.alarm_id == Alarm.id, isouter=True)
        .where(
            AlarmDisposition.is_deleted.is_(False),
            AlarmDisposition.created_at >= since,
        )
    )
    stmt = apply_data_scope(stmt, AlarmDisposition, scope)
    if project_id is not None:
        stmt = stmt.where(AlarmDisposition.project_id == project_id)

    rows = db.execute(stmt).all()

    total = len(rows)
    resolved = [r for r in rows if r[0].outcome == DISPOSITION_RESOLVED]
    closure_rate = (len(resolved) / total) if total else None

    durations: list[float] = []
    for disp, alarm_time in rows:
        if disp.resolved_at is None:
            continue
        base = alarm_time or disp.created_at
        if base is None:
            continue
        hours = (disp.resolved_at - base).total_seconds() / 3600.0
        if hours < 0:
            hours = 0.0
        durations.append(hours)
    avg_duration_hours = sum(durations) / len(durations) if durations else None

    by_outcome: dict[str, int] = {}
    for disp, _ in rows:
        key = disp.outcome or "未填写"
        by_outcome[key] = by_outcome.get(key, 0) + 1

    by_handler: dict[int, dict[str, Any]] = {}
    for disp, _ in rows:
        hid = disp.created_by or 0
        agg = by_handler.setdefault(hid, {"handler_id": hid, "total": 0, "resolved": 0})
        agg["total"] += 1
        if disp.outcome == DISPOSITION_RESOLVED:
            agg["resolved"] += 1
    for agg in by_handler.values():
        agg["closure_rate"] = agg["resolved"] / agg["total"] if agg["total"] else None

    by_project: dict[int, dict[str, Any]] = {}
    for disp, _ in rows:
        pid = disp.project_id or 0
        agg = by_project.setdefault(pid, {"project_id": pid, "total": 0, "resolved": 0})
        agg["total"] += 1
        if disp.outcome == DISPOSITION_RESOLVED:
            agg["resolved"] += 1
    for agg in by_project.values():
        agg["closure_rate"] = agg["resolved"] / agg["total"] if agg["total"] else None

    return {
        "period_days": days,
        "total": total,
        "resolved": len(resolved),
        "closure_rate": closure_rate,
        "avg_duration_hours": avg_duration_hours,
        "by_outcome": by_outcome,
        "by_handler": list(by_handler.values()),
        "by_project": list(by_project.values()),
    }
