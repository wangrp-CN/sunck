"""API 路由汇总（v1）。

按《开发计划》功能模块挂载：认证、项目、设备、人员、机械、围栏、作业、告警、系统、大屏。
"""

from fastapi import APIRouter

from app.api.v1 import (
    alarms,
    auth,
    dashboard,
    departments,
    devices,
    fences,
    jobs,
    machines,
    persons,
    projects,
    system,
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
api_router.include_router(system.router, prefix="/v1/system", tags=["系统管理"])
api_router.include_router(dashboard.router, prefix="/v1/dashboard", tags=["大屏"])
