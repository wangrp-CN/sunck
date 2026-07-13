"""电子围栏管理路由（骨架占位，对应需求 §2.5：基于高德地图绘制区域）。"""

from fastapi import APIRouter

router = APIRouter(tags=["电子围栏"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "fences", "status": "skeleton"}
