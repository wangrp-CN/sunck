"""作业计划管理路由（阶段3）：三步式（基本信息 → 绑资源 → 绑围栏+规则）。

- POST /        新建（写入基本信息 + 关联表）
- GET  /        列表（关键词/项目/状态过滤 + 部门数据隔离 + 软删过滤）
- GET  /{id}   详情（展开人员/机械/设备/围栏绑定 + 规则）
- PUT  /{id}   更新（基本信息 + 重链关联表）
- DELETE /{id}  软删除
"""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.clock import now_local
from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.core.rule_engine_v2 import is_plan_active_now
from app.model.fence import ElectronicFence
from app.model.job import (
    WorkPlan,
    WorkPlanDevice,
    WorkPlanFence,
    WorkPlanMachine,
    WorkPlanPerson,
)
from app.model.person import Machine, Person
from app.model.project import Project
from app.model.system import User
from app.schema.job import (
    BoundDevice,
    BoundFence,
    BoundMachine,
    BoundPerson,
    WorkPlanCreate,
    WorkPlanOut,
    WorkPlanPage,
    WorkPlanRule,
    WorkPlanUpdate,
)

router = APIRouter(tags=["作业计划"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "jobs", "status": "ready"}


def _parse_rule(raw) -> WorkPlanRule | None:
    if not raw:
        return None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(raw, dict):
        return None
    try:
        return WorkPlanRule(**raw)
    except Exception:  # noqa: BLE001
        return None


def _validate_bindings_project(
    db: Session,
    project_id: int | None,
    person_ids: list[int],
    machine_ids: list[int],
    fence_ids: list[int],
) -> None:
    """校验绑定的人员/机械/围栏归属目标项目（跨项目绑定会被规则引擎误判为越权）。

    仅当 project_id 给定时校验；空列表跳过。违反则抛业务错误（含具体越界 id 列表）。
    """
    if project_id is None:
        return

    def _check(model, ids: list[int], label: str) -> None:
        if not ids:
            return
        rows = db.execute(
            select(model.id, model.project_id).where(model.id.in_(ids), model.is_deleted.is_(False))
        ).all()
        bad = [rid for rid, pid in rows if pid != project_id]
        if bad:
            raise BusinessError(
                f"以下{label}不属于本项目(project_id={project_id})：{bad}", code=400
            )

    _check(Person, person_ids, "人员")
    _check(Machine, machine_ids, "机械")
    _check(ElectronicFence, fence_ids, "围栏")


def _sync_bindings(
    db: Session,
    plan_id: int,
    person_ids: list[int],
    machine_ids: list[int],
    device_bindings: list,
    fence_ids: list[int],
) -> None:
    """先清空再写入关联表（全量重链）。"""
    db.execute(delete(WorkPlanPerson).where(WorkPlanPerson.plan_id == plan_id))
    db.execute(delete(WorkPlanMachine).where(WorkPlanMachine.plan_id == plan_id))
    db.execute(delete(WorkPlanDevice).where(WorkPlanDevice.plan_id == plan_id))
    db.execute(delete(WorkPlanFence).where(WorkPlanFence.plan_id == plan_id))
    if person_ids:
        db.bulk_insert_mappings(
            WorkPlanPerson, [{"plan_id": plan_id, "person_id": i} for i in person_ids]
        )
    if machine_ids:
        db.bulk_insert_mappings(
            WorkPlanMachine, [{"plan_id": plan_id, "machine_id": i} for i in machine_ids]
        )
    if device_bindings:
        db.bulk_insert_mappings(
            WorkPlanDevice,
            [
                {"plan_id": plan_id, "device_type": d.device_type, "device_no": d.device_no}
                for d in device_bindings
            ],
        )
    if fence_ids:
        db.bulk_insert_mappings(
            WorkPlanFence, [{"plan_id": plan_id, "fence_id": i} for i in fence_ids]
        )


def _to_out(db: Session, plan: WorkPlan) -> WorkPlanOut:
    project_name = None
    if plan.project_id is not None:
        proj = db.get(Project, plan.project_id)
        project_name = proj.name if proj else None

    pids = db.scalars(
        select(WorkPlanPerson.person_id).where(WorkPlanPerson.plan_id == plan.id)
    ).all()
    mids = db.scalars(
        select(WorkPlanMachine.machine_id).where(WorkPlanMachine.plan_id == plan.id)
    ).all()
    fids = db.scalars(select(WorkPlanFence.fence_id).where(WorkPlanFence.plan_id == plan.id)).all()
    dev_rows = db.scalars(select(WorkPlanDevice).where(WorkPlanDevice.plan_id == plan.id)).all()

    persons = (
        db.execute(
            select(Person.id, Person.name).where(Person.id.in_(pids), Person.is_deleted.is_(False))
        ).all()
        if pids
        else []
    )
    machines = (
        db.execute(
            select(Machine.id, Machine.name).where(
                Machine.id.in_(mids), Machine.is_deleted.is_(False)
            )
        ).all()
        if mids
        else []
    )
    fences = (
        db.execute(
            select(ElectronicFence.id, ElectronicFence.name).where(
                ElectronicFence.id.in_(fids), ElectronicFence.is_deleted.is_(False)
            )
        ).all()
        if fids
        else []
    )

    return WorkPlanOut(
        id=plan.id,
        project_id=plan.project_id,
        project_name=project_name,
        name=plan.name,
        is_start=plan.is_start,
        description=plan.description,
        plan_time=plan.plan_time,
        plan_start=plan.plan_start,
        plan_end=plan.plan_end,
        actual_start=plan.actual_start,
        actual_end=plan.actual_end,
        status=plan.status,
        active=is_plan_active_now(plan),
        rule=_parse_rule(plan.rule_json),
        created_by=plan.created_by,
        created_at=plan.created_at.isoformat() if plan.created_at else None,
        persons=[BoundPerson(id=r[0], name=r[1]) for r in persons],
        machines=[BoundMachine(id=r[0], name=r[1]) for r in machines],
        devices=[BoundDevice(device_type=d.device_type, device_no=d.device_no) for d in dev_rows],
        fences=[BoundFence(id=r[0], name=r[1]) for r in fences],
    )


@router.post(
    "",
    summary="新建作业计划",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("job:add"))],
)
def create_job(
    req: WorkPlanCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    """三步式新建：基本信息 + 关联资源 + 围栏/规则。"""
    plan = WorkPlan(
        project_id=req.project_id,
        name=req.name,
        is_start=req.is_start,
        description=req.description,
        plan_time=req.plan_time,
        plan_start=req.plan_start,
        plan_end=req.plan_end,
        status=req.status,
        rule_json=json.dumps(req.rule.model_dump(), ensure_ascii=False) if req.rule else None,
        created_by=current.id,
    )
    db.add(plan)
    db.flush()
    # 跨项目绑定校验：绑定的人员/机械/围栏必须归属本计划的项目
    _validate_bindings_project(db, req.project_id, req.person_ids, req.machine_ids, req.fence_ids)
    _sync_bindings(db, plan.id, req.person_ids, req.machine_ids, req.device_bindings, req.fence_ids)
    db.commit()
    db.refresh(plan)
    return ApiResponse.success(data=_to_out(db, plan), message="作业计划已创建")


@router.get(
    "",
    summary="作业计划列表",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("job:list"))],
)
def list_jobs(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    keyword: str | None = None,
    project_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    """分页列表；施加部门数据隔离与软删过滤。"""
    stmt = select(WorkPlan).where(WorkPlan.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, WorkPlan, scope)
    if project_id is not None:
        stmt = stmt.where(WorkPlan.project_id == project_id)
    if status is not None:
        stmt = stmt.where(WorkPlan.status == status)
    if keyword:
        stmt = stmt.where(WorkPlan.name.ilike(f"%{keyword}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(WorkPlan.id.desc()).limit(size).offset((page - 1) * size)).all()
    return ApiResponse.success(
        data=WorkPlanPage(total=total or 0, items=[_to_out(db, r) for r in rows])
    )


@router.get(
    "/active",
    summary="激活中的作业计划（规则引擎据此判定）",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("job:list"))],
)
def list_active_jobs(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = None,
) -> ApiResponse:
    """返回 is_start=True 且 status=执行中 的计划（含时间窗/设备覆盖，已施加部门隔离）。"""
    stmt = select(WorkPlan).where(
        WorkPlan.is_deleted.is_(False),
        WorkPlan.is_start.is_(True),
        WorkPlan.status == "执行中",
    )
    stmt = apply_data_scope(stmt, WorkPlan, scope)
    if project_id is not None:
        stmt = stmt.where(WorkPlan.project_id == project_id)
    rows = db.scalars(stmt.order_by(WorkPlan.id.desc())).all()
    return ApiResponse.success(data=[_to_out(db, r) for r in rows])


@router.get(
    "/by-fence/{fence_id}",
    summary="根据围栏查询关联的作业计划（地图围栏点击联动）",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("job:list"))],
)
def list_jobs_by_fence(
    fence_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """返回绑定了该围栏的作业计划（含完整详情展开）；施加部门数据隔离与软删过滤。

    用于地图围栏点击 → 关联作业计划详情弹层，让地图与业务 v2 真正打通。
    一个围栏可关联多个作业计划（如不同阶段/不同单位的监护计划）。
    """
    plan_ids = db.scalars(
        select(WorkPlanFence.plan_id).where(WorkPlanFence.fence_id == fence_id)
    ).all()
    if not plan_ids:
        return ApiResponse.success(data=[])
    stmt = select(WorkPlan).where(
        WorkPlan.id.in_(plan_ids),
        WorkPlan.is_deleted.is_(False),
    )
    stmt = apply_data_scope(stmt, WorkPlan, scope)
    rows = db.scalars(stmt.order_by(WorkPlan.id.desc())).all()
    return ApiResponse.success(data=[_to_out(db, r) for r in rows])


def _get_owned_plan(db: Session, job_id: int, scope: DataScope) -> WorkPlan:
    stmt = select(WorkPlan).where(WorkPlan.id == job_id, WorkPlan.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, WorkPlan, scope)
    plan = db.scalars(stmt).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="作业计划不存在或无权访问")
    return plan


@router.get(
    "/{job_id}",
    summary="作业计划详情",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("job:list"))],
)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """详情；越权（不在数据范围）返回 404。"""
    plan = _get_owned_plan(db, job_id, scope)
    return ApiResponse.success(data=_to_out(db, plan))


@router.put(
    "/{job_id}",
    summary="更新作业计划",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("job:edit"))],
)
def update_job(
    job_id: int,
    req: WorkPlanUpdate,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """更新基本信息并（在提供时）重链关联表。"""
    stmt = select(WorkPlan).where(WorkPlan.id == job_id, WorkPlan.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, WorkPlan, scope)
    plan = db.scalars(stmt).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="作业计划不存在或无权访问")

    data = req.model_dump(exclude_unset=True)
    for f in (
        "project_id",
        "name",
        "is_start",
        "description",
        "plan_time",
        "plan_start",
        "plan_end",
        "status",
    ):
        if f in data:
            setattr(plan, f, data[f])
    if "rule" in data:
        plan.rule_json = json.dumps(req.rule.model_dump(), ensure_ascii=False) if req.rule else None
    if "person_ids" in data:
        # 跨项目绑定校验：以请求指定 project_id 为准，未指定则用计划原 project_id
        target_project = req.project_id if req.project_id is not None else plan.project_id
        _validate_bindings_project(
            db, target_project, req.person_ids or [], req.machine_ids or [], req.fence_ids or []
        )
        _sync_bindings(
            db,
            plan.id,
            req.person_ids or [],
            req.machine_ids or [],
            req.device_bindings or [],
            req.fence_ids or [],
        )
    db.commit()
    db.refresh(plan)
    return ApiResponse.success(data=_to_out(db, plan), message="作业计划已更新")


@router.post(
    "/{job_id}/start",
    summary="启动作业计划（进入执行中，规则引擎开始判定）",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("job:edit"))],
)
def start_job(
    job_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """将计划置为激活：is_start=True，status=执行中，并回填实际开始时间。"""
    plan = _get_owned_plan(db, job_id, scope)
    plan.is_start = True
    plan.status = "执行中"
    if plan.actual_start is None:
        plan.actual_start = now_local()
    db.commit()
    db.refresh(plan)
    return ApiResponse.success(data=_to_out(db, plan), message="作业计划已启动")


@router.post(
    "/{job_id}/complete",
    summary="完成作业计划（停止规则判定）",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("job:edit"))],
)
def complete_job(
    job_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """将计划置为已完成：status=已完成，is_start=False，并回填实际结束时间。"""
    plan = _get_owned_plan(db, job_id, scope)
    plan.status = "已完成"
    plan.is_start = False
    plan.actual_end = now_local()
    db.commit()
    db.refresh(plan)
    return ApiResponse.success(data=_to_out(db, plan), message="作业计划已完成")


@router.delete(
    "/{job_id}",
    summary="删除作业计划",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("job:delete"))],
)
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """软删除；越权返回 404。"""
    stmt = select(WorkPlan).where(WorkPlan.id == job_id, WorkPlan.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, WorkPlan, scope)
    plan = db.scalars(stmt).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="作业计划不存在或无权访问")
    plan.is_deleted = True
    db.commit()
    return ApiResponse.success(message="作业计划已删除")
