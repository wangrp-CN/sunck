"""告警管理路由（骨架占位，对应需求 §2.9：设备告警/前端告警/告警配置）。"""

from fastapi import APIRouter

router = APIRouter(tags=["告警管理"])


@router.get("/ping")
def ping() -> dict:
    return {"module": "alarms", "status": "skeleton"}
