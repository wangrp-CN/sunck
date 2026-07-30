"""告警策略服务（🅱 M4 告警收敛/抑制/升级）。

三类治理能力（均以 ``AlarmPolicy`` 配置驱动）：

- **收敛**：``resolve_policy`` 命中的策略若配置 ``suppress_window_seconds``，
  由 ``alarm_service.create_alarm`` 用其覆盖全局风暴合并窗口；
- **抑制（静默免打扰）**：``in_silence`` 判定当前（北京时间）落在静默时段内时，
  告警仍正常落库，但 ``create_alarm`` 跳过通知（不丢数据，只降打扰）；
- **升级**：``run_escalations`` 由周期任务驱动，对「待处理 + 超时 + 未升级过」的
  告警按策略升级级别并按渠道重新通知（含当班人姓名），``Alarm.escalated_at``
  留痕保证幂等。

匹配优先级：项目+类型 > 项目通配 > 全局+类型 > 全局通配。
遵循 SOP：服务内不提交事务，由调用端点 / job 统一 commit。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import LOCAL_TZ
from app.core.data_scope import DataScope, apply_data_scope
from app.core.exceptions import BusinessError
from app.model.alarm import Alarm
from app.model.alarm_policy import AlarmPolicy
from app.model.project import Project
from app.schema.alarm_policy import AlarmPolicyOut, AlarmPolicyUpdate

logger = logging.getLogger("rail_monitor.alarm_policy")

#: 单轮升级扫描的告警上限（防止历史积压导致单轮过大）
_ESCALATION_BATCH_LIMIT = 500

#: 合法升级级别（与 Alarm.alarm_level 取值一致）
_VALID_LEVELS = ("提示", "警告", "严重")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def _base_stmt(scope: DataScope):
    stmt = select(AlarmPolicy).where(AlarmPolicy.is_deleted.is_(False))
    return apply_data_scope(stmt, AlarmPolicy, scope)


def _validate(db: Session, project_id: int | None, escalate_to_level: str | None) -> None:
    if project_id is not None:
        proj = db.scalar(
            select(Project.id).where(Project.id == project_id, Project.is_deleted.is_(False))
        )
        if proj is None:
            raise BusinessError(f"归属项目不存在或已删除（project_id={project_id}）", code=400)
    if escalate_to_level is not None and escalate_to_level not in _VALID_LEVELS:
        raise BusinessError(f"升级目标级别须为 {'/'.join(_VALID_LEVELS)}", code=400)


def create_policy(db: Session, scope: DataScope, creator_id: int | None, data) -> AlarmPolicy:
    _validate(db, data.project_id, data.escalate_to_level)
    obj = AlarmPolicy(
        name=data.name,
        project_id=data.project_id,
        alarm_type=data.alarm_type or None,
        enabled=data.enabled,
        suppress_window_seconds=data.suppress_window_seconds,
        silence_start=data.silence_start,
        silence_end=data.silence_end,
        escalate_after_minutes=data.escalate_after_minutes,
        escalate_to_level=data.escalate_to_level,
        escalate_channels=data.escalate_channels or "in_app",
        note=data.note,
        created_by=creator_id,
    )
    db.add(obj)
    db.flush()
    return obj


def list_policies(
    db: Session,
    scope: DataScope,
    *,
    project_id: int | None = None,
    alarm_type: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    page = max(1, page)
    size = max(1, min(size, 200))
    stmt = _base_stmt(scope)
    if project_id is not None:
        stmt = stmt.where(AlarmPolicy.project_id == project_id)
    if alarm_type is not None:
        stmt = stmt.where(AlarmPolicy.alarm_type == alarm_type)
    if enabled is not None:
        stmt = stmt.where(AlarmPolicy.enabled.is_(enabled))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AlarmPolicy.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return {"total": total, "items": rows, "page": page, "size": size}


def get_policy(db: Session, scope: DataScope, pid: int) -> AlarmPolicy | None:
    return db.scalars(_base_stmt(scope).where(AlarmPolicy.id == pid)).first()


def update_policy(
    db: Session, scope: DataScope, pid: int, data: AlarmPolicyUpdate
) -> AlarmPolicy | None:
    obj = get_policy(db, scope, pid)
    if obj is None:
        return None
    _validate(db, data.project_id, data.escalate_to_level)
    for f in ("name", "project_id", "alarm_type", "enabled", "escalate_to_level", "note"):
        v = getattr(data, f, None)
        if v is not None:
            setattr(obj, f, v)
    # 数值/时段字段约定：0 或空串 = 清除（回退默认/关闭），None = 不变
    if data.suppress_window_seconds is not None:
        obj.suppress_window_seconds = data.suppress_window_seconds or None
    if data.escalate_after_minutes is not None:
        obj.escalate_after_minutes = data.escalate_after_minutes or None
    if data.silence_start is not None:
        obj.silence_start = data.silence_start or None
    if data.silence_end is not None:
        obj.silence_end = data.silence_end or None
    if data.escalate_channels is not None:
        obj.escalate_channels = data.escalate_channels or "in_app"
    db.flush()
    return obj


def delete_policy(db: Session, scope: DataScope, pid: int) -> bool:
    obj = get_policy(db, scope, pid)
    if obj is None:
        return False
    obj.is_deleted = True
    db.flush()
    return True


def to_out(db: Session, obj: AlarmPolicy) -> AlarmPolicyOut:
    out = AlarmPolicyOut.model_validate(obj)
    if obj.project_id is not None:
        p = db.get(Project, obj.project_id)
        out.project_name = p.name if p else None
    return out


# ---------------------------------------------------------------------------
# 策略引擎：匹配 / 收敛窗口 / 静默判定
# ---------------------------------------------------------------------------


def resolve_policy(
    db: Session, project_id: int | None, alarm_type: str | None
) -> AlarmPolicy | None:
    """解析对 (project_id, alarm_type) 生效的策略。

    优先级：项目+类型 > 项目通配 > 全局+类型 > 全局通配；同级取 id 最大（最新）。
    未命中返回 None（走全局默认行为）。
    """
    conds = [AlarmPolicy.is_deleted.is_(False), AlarmPolicy.enabled.is_(True)]
    if project_id is not None:
        conds.append(AlarmPolicy.project_id.in_([project_id]) | AlarmPolicy.project_id.is_(None))
    else:
        conds.append(AlarmPolicy.project_id.is_(None))
    rows = db.scalars(select(AlarmPolicy).where(*conds)).all()

    def _specificity(p: AlarmPolicy) -> tuple[int, int, int]:
        proj_match = 1 if (project_id is not None and p.project_id == project_id) else 0
        type_match = 1 if (alarm_type is not None and p.alarm_type == alarm_type) else 0
        return (proj_match, type_match, p.id)

    candidates = [
        p
        for p in rows
        if p.alarm_type is None or (alarm_type is not None and p.alarm_type == alarm_type)
    ]
    if not candidates:
        return None
    return max(candidates, key=_specificity)


def effective_suppress_window(policy: AlarmPolicy | None) -> int | None:
    """返回策略覆盖的风暴合并窗口秒数；无覆盖返回 None（用全局默认）。"""
    if policy is None or not policy.suppress_window_seconds:
        return None
    return max(1, int(policy.suppress_window_seconds))


def in_silence(policy: AlarmPolicy | None, now: datetime | None = None) -> bool:
    """判定当前（北京时间）是否落在策略静默时段内（支持跨天，如 22:00-06:00）。"""
    if policy is None or not policy.silence_start or not policy.silence_end:
        return False
    now = now or datetime.now(timezone.utc)
    hhmm = now.astimezone(LOCAL_TZ).strftime("%H:%M")
    start, end = policy.silence_start, policy.silence_end
    if start <= end:
        return start <= hhmm < end
    # 跨天窗口：22:00-06:00 → hhmm>=22:00 或 hhmm<06:00
    return hhmm >= start or hhmm < end


# ---------------------------------------------------------------------------
# 升级引擎：超时未处理 → 升级级别 + 重新通知（周期任务驱动）
# ---------------------------------------------------------------------------


def run_escalations(db: Session, now: datetime | None = None) -> dict:
    """扫描待处理且未升级过的告警，按命中策略执行超时升级。

    - 仅处理 ``handle_status="待处理"`` 且 ``escalated_at IS NULL`` 的告警；
    - 逐条 ``resolve_policy``（与创建时同一优先级语义），命中且配置了
      ``escalate_after_minutes`` 且已超时 → 升级：
      - ``alarm_level`` 提升到 ``escalate_to_level``（已同级则只留痕+通知）；
      - ``escalated_at = now`` 幂等留痕（下一轮不再重复升级）；
      - 按 ``escalate_channels`` 重新通知项目范围用户（含当班人姓名提示）。
    - 不提交事务（由调用 job/端点 commit）。返回 {scanned, escalated, alarm_ids}。
    """
    from app.core.notify import notify_for_project
    from app.service.duty_service import resolve_on_duty

    now = now or datetime.now(timezone.utc)
    rows = db.scalars(
        select(Alarm)
        .where(
            Alarm.handle_status == "待处理",
            Alarm.escalated_at.is_(None),
            Alarm.alarm_time.is_not(None),
        )
        .order_by(Alarm.alarm_time.asc())
        .limit(_ESCALATION_BATCH_LIMIT)
    ).all()

    escalated_ids: list[int] = []
    for alarm in rows:
        policy = resolve_policy(db, alarm.project_id, alarm.alarm_type)
        if policy is None or not policy.escalate_after_minutes:
            continue
        deadline = alarm.alarm_time + timedelta(minutes=int(policy.escalate_after_minutes))
        if now < deadline:
            continue
        old_level = alarm.alarm_level or "未分级"
        target = policy.escalate_to_level or "严重"
        if alarm.alarm_level != target:
            alarm.alarm_level = target
        alarm.escalated_at = now
        escalated_ids.append(alarm.id)

        channels = tuple(
            c.strip() for c in (policy.escalate_channels or "in_app").split(",") if c.strip()
        ) or ("in_app",)
        _, duty_name = resolve_on_duty(db, alarm.project_id, now=now)
        dev = alarm.device_name or alarm.device_no or "设备"
        overdue_min = int((now - alarm.alarm_time).total_seconds() // 60)
        title = f"告警升级：{target}级 / {dev}（超时未处理）"
        content = (
            f"告警 #{alarm.id} 已超时 {overdue_min} 分钟未处理，"
            f"级别 {old_level} → {target}（策略「{policy.name}」）。"
            f"当班人：{duty_name or '无人值班'}。{alarm.alarm_info or ''}"
        )
        try:
            notify_for_project(
                db,
                alarm.project_id,
                title,
                content=content,
                link="/alarms",
                category="alarm",
                channels=channels,
            )
        except Exception:  # noqa: BLE001
            logger.warning("告警升级通知失败（不影响升级留痕）alarm_id=%s", alarm.id)

    db.flush()
    return {"scanned": len(rows), "escalated": len(escalated_ids), "alarm_ids": escalated_ids}
