"""API 路由汇总（v1）。

按《开发计划》功能模块挂载：认证、项目、设备、人员、机械、围栏、作业、告警、系统、大屏。
"""

from fastapi import APIRouter

from app.api.v1 import (
    alarms,
    attachments,
    audit_logs,
    auth,
    dashboard,
    departments,
    devices,
    dicts,
    fences,
    hazards,
    inspections,
    jobs,
    machines,
    media,
    notifications,
    persons,
    projects,
    realtime,
    videos,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router, prefix="/v1/auth", tags=["认证"])
api_router.include_router(departments.router, prefix="/v1/departments", tags=["部门管理"])
api_router.include_router(projects.router, prefix="/v1/projects", tags=["项目管理"])
api_router.include_router(devices.router, prefix="/v1/devices", tags=["设备管理"])
api_router.include_router(persons.router, prefix="/v1/persons", tags=["人员管理"])
api_router.include_router(machines.router, prefix="/v1/machines", tags=["大型机械"])
api_router.include_router(fences.router, prefix="/v1/fences", tags=["电子围栏"])
api_router.include_router(jobs.router, prefix="/v1/jobs", tags=["作业计划"])
api_router.include_router(alarms.router, prefix="/v1/alarms", tags=["告警管理"])
api_router.include_router(hazards.router, prefix="/v1/hazards", tags=["隐患治理"])
api_router.include_router(notifications.router, prefix="/v1/notifications", tags=["通知中心"])
api_router.include_router(realtime.router, prefix="/v1/realtime", tags=["实时链路"])
api_router.include_router(dashboard.router, prefix="/v1/dashboard", tags=["大屏"])
api_router.include_router(media.router, prefix="/v1/media", tags=["媒体管理"])
api_router.include_router(attachments.router, prefix="/v1/attachments", tags=["附件"])
api_router.include_router(audit_logs.router, prefix="/v1/audit-logs", tags=["操作审计"])
api_router.include_router(dicts.router, prefix="/v1/dicts", tags=["数据字典"])
api_router.include_router(inspections.router, prefix="/v1/inspections", tags=["巡检打卡"])
api_router.include_router(videos.router, prefix="/v1/videos", tags=["视频AI"])
