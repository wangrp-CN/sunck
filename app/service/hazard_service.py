"""隐患治理闭环服务层：CRUD、状态机流转、统计与逾期判定。

状态机（HAZARD_TRANSITIONS）：
  待整改 --start_rectify--> 整改中 --submit_rectify--> 待复核
  待复核 --verify_pass--> 已销号(终态) | --verify_reject--> 整改中
  待整改 --reject--> 已驳回 --reopen--> 待整改

所有查询均经 apply_data_scope 施加部门数据隔离；端点统一提交（service 不 commit）。
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.clock import now_local
from app.core.constants import (
    ALARM_LEVEL_TO_HAZARD_LEVEL,
    HAZARD_TERMINAL_STATUSES,
    HAZARD_TRANSITIONS,
)
from app.core.data_scope import DataScope, apply_data_scope
from app.core.exceptions import BusinessError
from app.model.alarm import Alarm
from app.model.hazard import Hazard
from app.schema.hazard import HazardOut
from app.service.alarm_service import alarm_type_label

logger = logging.getLogger("rail_monitor.hazard")


def _is_overdue(h: Hazard, now_utc: datetime) -> bool:
    """是否超期：未到终态且已设整改期限且期限早于当前时间。"""
    if h.status in HAZARD_TERMINAL_STATUSES or h.due_at is None:
        return False
    return h.due_at.astimezone(timezone.utc) < now_utc


def to_hazard_out(h: Hazard, now_utc: datetime | None = None) -> HazardOut:
    """把 ORM 行转为对外输出（补充 project_name/assignee_name/is_overdue）。"""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    project_name = h.project.name if h.project is not None else None
    assignee_name = h.assignee.name if h.assignee is not None else None
    return HazardOut(
        id=h.id,
        project_id=h.project_id,
        project_name=project_name,
        title=h.title,
        level=h.level,
        category=h.category,
        description=h.description,
        location_desc=h.location_desc,
        lng=h.lng,
        lat=h.lat,
        discovered_by_name=h.discovered_by_name,
        discovered_at=h.discovered_at,
        source=h.source,
        source_alarm_id=h.source_alarm_id,
        status=h.status,
        assignee_id=h.assignee_id,
        assignee_name=assignee_name,
        due_at=h.due_at,
        rectify_note=h.rectify_note,
        rectify_at=h.rectify_at,
        verify_by_name=h.verify_by_name,
        verify_at=h.verify_at,
        verify_note=h.verify_note,
        closed_at=h.closed_at,
        created_by=h.created_by,
        created_at=h.created_at,
        updated_at=h.updated_at,
        is_overdue=_is_overdue(h, now_utc),
    )


def create_hazard(db: Session, data: dict, user_id: int | None) -> HazardOut:
    """创建隐患；发现时间缺省填当前时间。

    创建成功后按隐患所属项目的数据范围收敛推送站内信（与告警通知同源），
    确保「监测→治理」闭环的治理侧通知同样遵守部门数据隔离、不越权广播。
    """
    if not data.get("title"):
        raise BusinessError("隐患标题不能为空", code=400)
    if data.get("discovered_at") is None:
        data["discovered_at"] = now_local()
    h = Hazard(**data)
    h.created_by = user_id
    db.add(h)
    db.flush()
    db.refresh(h)
    # 治理侧通知（数据范围收敛，失败不影响隐患落库）
    try:
        from app.core.notify import notify_hazard_created

        notify_hazard_created(db, h)
    except Exception:  # noqa: BLE001
        logger.warning("隐患站内信通知失败（不影响隐患落库）")
    return to_hazard_out(h)


def convert_alarm_to_hazard(
    db: Session,
    alarm_id: int,
    operator_id: int | None,
    overrides: dict | None = None,
) -> HazardOut | None:
    """告警一键转隐患：把一条告警转换为隐患治理工单，形成监测→治理闭环。

    转换后回填 `alarm.hazard_id` 与 `hazard.source_alarm_id` 双向关联。
    若该告警已转过隐患，按业务错误返回（调用方转 HTTP 200 + body code 400）。
    """
    overrides = overrides or {}
    alarm = db.get(Alarm, alarm_id)
    if alarm is None:
        return None
    if alarm.hazard_id is not None:
        raise BusinessError("该告警已转为隐患，不可重复转换", code=400)

    title = overrides.get("title") or "告警转隐患：{}/{}".format(
        alarm_type_label(alarm.alarm_type),
        alarm.device_name or alarm.device_no or "未知设备",
    )
    level = overrides.get("level") or ALARM_LEVEL_TO_HAZARD_LEVEL.get(alarm.alarm_level, "一般")
    raw_due = overrides.get("due_at")
    if isinstance(raw_due, str):
        try:
            due_at = datetime.fromisoformat(raw_due)
        except ValueError:
            due_at = now_local() + timedelta(days=7)
    else:
        due_at = raw_due or (now_local() + timedelta(days=7))
    data = {
        "project_id": overrides.get("project_id", alarm.project_id),
        "title": title,
        "level": level,
        "category": overrides.get("category") or "施工安全",
        "description": overrides.get("description") or alarm.alarm_info,
        "location_desc": overrides.get("location_desc") or alarm.fence_name,
        "lng": overrides.get("lng"),
        "lat": overrides.get("lat"),
        "discovered_by_name": overrides.get("discovered_by_name") or "系统(告警转隐患)",
        "discovered_at": now_local(),
        "source": "系统",
        "assignee_id": overrides.get("assignee_id"),
        "due_at": due_at,
        "source_alarm_id": alarm.id,
    }
    out = create_hazard(db, data, operator_id)
    # 回填告警侧关联（create_hazard 已 flush，hazard.id 可用）
    hazard_id = out.id
    alarm.hazard_id = hazard_id
    db.flush()
    return out


def _base_stmt(scope: DataScope):
    stmt = select(Hazard).where(Hazard.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, Hazard, scope)
    return stmt


def list_hazards(
    db: Session,
    scope: DataScope,
    project_id: int | None = None,
    level: str | None = None,
    status: str | None = None,
    keyword: str | None = None,
    overdue_only: bool = False,
    page: int = 1,
    size: int = 20,
) -> tuple[int, list[HazardOut]]:
    """分页列出隐患（带数据隔离与筛选）。"""
    now_utc = datetime.now(timezone.utc)
    stmt = _base_stmt(scope)
    if project_id is not None:
        stmt = stmt.where(Hazard.project_id == project_id)
    if level:
        stmt = stmt.where(Hazard.level == level)
    if status:
        stmt = stmt.where(Hazard.status == status)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                Hazard.title.ilike(like),
                Hazard.description.ilike(like),
                Hazard.location_desc.ilike(like),
            )
        )
    # 最新的隐患排在前面（便于管理与测试断言）
    stmt = stmt.order_by(Hazard.id.desc())
    # 先取全部命中（分页前），用于 overdue 过滤与统计可控
    rows = list(db.scalars(stmt).all())
    outs = [to_hazard_out(h, now_utc) for h in rows]
    if overdue_only:
        outs = [o for o in outs if o.is_overdue]

    total = len(outs)
    start = max(0, (page - 1) * size)
    end = start + size
    return total, outs[start:end]


def get_hazard(db: Session, hazard_id: int, scope: DataScope) -> HazardOut | None:
    stmt = _base_stmt(scope).where(Hazard.id == hazard_id)
    h = db.scalar(stmt)
    return to_hazard_out(h) if h else None


def update_hazard(db: Session, hazard_id: int, data: dict, scope: DataScope) -> HazardOut | None:
    """局部更新隐患（仅数据范围内可见的记录）。"""
    stmt = _base_stmt(scope).where(Hazard.id == hazard_id)
    h = db.scalar(stmt)
    if h is None:
        return None
    for k, v in data.items():
        if v is not None:
            setattr(h, k, v)
    db.flush()
    return to_hazard_out(h)


def delete_hazard(db: Session, hazard_id: int, scope: DataScope) -> bool:
    """软删除隐患（仅数据范围内可见的记录）。"""
    stmt = _base_stmt(scope).where(Hazard.id == hazard_id)
    h = db.scalar(stmt)
    if h is None:
        return False
    h.is_deleted = True
    db.flush()
    return True


def transition_hazard(
    db: Session,
    hazard_id: int,
    action: str,
    note: str | None,
    scope: DataScope,
    operator_name: str | None = None,
) -> HazardOut:
    """执行状态机流转；非法动作/状态抛 BusinessError。"""
    rule = HAZARD_TRANSITIONS.get(action)
    if rule is None:
        raise BusinessError(f"非法的流转动作：{action}", code=400)
    from_state, to_state = rule
    stmt = _base_stmt(scope).where(Hazard.id == hazard_id)
    h = db.scalar(stmt)
    if h is None:
        raise BusinessError("隐患不存在或无权限访问", code=404)
    if h.status != from_state:
        raise BusinessError(
            f"当前状态「{h.status}」不允许执行「{action}」（需处于「{from_state}」）",
            code=400,
        )

    now = now_local()
    if action == "start_rectify":
        pass
    elif action == "submit_rectify":
        if not note:
            raise BusinessError("提交整改需填写整改说明", code=400)
        h.rectify_note = note
        h.rectify_at = now
    elif action == "verify_pass":
        if not note:
            raise BusinessError("复核通过需填写复核意见", code=400)
        h.verify_by_name = operator_name
        h.verify_at = now
        h.verify_note = note
        h.closed_at = now
    elif action == "verify_reject":
        if not note:
            raise BusinessError("复核驳回需填写复核意见", code=400)
        h.verify_by_name = operator_name
        h.verify_at = now
        h.verify_note = note
    elif action == "reject":
        if not note:
            raise BusinessError("驳回隐患需填写原因", code=400)
        h.verify_note = note
    elif action == "reopen":
        h.closed_at = None

    h.status = to_state
    db.flush()
    return to_hazard_out(h)


def hazard_stats(db: Session, scope: DataScope) -> dict:
    """统计：总数、按状态、按等级、超期数（均受数据隔离约束）。"""
    now_utc = datetime.now(timezone.utc)
    stmt = _base_stmt(scope)
    rows = list(db.scalars(stmt).all())

    by_status: dict[str, int] = {}
    by_level: dict[str, int] = {}
    overdue = 0
    for h in rows:
        by_status[h.status] = by_status.get(h.status, 0) + 1
        by_level[h.level] = by_level.get(h.level, 0) + 1
        if _is_overdue(h, now_utc):
            overdue += 1
    return {
        "total": len(rows),
        "by_status": by_status,
        "by_level": by_level,
        "overdue": overdue,
    }
