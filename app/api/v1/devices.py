"""设备管理路由（骨架占位，对应需求 §2.7：人机定位/大机防侵限/列车接近三类设备）。"""

from fastapi import APIRouter

router = APIRouter(tags=["设备管理"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "devices", "status": "skeleton"}
