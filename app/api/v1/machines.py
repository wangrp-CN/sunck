"""大型机械管理路由（骨架占位，对应需求 §2.8.2）。"""

from fastapi import APIRouter

router = APIRouter(tags=["大型机械"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "machines", "status": "skeleton"}
