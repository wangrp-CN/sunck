"""大屏路由（骨架占位，对应需求 §2.3：地图/轨迹/告警联动可视化）。"""

from fastapi import APIRouter

router = APIRouter(tags=["大屏"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "dashboard", "status": "skeleton"}
