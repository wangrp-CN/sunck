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
from app.core.constants import (
    DEVICE_TYPE_ANTI_INTRUSION,
    DEVICE_TYPE_LOCATE,
    DEVICE_TYPE_TRAIN_APPROACH,
)
from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.core.rule_engine_v2 import is_plan_active_now
from app.model.device import AntiIntrusionDevice, LocateDevice, TrainApproachDevice
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
    FenceRuleIn,
    FenceRuleOut,
    MachineBindingIn,
    MachineBindingOut,
    PersonBindingIn,
    PersonBindingOut,
    WorkPlanCreate,
    WorkPlanOut,
    WorkPlanPage,
    WorkPlanRule,
    WorkPlanUpdate,
)

router = APIRouter(tags=["作业计划"])

#: 列表可排序字段白名单（前端表头排序 → ORDER BY）
_SORTABLE = {
    "created_at": WorkPlan.created_at,
    "plan_start": WorkPlan.plan_start,
    "plan_end": WorkPlan.plan_end,
    "name": WorkPlan.name,
    "status": WorkPlan.status,
    "is_start": WorkPlan.is_start,
}

#: 设备编号解析：三类设备表统一按 device_no 反查（类型 + 名称）
_DEVICE_MODELS = (
    (DEVICE_TYPE_LOCATE, LocateDevice),
    (DEVICE_TYPE_ANTI_INTRUSION, AntiIntrusionDevice),
    (DEVICE_TYPE_TRAIN_APPROACH, TrainApproachDevice),
)


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


def _resolve_devices(db: Session, device_nos: set[str]) -> dict[str, tuple[str, str]]:
    """device_no → (device_type, name)；跨三类设备表反查，未命中的编号不出现在结果中。"""
    device_nos = {n for n in device_nos if n}
    if not device_nos:
        return {}
    resolved: dict[str, tuple[str, str]] = {}
    for dtype, model in _DEVICE_MODELS:
        pending = device_nos - resolved.keys()
        if not pending:
            break
        rows = db.execute(
            select(model.device_no, model.name).where(
                model.device_no.in_(pending), model.is_deleted.is_(False)
            )
        ).all()
        for no, name in rows:
            resolved[no] = (dtype, name)
    return resolved


def _normalize_bindings(
    req: WorkPlanCreate | WorkPlanUpdate,
) -> tuple[list[PersonBindingIn], list[MachineBindingIn], list[FenceRuleIn]]:
    """把「结构化绑定」与「旧版 *_ids 简写」统一成结构化形式。

    结构化字段（person_bindings / machine_bindings / fence_rules）给出时优先；
    否则回退到 person_ids / machine_ids / fence_ids，保证既有调用方不受影响。
    """
    persons = (
        req.person_bindings
        if req.person_bindings is not None
        else [PersonBindingIn(person_id=i) for i in (req.person_ids or [])]
    )
    machines = (
        req.machine_bindings
        if req.machine_bindings is not None
        else [MachineBindingIn(machine_id=i) for i in (req.machine_ids or [])]
    )
    fences = (
        req.fence_rules
        if req.fence_rules is not None
        else [FenceRuleIn(fence_id=i) for i in (req.fence_ids or [])]
    )
    return list(persons), list(machines), list(fences)


def _derive_rule(fence_rules: list[FenceRuleIn]) -> WorkPlanRule | None:
    """由首条围栏规则派生「计划级聚合规则」，供规则引擎 v2 判定使用。

    原型的触发条件（进入/离开）均属围栏类判定，统一映射为 ``fence_intrusion``；
    monitor_target / time_range / dwell_time 原样透传（引擎对自由文本目标回落不受限）。
    """
    if not fence_rules:
        return None
    first = fence_rules[0]
    return WorkPlanRule(
        monitor_target=first.monitor_target,
        trigger_conditions=["fence_intrusion"] if first.trigger_condition else None,
        time_range=first.time_range,
        dwell_time=first.dwell_time,
    )


def _sync_bindings(
    db: Session,
    plan_id: int,
    person_bindings: list[PersonBindingIn],
    machine_bindings: list[MachineBindingIn],
    device_bindings: list,
    fence_rules: list[FenceRuleIn],
) -> None:
    """先清空再写入关联表（全量重链）。

    人员/大机行内引用的设备编号会自动并入 ``work_plan_device``（去重），
    使规则引擎 v2 的「计划设备覆盖」与向导所选设备保持一致。
    """
    db.execute(delete(WorkPlanPerson).where(WorkPlanPerson.plan_id == plan_id))
    db.execute(delete(WorkPlanMachine).where(WorkPlanMachine.plan_id == plan_id))
    db.execute(delete(WorkPlanDevice).where(WorkPlanDevice.plan_id == plan_id))
    db.execute(delete(WorkPlanFence).where(WorkPlanFence.plan_id == plan_id))

    if person_bindings:
        db.bulk_insert_mappings(
            WorkPlanPerson,
            [
                {"plan_id": plan_id, "person_id": b.person_id, "device_no": b.device_no}
                for b in person_bindings
            ],
        )
    if machine_bindings:
        db.bulk_insert_mappings(
            WorkPlanMachine,
            [
                {
                    "plan_id": plan_id,
                    "machine_id": b.machine_id,
                    "guard_person_id": b.guard_person_id,
                    "driver_person_id": b.driver_person_id,
                    "arm_device_no": b.arm_device_no,
                    "body_device_no": b.body_device_no,
                    "voice_device_no": b.voice_device_no,
                }
                for b in machine_bindings
            ],
        )

    # 设备覆盖 = 显式 device_bindings ∪ 人员/大机行内引用的设备
    pairs: dict[str, str] = {}
    for d in device_bindings or []:
        pairs[d.device_no] = d.device_type
    implicit = {b.device_no for b in person_bindings if b.device_no}
    for b in machine_bindings:
        implicit.update({b.arm_device_no, b.body_device_no, b.voice_device_no})
    implicit = {n for n in implicit if n and n not in pairs}
    for no, (dtype, _name) in _resolve_devices(db, implicit).items():
        pairs[no] = dtype
    if pairs:
        db.bulk_insert_mappings(
            WorkPlanDevice,
            [
                {"plan_id": plan_id, "device_type": dtype, "device_no": no}
                for no, dtype in pairs.items()
            ],
        )

    if fence_rules:
        db.bulk_insert_mappings(
            WorkPlanFence,
            [
                {
                    "plan_id": plan_id,
                    "fence_id": f.fence_id,
                    "monitor_target": f.monitor_target,
                    "trigger_condition": f.trigger_condition,
                    "time_range": f.time_range,
                    "dwell_time": f.dwell_time,
                }
                for f in fence_rules
            ],
        )


def _to_out(db: Session, plan: WorkPlan) -> WorkPlanOut:
    project_name = None
    if plan.project_id is not None:
        proj = db.get(Project, plan.project_id)
        project_name = proj.name if proj else None

    person_rows = db.scalars(select(WorkPlanPerson).where(WorkPlanPerson.plan_id == plan.id)).all()
    machine_rows = db.scalars(
        select(WorkPlanMachine).where(WorkPlanMachine.plan_id == plan.id)
    ).all()
    fence_rows = db.scalars(select(WorkPlanFence).where(WorkPlanFence.plan_id == plan.id)).all()
    dev_rows = db.scalars(select(WorkPlanDevice).where(WorkPlanDevice.plan_id == plan.id)).all()

    pids = [r.person_id for r in person_rows]
    mids = [r.machine_id for r in machine_rows]
    fids = [r.fence_id for r in fence_rows]
    # 大机行内引用的防护/驾驶人员也要能回显名字
    ref_pids = {r.guard_person_id for r in machine_rows} | {
        r.driver_person_id for r in machine_rows
    }
    all_pids = set(pids) | {i for i in ref_pids if i}

    person_map: dict[int, tuple[str, str]] = {}
    if all_pids:
        for pid, pname, pno in db.execute(
            select(Person.id, Person.name, Person.person_no).where(
                Person.id.in_(all_pids), Person.is_deleted.is_(False)
            )
        ).all():
            person_map[pid] = (pname, pno)

    machine_map: dict[int, tuple[str, str | None]] = {}
    if mids:
        for mid, mno, mtype in db.execute(
            select(Machine.id, Machine.machine_no, Machine.machine_type).where(
                Machine.id.in_(mids), Machine.is_deleted.is_(False)
            )
        ).all():
            machine_map[mid] = (mno, mtype)

    fence_map: dict[int, str] = {}
    if fids:
        for fid, fname in db.execute(
            select(ElectronicFence.id, ElectronicFence.name).where(
                ElectronicFence.id.in_(fids), ElectronicFence.is_deleted.is_(False)
            )
        ).all():
            fence_map[fid] = fname

    # 设备名称回显（人员定位设备 + 大机三类车载设备 + 显式绑定设备）
    device_nos: set[str] = {r.device_no for r in person_rows if r.device_no}
    for r in machine_rows:
        device_nos.update({r.arm_device_no, r.body_device_no, r.voice_device_no})
    device_nos.update({d.device_no for d in dev_rows})
    device_map = _resolve_devices(db, {n for n in device_nos if n})

    def _dev_name(no: str | None) -> str | None:
        if not no:
            return None
        hit = device_map.get(no)
        return hit[1] if hit else None

    persons = [(pid, person_map[pid][0]) for pid in pids if pid in person_map]
    machines = [
        (mid, f"{machine_map[mid][0]}({machine_map[mid][1] or '大机'})")
        for mid in mids
        if mid in machine_map
    ]
    fences = [(fid, fence_map[fid]) for fid in fids if fid in fence_map]

    person_bindings = [
        PersonBindingOut(
            person_id=r.person_id,
            person_name=person_map.get(r.person_id, (None, None))[0],
            person_no=person_map.get(r.person_id, (None, None))[1],
            device_no=r.device_no,
            device_name=_dev_name(r.device_no),
        )
        for r in person_rows
    ]
    machine_bindings = [
        MachineBindingOut(
            machine_id=r.machine_id,
            machine_no=machine_map.get(r.machine_id, (None, None))[0],
            machine_type=machine_map.get(r.machine_id, (None, None))[1],
            guard_person_id=r.guard_person_id,
            guard_person_name=person_map.get(r.guard_person_id or -1, (None, None))[0],
            driver_person_id=r.driver_person_id,
            driver_person_name=person_map.get(r.driver_person_id or -1, (None, None))[0],
            arm_device_no=r.arm_device_no,
            arm_device_name=_dev_name(r.arm_device_no),
            body_device_no=r.body_device_no,
            body_device_name=_dev_name(r.body_device_no),
            voice_device_no=r.voice_device_no,
            voice_device_name=_dev_name(r.voice_device_no),
        )
        for r in machine_rows
    ]
    fence_rules = [
        FenceRuleOut(
            fence_id=r.fence_id,
            fence_name=fence_map.get(r.fence_id),
            monitor_target=r.monitor_target,
            trigger_condition=r.trigger_condition,
            time_range=r.time_range,
            dwell_time=r.dwell_time,
        )
        for r in fence_rows
    ]

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
        is_template=plan.is_template,
        active=is_plan_active_now(plan),
        rule=_parse_rule(plan.rule_json),
        created_by=plan.created_by,
        created_at=plan.created_at.isoformat() if plan.created_at else None,
        persons=[BoundPerson(id=r[0], name=r[1]) for r in persons],
        machines=[BoundMachine(id=r[0], name=r[1]) for r in machines],
        devices=[
            BoundDevice(
                device_type=d.device_type, device_no=d.device_no, name=_dev_name(d.device_no)
            )
            for d in dev_rows
        ],
        fences=[BoundFence(id=r[0], name=r[1]) for r in fences],
        person_bindings=person_bindings,
        machine_bindings=machine_bindings,
        fence_rules=fence_rules,
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
    person_bindings, machine_bindings, fence_rules = _normalize_bindings(req)
    # 计划级聚合规则：显式 rule 优先，否则由首条围栏规则派生（供规则引擎 v2）
    rule = req.rule or _derive_rule(fence_rules)
    plan = WorkPlan(
        project_id=req.project_id,
        name=req.name,
        is_start=req.is_start,
        description=req.description,
        plan_time=req.plan_time,
        plan_start=req.plan_start,
        plan_end=req.plan_end,
        status=req.status,
        rule_json=json.dumps(rule.model_dump(), ensure_ascii=False) if rule else None,
        created_by=current.id,
    )
    db.add(plan)
    db.flush()
    # 跨项目绑定校验：绑定的人员/机械/围栏必须归属本计划的项目
    _validate_bindings_project(
        db,
        req.project_id,
        [b.person_id for b in person_bindings],
        [b.machine_id for b in machine_bindings],
        [f.fence_id for f in fence_rules],
    )
    _sync_bindings(db, plan.id, person_bindings, machine_bindings, req.device_bindings, fence_rules)
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
    is_start: bool | None = None,
    is_template: bool = False,
    sort_by: str = "created_at",
    order: str = "desc",
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    """分页列表；施加部门数据隔离与软删过滤。

    - is_template=False（默认）仅普通计划；=True 仅模板（模板库视图）。
    - 默认按创建时间倒序（原型要求）；sort_by 走白名单，非法值回落 created_at。
    """
    stmt = select(WorkPlan).where(
        WorkPlan.is_deleted.is_(False), WorkPlan.is_template.is_(is_template)
    )
    stmt = apply_data_scope(stmt, WorkPlan, scope)
    if project_id is not None:
        stmt = stmt.where(WorkPlan.project_id == project_id)
    if status is not None:
        stmt = stmt.where(WorkPlan.status == status)
    if is_start is not None:
        stmt = stmt.where(WorkPlan.is_start.is_(is_start))
    if keyword:
        stmt = stmt.where(WorkPlan.name.ilike(f"%{keyword}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))

    col = _SORTABLE.get(sort_by, WorkPlan.created_at)
    direction = col.asc() if str(order).lower() == "asc" else col.desc()
    # id 作为稳定次序，避免同一时间戳分页错乱
    tiebreak = WorkPlan.id.asc() if str(order).lower() == "asc" else WorkPlan.id.desc()
    rows = db.scalars(
        stmt.order_by(direction, tiebreak).limit(size).offset((page - 1) * size)
    ).all()
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
        WorkPlan.is_template.is_(False),
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
    binding_keys = {
        "person_ids",
        "machine_ids",
        "fence_ids",
        "device_bindings",
        "person_bindings",
        "machine_bindings",
        "fence_rules",
    }
    touches_bindings = bool(binding_keys & data.keys())
    person_bindings, machine_bindings, fence_rules = _normalize_bindings(req)

    if "rule" in data:
        plan.rule_json = json.dumps(req.rule.model_dump(), ensure_ascii=False) if req.rule else None
    elif "fence_rules" in data:
        # 未显式给出计划级规则时，由首条围栏规则派生（与新建一致）
        derived = _derive_rule(fence_rules)
        plan.rule_json = json.dumps(derived.model_dump(), ensure_ascii=False) if derived else None

    if touches_bindings:
        # 跨项目绑定校验：以请求指定 project_id 为准，未指定则用计划原 project_id
        target_project = req.project_id if req.project_id is not None else plan.project_id
        _validate_bindings_project(
            db,
            target_project,
            [b.person_id for b in person_bindings],
            [b.machine_id for b in machine_bindings],
            [f.fence_id for f in fence_rules],
        )
        _sync_bindings(
            db,
            plan.id,
            person_bindings,
            machine_bindings,
            req.device_bindings or [],
            fence_rules,
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


def _copy_plan(
    db: Session,
    src: WorkPlan,
    *,
    name: str,
    is_template: bool,
    user_id: int | None,
) -> WorkPlan:
    """深拷贝计划：基本信息 + 规则 + 四类绑定；执行态字段清零（草稿/未激活）。"""
    new_plan = WorkPlan(
        project_id=src.project_id,
        name=name,
        is_start=False,
        description=src.description,
        plan_time=src.plan_time,
        plan_start=src.plan_start,
        plan_end=src.plan_end,
        status="草稿",
        is_template=is_template,
        rule_json=src.rule_json,
        created_by=user_id,
    )
    db.add(new_plan)
    db.flush()
    # 深拷贝四类绑定（含绑定明细列：人员配对设备/大机六要素/围栏规则）
    prows = db.scalars(select(WorkPlanPerson).where(WorkPlanPerson.plan_id == src.id)).all()
    mrows = db.scalars(select(WorkPlanMachine).where(WorkPlanMachine.plan_id == src.id)).all()
    frows = db.scalars(select(WorkPlanFence).where(WorkPlanFence.plan_id == src.id)).all()
    devs = db.scalars(select(WorkPlanDevice).where(WorkPlanDevice.plan_id == src.id)).all()
    if prows:
        db.bulk_insert_mappings(
            WorkPlanPerson,
            [
                {"plan_id": new_plan.id, "person_id": r.person_id, "device_no": r.device_no}
                for r in prows
            ],
        )
    if mrows:
        db.bulk_insert_mappings(
            WorkPlanMachine,
            [
                {
                    "plan_id": new_plan.id,
                    "machine_id": r.machine_id,
                    "guard_person_id": r.guard_person_id,
                    "driver_person_id": r.driver_person_id,
                    "arm_device_no": r.arm_device_no,
                    "body_device_no": r.body_device_no,
                    "voice_device_no": r.voice_device_no,
                }
                for r in mrows
            ],
        )
    if frows:
        db.bulk_insert_mappings(
            WorkPlanFence,
            [
                {
                    "plan_id": new_plan.id,
                    "fence_id": r.fence_id,
                    "monitor_target": r.monitor_target,
                    "trigger_condition": r.trigger_condition,
                    "time_range": r.time_range,
                    "dwell_time": r.dwell_time,
                }
                for r in frows
            ],
        )
    if devs:
        db.bulk_insert_mappings(
            WorkPlanDevice,
            [
                {"plan_id": new_plan.id, "device_type": d.device_type, "device_no": d.device_no}
                for d in devs
            ],
        )
    return new_plan


@router.post(
    "/{job_id}/clone",
    summary="克隆作业计划（从计划或模板生成草稿副本）",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("job:add"))],
)
def clone_job(
    job_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    """深拷贝生成新草稿：基本信息/规则/绑定全量复制，执行态清零。

    源可以是普通计划或模板（模板套用 = 克隆模板）。
    """
    src = _get_owned_plan(db, job_id, scope)
    new_plan = _copy_plan(db, src, name=f"{src.name}(副本)", is_template=False, user_id=current.id)
    db.commit()
    db.refresh(new_plan)
    return ApiResponse.success(data=_to_out(db, new_plan), message="作业计划已克隆")


@router.post(
    "/{job_id}/save-as-template",
    summary="存为模板（模板仅作克隆蓝本，不参与执行）",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("job:add"))],
)
def save_job_as_template(
    job_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    """把现有计划沉淀为模板；源计划本身不受影响。"""
    src = _get_owned_plan(db, job_id, scope)
    if src.is_template:
        raise BusinessError("该计划已是模板，无需重复保存", code=400)
    new_plan = _copy_plan(db, src, name=f"{src.name}(模板)", is_template=True, user_id=current.id)
    db.commit()
    db.refresh(new_plan)
    return ApiResponse.success(data=_to_out(db, new_plan), message="已存为模板")


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
