"""设备服务：按类型解析设备（编号→项目/名称），并汇总设备列表（地图展示用）。"""

from typing import Any

from sqlalchemy import select

from app.core.constants import (
    DEVICE_TYPE_ANTI_INTRUSION,
    DEVICE_TYPE_LOCATE,
    DEVICE_TYPE_TRAIN_APPROACH,
)
from app.model.device import AntiIntrusionDevice, LocateDevice, TrainApproachDevice

_MODEL_BY_TYPE: dict[str, type] = {
    DEVICE_TYPE_LOCATE: LocateDevice,
    DEVICE_TYPE_ANTI_INTRUSION: AntiIntrusionDevice,
    DEVICE_TYPE_TRAIN_APPROACH: TrainApproachDevice,
}

_LABEL_BY_TYPE: dict[str, str] = {
    DEVICE_TYPE_LOCATE: "人机定位",
    DEVICE_TYPE_ANTI_INTRUSION: "大机防侵限",
    DEVICE_TYPE_TRAIN_APPROACH: "列车接近",
}


def device_model(device_type: str) -> type | None:
    return _MODEL_BY_TYPE.get(device_type)


def resolve_device(db, device_type: str, device_no: str) -> dict[str, Any] | None:
    """按 (设备类型, 设备编号) 解析设备，返回 {project_id, name, device_id}。

    找不到返回 None（设备未登记）；上游仍可落库为孤儿位置，但不做规则判定。
    """
    model = _MODEL_BY_TYPE.get(device_type)
    if model is None:
        return None
    row = db.scalar(select(model).where(model.device_no == device_no))
    if row is None:
        return None
    return {"project_id": row.project_id, "name": row.name, "device_id": row.id}


def list_devices(db, project_id: int | None = None, device_type: str | None = None) -> list[dict]:
    """汇总三类设备，返回统一的地图打点列表。"""
    out: list[dict] = []
    types = [device_type] if device_type else list(_MODEL_BY_TYPE.keys())
    for dtype in types:
        model = _MODEL_BY_TYPE[dtype]
        stmt = select(model)
        if project_id is not None:
            stmt = stmt.where(model.project_id == project_id)
        rows = db.scalars(stmt.order_by(model.id)).all()
        for r in rows:
            out.append(
                {
                    "device_type": dtype,
                    "device_type_label": _LABEL_BY_TYPE.get(dtype, dtype),
                    "device_id": r.id,
                    "device_no": r.device_no,
                    "name": r.name,
                    "project_id": r.project_id,
                    "longitude": getattr(r, "longitude", None),
                    "latitude": getattr(r, "latitude", None),
                    "status": r.status,
                }
            )
    return out
