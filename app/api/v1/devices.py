"""设备管理路由（对应需求 §2.7）。

三类设备（人机定位 / 大机防侵限 / 列车接近）共用统一接口：
- 列表/详情/更新/删除通过 ``device_type`` 参数在三类 ORM 模型间派发。
- 全部接入数据隔离（VIA_PROJECT：经 project.dept_id 过滤）。
- 权限：device:list / device:add / device:edit / device:delete。
  （device:command 属实时监控下行，不在此处实现。）
"""

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope, apply_data_scope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.core.scoring import device_health_level, device_health_score
from app.model.device import (
    AntiIntrusionDevice,
    LocateDevice,
    TrainApproachDevice,
)
from app.model.project import Project
from app.model.system import User
from app.schema.device import (
    DeviceCreate,
    DeviceOut,
    DevicePage,
    DeviceUpdate,
    validate_device_type,
)

router = APIRouter(tags=["设备管理"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "devices", "status": "skeleton"}


_DEVICE_MODELS = {
    "locate": LocateDevice,
    "anti_intrusion": AntiIntrusionDevice,
    "train_approach": TrainApproachDevice,
}


def _candidate_models(device_type: str | None):
    if device_type:
        validate_device_type(device_type)
        return [_DEVICE_MODELS[device_type]]
    return list(_DEVICE_MODELS.values())


def _find_device(db: Session, scope: DataScope, device_id: int, device_type: str | None):
    for m in _candidate_models(device_type):
        stmt = select(m).where(m.id == device_id, m.is_deleted.is_(False))
        stmt = apply_data_scope(stmt, m, scope)
        obj = db.scalars(stmt).first()
        if obj is not None:
            return obj
    return None


@router.get(
    "",
    response_model=ApiResponse[DevicePage],
    summary="设备列表",
    dependencies=[Depends(require_permissions("device:list"))],
)
def list_devices(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    device_type: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> ApiResponse:
    """分页查询设备；device_type 为空时跨三类合并后排序分页。"""
    models = _candidate_models(device_type)
    rows: list = []
    for m in models:
        stmt = select(m).where(m.is_deleted.is_(False))
        if keyword:
            kw = f"%{keyword}%"
            stmt = stmt.where(or_(m.name.ilike(kw), m.device_no.ilike(kw)))
        stmt = apply_data_scope(stmt, m, scope)
        rows.extend(db.scalars(stmt).all())
    # 跨表合并后按 id 倒序分页（主数据量级小，内存分页可接受）
    rows.sort(key=lambda x: x.id, reverse=True)
    total = len(rows)
    page_rows = rows[(page - 1) * size : (page - 1) * size + size]
    return ApiResponse.success(
        DevicePage(
            items=[DeviceOut.model_validate(r) for r in page_rows],
            total=total,
            page=page,
            size=size,
        ),
        message="查询成功",
    )


_TYPE_LABELS = {
    "locate": "人机定位",
    "anti_intrusion": "大机防侵限",
    "train_approach": "列车接近",
}

_EXPORT_COLUMNS = [
    ("id", "ID", 8, 10),
    ("type_label", "设备大类", 14, 22),
    ("name", "设备名称", 22, 34),
    ("device_no", "设备编号", 18, 30),
    ("sn", "SN码", 18, 28),
    ("project_name", "归属项目", 20, 34),
    ("status", "状态", 10, 14),
    ("created_at", "创建时间", 20, 28),
]


def _model_type_key(m) -> str:
    return {v: k for k, v in _DEVICE_MODELS.items()}[m]


@router.get(
    "/export",
    summary="导出设备台账（Excel/PDF）",
    dependencies=[Depends(require_permissions("device:list"))],
)
def export_devices(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    fmt: str = Query("excel", description="导出格式：excel | pdf"),
    device_type: str | None = None,
    keyword: str | None = None,
) -> StreamingResponse:
    """按筛选条件导出设备台账（跨三类合并，受数据范围约束），与告警/隐患导出对称。"""
    from app.service.report_common import build_simple_excel, build_simple_pdf

    models = _candidate_models(device_type)
    rows: list[dict] = []
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for m in models:
        tkey = _model_type_key(m)
        tlabel = _TYPE_LABELS[tkey]
        stmt = select(m).where(m.is_deleted.is_(False))
        if keyword:
            kw = f"%{keyword}%"
            stmt = stmt.where(or_(m.name.ilike(kw), m.device_no.ilike(kw)))
        stmt = apply_data_scope(stmt, m, scope)
        for obj in db.scalars(stmt).all():
            by_type[tlabel] = by_type.get(tlabel, 0) + 1
            by_status[obj.status] = by_status.get(obj.status, 0) + 1
            created = obj.created_at
            if created is not None and created.tzinfo is not None:
                created = created.astimezone().replace(tzinfo=None)
            rows.append(
                {
                    "id": obj.id,
                    "type_label": tlabel,
                    "name": obj.name,
                    "device_no": obj.device_no,
                    "sn": obj.sn or "",
                    "project_name": obj.project.name if obj.project is not None else "",
                    "status": obj.status,
                    "created_at": created.strftime("%Y-%m-%d %H:%M") if created else "",
                }
            )
    rows.sort(key=lambda x: x["id"], reverse=True)

    filters = []
    if device_type:
        filters.append(f"设备大类={_TYPE_LABELS.get(device_type, device_type)}")
    if keyword:
        filters.append(f"关键词={keyword}")
    meta = {
        "title": "涉铁工程设备台账",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filters_desc": "；".join(filters) or "全部",
    }
    summary_blocks = [
        ("按设备大类", sorted(by_type.items())),
        ("按状态", sorted(by_status.items())),
    ]

    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    if fmt == "pdf":
        content = build_simple_pdf(_EXPORT_COLUMNS, rows, meta, summary_blocks)
        media_type = "application/pdf"
        filename = f"device_report_{tag}.pdf"
    else:
        content = build_simple_excel(_EXPORT_COLUMNS, rows, meta, summary_blocks)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"device_report_{tag}.xlsx"
    disposition = f"attachment; filename={filename}; filename*=UTF-8''{quote(filename)}"
    return StreamingResponse(
        iter([content]),
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


@router.get(
    "/health",
    summary="设备健康/运维统计（P3·⑫）",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("device:list"))],
)
def device_health(
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    device_type: str | None = None,
    project_id: int | None = None,
    hours: int = Query(24, ge=1, le=720, description="统计窗口(小时)"),
) -> ApiResponse:
    """按设备聚合健康指标：最近上报/在线判定/窗口内上报量与告警数。

    在线定义与实时看板同源（settings.online_threshold_seconds）；
    健康分 = 在线(60) + 上报活跃(20，窗口有上报) + 无告警(20，窗口零告警)。
    """
    from datetime import timedelta
    from datetime import timezone as _tz

    from sqlalchemy import func

    from app.config import settings
    from app.model.alarm import Alarm
    from app.model.realtime import DeviceLocation

    now_utc = datetime.now(_tz.utc)
    since = now_utc - timedelta(hours=hours)
    threshold = settings.online_threshold_seconds

    # 数据范围内的设备台账（跨三类）
    devices: list[dict] = []
    device_nos: list[str] = []
    for m in _candidate_models(device_type):
        tkey = _model_type_key(m)
        stmt = select(m).where(m.is_deleted.is_(False))
        if project_id is not None:
            stmt = stmt.where(m.project_id == project_id)
        stmt = apply_data_scope(stmt, m, scope)
        for obj in db.scalars(stmt).all():
            devices.append(
                {
                    "id": obj.id,
                    "device_type": tkey,
                    "type_label": _TYPE_LABELS[tkey],
                    "name": obj.name,
                    "device_no": obj.device_no,
                    "project_id": obj.project_id,
                    "project_name": obj.project.name if obj.project is not None else None,
                    "status": obj.status,
                }
            )
            device_nos.append(obj.device_no)

    if not device_nos:
        return ApiResponse.success(
            data={
                "window_hours": hours,
                "threshold_seconds": threshold,
                "total": 0,
                "online": 0,
                "offline": 0,
                "items": [],
            }
        )

    # 窗口内上报量 + 最近上报时间（单查聚合）
    loc_rows = db.execute(
        select(
            DeviceLocation.device_no,
            func.count(DeviceLocation.id),
            func.max(DeviceLocation.report_time),
        )
        .where(
            DeviceLocation.device_no.in_(device_nos),
            DeviceLocation.report_time >= since,
        )
        .group_by(DeviceLocation.device_no)
    ).all()
    report_stats = {r[0]: (r[1], r[2]) for r in loc_rows}
    # 最近上报（不限窗口，用于在线判定兜底）
    last_rows = db.execute(
        select(DeviceLocation.device_no, func.max(DeviceLocation.report_time))
        .where(DeviceLocation.device_no.in_(device_nos))
        .group_by(DeviceLocation.device_no)
    ).all()
    last_seen = {r[0]: r[1] for r in last_rows}

    # 窗口内告警，按设备 + 告警级别分组（用于按严重度施加惩罚）
    alarm_rows = db.execute(
        select(Alarm.device_no, Alarm.alarm_level, func.count(Alarm.id))
        .where(Alarm.device_no.in_(device_nos), Alarm.alarm_time >= since)
        .group_by(Alarm.device_no, Alarm.alarm_level)
    ).all()
    alarm_sev_stats: dict[str, dict[str, int]] = {}
    for no, lvl, cnt in alarm_rows:
        alarm_sev_stats.setdefault(no, {}).setdefault(lvl or "提示", cnt)

    items: list[dict] = []
    online_n = 0
    for d in devices:
        no = d["device_no"]
        rpt_count, _ = report_stats.get(no, (0, None))
        last = last_seen.get(no)
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=_tz.utc)
        age = (now_utc - last).total_seconds() if last is not None else None
        online = age is not None and age <= threshold
        # 在线状态细分：fresh=新鲜 / stale=陈旧 / offline=离线或无上报
        if age is None:
            state = "offline"
        elif age <= threshold:
            state = "fresh"
        elif age <= 2 * threshold:
            state = "stale"
        else:
            state = "offline"
        sev = alarm_sev_stats.get(no, {})
        alarms = sum(sev.values())
        score = device_health_score(
            online_state=state, reported=rpt_count > 0, alarm_severity_counts=sev
        )
        level = device_health_level(score)
        if online:
            online_n += 1
        items.append(
            {
                **d,
                "online": online,
                "online_state": state,
                "last_report_time": (
                    last.astimezone().replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
                    if last is not None
                    else None
                ),
                "age_seconds": int(age) if age is not None else None,
                "report_count": rpt_count,
                "alarm_count": alarms,
                "health_score": score,
                "health_level": level,
            }
        )
    # 健康分升序（最差在前，运维视角优先关注）
    items.sort(key=lambda x: (x["health_score"], -(x["alarm_count"])))

    return ApiResponse.success(
        data={
            "window_hours": hours,
            "threshold_seconds": threshold,
            "total": len(items),
            "online": online_n,
            "offline": len(items) - online_n,
            "items": items,
        }
    )


@router.get(
    "/{device_id}",
    response_model=ApiResponse[DeviceOut],
    summary="设备详情",
    dependencies=[Depends(require_permissions("device:list"))],
)
def get_device(
    device_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    device_type: str | None = None,
) -> ApiResponse:
    """返回单个设备；不在数据范围内返回 404。"""
    obj = _find_device(db, scope, device_id, device_type)
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在或无权访问")
    return ApiResponse.success(DeviceOut.model_validate(obj), message="获取成功")


@router.post(
    "",
    response_model=ApiResponse[DeviceOut],
    summary="新建设备",
    dependencies=[Depends(require_permissions("device:add"))],
)
def create_device(
    req: DeviceCreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
) -> ApiResponse:
    """按 device_type 派发到对应模型；写入 created_by 与归属项目。"""
    validate_device_type(req.device_type)
    if (
        db.scalar(
            select(Project.id).where(Project.id == req.project_id, Project.is_deleted.is_(False))
        )
        is None
    ):
        raise BusinessError("归属项目不存在", code=400)
    m = _DEVICE_MODELS[req.device_type]
    cols = {c.name for c in m.__table__.columns}
    data = {k: v for k, v in req.model_dump(exclude={"device_type"}).items() if k in cols}
    if "device_type" in cols:
        data["device_type"] = req.device_type
    data["created_by"] = current.id
    obj = m(**data)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return ApiResponse.success(DeviceOut.model_validate(obj), message="设备创建成功")


@router.put(
    "/{device_id}",
    response_model=ApiResponse[DeviceOut],
    summary="更新设备",
    dependencies=[Depends(require_permissions("device:edit"))],
)
def update_device(
    device_id: int,
    req: DeviceUpdate,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    device_type: str | None = None,
) -> ApiResponse:
    """更新设备；device_type 用于定位正确模型。"""
    obj = _find_device(db, scope, device_id, device_type)
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在或无权访问")
    cols = {c.name for c in obj.__table__.columns}
    for field, value in req.model_dump(exclude_unset=True).items():
        if field in cols:
            setattr(obj, field, value)
    db.commit()
    db.refresh(obj)
    return ApiResponse.success(DeviceOut.model_validate(obj), message="设备更新成功")


@router.delete(
    "/{device_id}",
    response_model=ApiResponse,
    summary="删除设备",
    dependencies=[Depends(require_permissions("device:delete"))],
)
def delete_device(
    device_id: int,
    db: Session = Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    device_type: str | None = None,
) -> ApiResponse:
    """软删设备（is_deleted=True）。"""
    obj = _find_device(db, scope, device_id, device_type)
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在或无权访问")
    obj.is_deleted = True
    db.commit()
    return ApiResponse.success(message="设备已删除")
