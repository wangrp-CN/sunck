"""实时链路 API（阶段1）。

- GET  /locations  最新设备位置（地图打点），施加数据隔离
- GET  /devices   设备列表（含配置坐标），施加数据隔离
- POST /command   向设备下发指令（接口 2/4/6），需 device:command 权限

坐标统一对外转换：WGS-84（设备）→ GCJ-02（高德地图），内部规则判定仍用 WGS-84。
"""

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.cache import get_cached_json, set_cached_json
from app.core.constants import down_topic
from app.core.data_scope import DataScope
from app.core.database import get_db, get_read_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.exceptions import BusinessError
from app.core.geo import wgs84_to_gcj02
from app.core.responses import ApiResponse
from app.model.project import Project
from app.model.system import User
from app.mqtt import client as mqtt_client
from app.mqtt import protocol
from app.service.device_service import list_devices, resolve_device
from app.service.location_service import latest_locations, trajectory

router = APIRouter(tags=["实时链路"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "realtime", "status": "skeleton"}


class DeviceCommandRequest(BaseModel):
    device_type: str = Field(..., description="设备类型(locate/anti_intrusion/train_approach)")
    device_no: str = Field(..., description="设备编号")
    action: str = Field(..., description="指令动作(见 protocol._DOWNLINK_ACTIONS)")
    params: dict[str, Any] | None = Field(None, description="指令参数")


def _scope_project_ids(db: Session, scope: DataScope) -> set[int] | None:
    """返回当前用户可见的项目 ID 集合；is_all 返回 None。"""
    if scope.is_all or not scope.dept_ids:
        return None
    ids = db.scalars(select(Project.id).where(Project.dept_id.in_(scope.dept_ids))).all()
    return set(ids)


def _to_gcj(lng: float | None, lat: float | None) -> dict | None:
    if lng is None or lat is None:
        return None
    glng, glat = wgs84_to_gcj02(lng, lat)
    return {"lng": glng, "lat": glat}


@router.get(
    "/locations",
    summary="最新设备位置",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("device:list"))],
)
def get_locations(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_read_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = None,
    device_type: str | None = None,
) -> ApiResponse:
    """返回每个设备最新一条位置（地图实时打点）。"""
    _cached = get_cached_json(current_user.id, request.url.path, request.url.query)
    if _cached is not None:
        return ApiResponse(**_cached)

    rows = latest_locations(db, project_id=project_id, device_type=device_type)
    allowed = _scope_project_ids(db, scope)
    data = []
    for r in rows:
        if allowed is not None and r.project_id not in allowed:
            continue
        data.append(
            {
                "device_type": r.device_type,
                "device_no": r.device_no,
                "device_name": r.device_name,
                "project_id": r.project_id,
                "longitude": r.longitude,
                "latitude": r.latitude,
                "gcj02": _to_gcj(r.longitude, r.latitude),
                "accuracy": r.accuracy,
                "speed": r.speed,
                "status": r.status,
                "report_time": r.report_time.isoformat() if r.report_time else None,
            }
        )
    resp = ApiResponse.success(data={"total": len(data), "items": data})
    set_cached_json(current_user.id, request.url.path, request.url.query, resp.model_dump())
    return resp


@router.get(
    "/online-status",
    summary="设备在线状态看板",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("device:list"))],
)
def online_status(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_read_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = None,
    device_type: str | None = None,
) -> ApiResponse:
    """汇总设备实时在线状态（基于最近上报时间阈值判定）。

    在线定义：最近一次上报距当前不超过 `settings.online_threshold_seconds`（默认 300s）。
    坐标统一对外转换：WGS-84 → GCJ-02。施加部门数据隔离。
    """
    _cached = get_cached_json(current_user.id, request.url.path, request.url.query)
    if _cached is not None:
        return ApiResponse(**_cached)

    rows = latest_locations(db, project_id=project_id, device_type=device_type)
    allowed = _scope_project_ids(db, scope)
    threshold = settings.online_threshold_seconds
    now = datetime.now(timezone.utc)
    items: list[dict] = []
    by_type: dict[str, dict] = {}
    for r in rows:
        if allowed is not None and r.project_id not in allowed:
            continue
        last = r.report_time
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        age = (now - last).total_seconds() if last is not None else None
        online = age is not None and age <= threshold
        item = {
            "device_type": r.device_type,
            "device_no": r.device_no,
            "device_name": r.device_name,
            "project_id": r.project_id,
            "longitude": r.longitude,
            "latitude": r.latitude,
            "gcj02": _to_gcj(r.longitude, r.latitude),
            "status": r.status,
            "report_time": last.isoformat() if last else None,
            "online": online,
            "age_seconds": int(age) if age is not None else None,
        }
        items.append(item)
        bt = by_type.setdefault(r.device_type, {"total": 0, "online": 0, "offline": 0})
        bt["total"] += 1
        if online:
            bt["online"] += 1
        else:
            bt["offline"] += 1
    total = len(items)
    online_n = sum(1 for i in items if i["online"])
    resp = ApiResponse.success(
        data={
            "threshold_seconds": threshold,
            "total": total,
            "online": online_n,
            "offline": total - online_n,
            "by_type": by_type,
            "items": items,
        }
    )
    set_cached_json(current_user.id, request.url.path, request.url.query, resp.model_dump())
    return resp


@router.get(
    "/devices",
    summary="设备列表(地图)",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("device:list"))],
)
def get_devices(
    db: Session = Depends(get_read_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = None,
    device_type: str | None = None,
) -> ApiResponse:
    """汇总三类设备（含配置坐标），供地图初始渲染。"""
    rows = list_devices(db, project_id=project_id, device_type=device_type)
    allowed = _scope_project_ids(db, scope)
    data = []
    for r in rows:
        if allowed is not None and r["project_id"] not in allowed:
            continue
        r["gcj02"] = _to_gcj(r.get("longitude"), r.get("latitude"))
        data.append(r)
    return ApiResponse.success(data={"total": len(data), "items": data})


@router.get(
    "/trajectory",
    summary="设备轨迹回放",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("device:list"))],
)
def get_trajectory(
    device_no: str,
    start: str,
    end: str,
    db: Session = Depends(get_read_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = None,
) -> ApiResponse:
    """返回单设备在某时间段内的有序位置序列（轨迹回放）。

    坐标统一对外转换：WGS-84（设备）→ GCJ-02（高德地图）。
    start/end 为 ISO 时间字符串，如 `2026-07-15T00:00:00`。
    """
    try:
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
    except ValueError:
        raise BusinessError("start/end 需为 ISO 时间字符串，如 2026-07-15T00:00:00", code=400)
    if end_dt < start_dt:
        raise BusinessError("end 必须晚于 start", code=400)

    rows = trajectory(db, device_no=device_no, start=start_dt, end=end_dt, project_id=project_id)
    allowed = _scope_project_ids(db, scope)
    items = []
    for r in rows:
        if allowed is not None and r.project_id not in allowed:
            continue
        items.append(
            {
                "device_no": r.device_no,
                "device_name": r.device_name,
                "report_time": r.report_time.isoformat() if r.report_time else None,
                "longitude": r.longitude,
                "latitude": r.latitude,
                "gcj02": _to_gcj(r.longitude, r.latitude),
                "speed": r.speed,
                "status": r.status,
            }
        )
    return ApiResponse.success(data={"total": len(items), "items": items})


@router.post(
    "/command",
    summary="下发设备指令",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("device:command"))],
)
def send_command(
    req: DeviceCommandRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    """向指定设备下发指令（接口 2/4/6）。返回下发报文。

    部门数据隔离：仅当前用户可见项目内的设备可下发指令；
    越权访问返回 404（不泄露设备是否存在）。
    """
    # 部门隔离：解析设备所属项目并校验可见性
    device = resolve_device(db, req.device_type, req.device_no)
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    allowed = _scope_project_ids(db, scope)
    if allowed is not None and device["project_id"] not in allowed:
        raise HTTPException(status_code=404, detail="设备不存在或无权操作")

    try:
        payload = protocol.build_command(req.device_type, req.action, req.params)
    except protocol.ProtocolError as exc:
        raise BusinessError(str(exc), code=400)
    topic = down_topic(req.device_type, req.device_no)
    try:
        mqtt_client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"MQTT 下发失败：{exc}")
    return ApiResponse.success(
        data={
            "topic": topic,
            "device_type": req.device_type,
            "device_no": req.device_no,
            "action": req.action,
            "payload": payload,
        },
        message="指令已下发",
    )
