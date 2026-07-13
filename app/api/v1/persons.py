"""人员管理路由（骨架占位，对应需求 §2.8.1）。"""

from fastapi import APIRouter

router = APIRouter(tags=["人员管理"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "persons", "status": "skeleton"}
