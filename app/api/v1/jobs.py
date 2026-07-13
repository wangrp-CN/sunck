"""作业计划管理路由（骨架占位，对应需求 §2.6：三步式 + 规则配置）。"""

from fastapi import APIRouter

router = APIRouter(tags=["作业计划"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "jobs", "status": "skeleton"}
