"""巡检/打卡服务层：任务 CRUD、状态机流转、打卡与异常转隐患、统计。

状态机（INSPECTION_TRANSITIONS）：
  待巡检 --start--> 巡检中 --finish--> 已完成；任一非终态 --cancel--> 已取消。

数据范围经 project 关联(VIA_PROJECT)：查询施加 apply_data_scope，但打卡明细按
task 聚合（任务可见即可见其全部打卡）。异常打卡可一键转隐患（hazard_id 溯源）。
"""

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.clock import now_local
from app.core.data_scope import DataScope, apply_data_scope
from app.core.exceptions import BusinessError
from app.model.hazard import Hazard
from app.model.inspection import InspectionRecord, InspectionTask
from app.model.person import Person
from app.model.project import Project
from app.schema.inspection import InspectionRecordOut, InspectionTaskOut

# 状态机：动作 → (源状态, 目标状态)
INSPECTION_TRANSITIONS = {
    "start": ("待巡检", "巡检中"),
    "finish": ("巡检中", "已完成"),
    "cancel": ("巡检中", "已取消"),
}
INSPECTION_TERMINAL = {"已完成", "已取消"}


def _counts(db: Session, task_id: int) -> tuple[int, int]:
    rows = db.execute(
        select(
            func.count(InspectionRecord.id),
            func.sum(case((InspectionRecord.result == "异常", 1), else_=0)),
        ).where(InspectionRecord.task_id == task_id)
    ).first()
    total = rows[0] or 0
    abnormal = int(rows[1] or 0)
    return total, abnormal


def to_task_out(db: Session, t: InspectionTask) -> InspectionTaskOut:
    project_name = None
    if t.project_id is not None:
        proj = db.get(Project, t.project_id)
        project_name = proj.name if proj else None
    assignee_name = None
    if t.assignee_id is not None:
        p = db.get(Person, t.assignee_id)
        assignee_name = p.name if p else None
    total, abnormal = _counts(db, t.id)
    records = db.scalars(
        select(InspectionRecord)
        .where(InspectionRecord.task_id == t.id)
        .order_by(InspectionRecord.id.asc())
    ).all()
    return InspectionTaskOut(
        id=t.id,
        project_id=t.project_id,
        project_name=project_name,
        name=t.name,
        content=t.content,
        assignee_id=t.assignee_id,
        assignee_name=assignee_name,
        start_time=t.start_time,
        end_time=t.end_time,
        status=t.status,
        required_checkins=t.required_checkins,
        checkin_count=total,
        abnormal_count=abnormal,
        created_by=t.created_by,
        created_at=t.created_at,
        records=[InspectionRecordOut.model_validate(r) for r in records],
    )


def _base_stmt(scope: DataScope):
    return apply_data_scope(
        select(InspectionTask).where(InspectionTask.is_deleted.is_(False)), InspectionTask, scope
    )


def list_tasks(
    db: Session,
    scope: DataScope,
    project_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[int, list[InspectionTask]]:
    stmt = _base_stmt(scope)
    if project_id is not None:
        stmt = stmt.where(InspectionTask.project_id == project_id)
    if status:
        stmt = stmt.where(InspectionTask.status == status)
    if keyword:
        stmt = stmt.where(InspectionTask.name.ilike(f"%{keyword}%"))
    stmt = stmt.order_by(InspectionTask.id.desc())
    rows = db.scalars(stmt).all()
    total = len(rows)
    start = max(0, (page - 1) * size)
    return total, rows[start : start + size]


def get_task(db: Session, task_id: int, scope: DataScope) -> InspectionTask | None:
    return db.scalar(_base_stmt(scope).where(InspectionTask.id == task_id))


def create_task(db: Session, data: dict, user_id: int | None) -> InspectionTask:
    if not data.get("name"):
        raise BusinessError("巡检任务名称不能为空", code=400)
    t = InspectionTask(**data)
    t.created_by = user_id
    db.add(t)
    db.flush()
    return t


def update_task(db: Session, task_id: int, data: dict, scope: DataScope) -> InspectionTask | None:
    t = get_task(db, task_id, scope)
    if t is None:
        return None
    for k, v in data.items():
        if v is not None:
            setattr(t, k, v)
    db.flush()
    return t


def transition_task(db: Session, task_id: int, action: str, scope: DataScope) -> InspectionTask:
    rule = INSPECTION_TRANSITIONS.get(action)
    if rule is None:
        raise BusinessError(f"非法的流转动作：{action}", code=400)
    from_state, to_state = rule
    t = get_task(db, task_id, scope)
    if t is None:
        raise BusinessError("巡检任务不存在或无权访问", code=404)
    if t.status != from_state:
        raise BusinessError(
            f"当前状态「{t.status}」不允许执行「{action}」（需处于「{from_state}」）",
            code=400,
        )
    t.status = to_state
    db.flush()
    return t


def delete_task(db: Session, task_id: int, scope: DataScope) -> bool:
    t = get_task(db, task_id, scope)
    if t is None:
        return False
    t.is_deleted = True
    db.flush()
    return True


def checkin(
    db: Session,
    task_id: int,
    data: dict,
    scope: DataScope,
    operator_name: str | None = None,
) -> InspectionRecord:
    """提交一次打卡；异常结果自动置任务为巡检中（若仍待巡检）。"""
    t = get_task(db, task_id, scope)
    if t is None:
        raise BusinessError("巡检任务不存在或无权访问", code=404)
    rec = InspectionRecord(
        task_id=task_id,
        project_id=t.project_id,
        checkin_by_name=data.get("checkin_by_name") or operator_name,
        checkin_at=now_local(),
        lng=data.get("lng"),
        lat=data.get("lat"),
        result=data.get("result", "正常"),
        note=data.get("note"),
    )
    db.add(rec)
    if t.status == "待巡检":
        t.status = "巡检中"
    db.flush()
    return rec


def convert_checkin_to_hazard(
    db: Session, record_id: int, scope: DataScope, operator_id: int | None
) -> int:
    """把一条异常打卡转隐患（创建 Hazard 并回填 hazard_id）。

    与告警转隐患同源，确保「巡检异常 → 治理」闭环。返回新建隐患 id。
    """
    rec = db.get(InspectionRecord, record_id)
    if rec is None:
        raise BusinessError("打卡记录不存在", code=404)
    if rec.result != "异常":
        raise BusinessError("仅异常打卡可转隐患", code=400)
    if rec.hazard_id is not None:
        raise BusinessError("该打卡已转过隐患", code=400)
    task = db.get(InspectionTask, rec.task_id)
    hazard = Hazard(
        project_id=rec.project_id,
        title=f"巡检异常转隐患：{task.name if task else rec.id}",
        level="一般",
        category="巡检异常",
        description=rec.note,
        lng=rec.lng,
        lat=rec.lat,
        discovered_by_name=rec.checkin_by_name or "巡检员",
        discovered_at=now_local(),
        source="巡检",
        status="待整改",
    )
    hazard.created_by = operator_id
    db.add(hazard)
    db.flush()
    rec.hazard_id = hazard.id
    db.flush()
    return hazard.id


def inspection_stats(db: Session, scope: DataScope) -> dict:
    """统计：任务总数/按状态、打卡总数、异常数。"""
    rows = db.scalars(_base_stmt(scope)).all()
    by_status: dict[str, int] = {}
    checkin_total = 0
    abnormal = 0
    for t in rows:
        by_status[t.status] = by_status.get(t.status, 0) + 1
        total, ab = _counts(db, t.id)
        checkin_total += total
        abnormal += ab
    return {
        "task_total": len(rows),
        "by_status": by_status,
        "checkin_total": checkin_total,
        "abnormal_total": abnormal,
    }
