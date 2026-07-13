"""系统管理路由（骨架占位，对应需求 §2.10：用户管理/地图维护）。"""

from fastapi import APIRouter

router = APIRouter(tags=["系统管理"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "system", "status": "skeleton"}
