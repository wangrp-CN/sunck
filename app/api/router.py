"""API 路由汇总（v1）。

按《开发计划》功能模块挂载：认证、项目、设备、人员、机械、围栏、作业、告警、系统、大屏。
"""

from fastapi import APIRouter

from app.api.v1 import (
    alarm_policies,
    alarms,
    attachments,
    audit_logs,
    auth,
    commands,
    dashboard,
    departments,
    devices,
    dicts,
    dispatch,
    dispositions,
    duty,
    fences,
    forecasts,
    hazards,
    inspections,
    intelligence,
    jobs,
    knowledge,
    machines,
    media,
    metrics,
    notifications,
    persons,
    playbooks,
    projects,
    realtime,
    reports,
    subscriptions,
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
api_router.include_router(dispositions.router, prefix="/v1/dispositions", tags=["告警处置"])
api_router.include_router(alarm_policies.router, prefix="/v1/alarm-policies", tags=["告警策略"])
api_router.include_router(playbooks.router, prefix="/v1/playbooks", tags=["处置预案"])
api_router.include_router(knowledge.router, prefix="/v1/knowledge", tags=["知识库"])
api_router.include_router(hazards.router, prefix="/v1/hazards", tags=["隐患治理"])
api_router.include_router(notifications.router, prefix="/v1/notifications", tags=["通知中心"])
api_router.include_router(realtime.router, prefix="/v1/realtime", tags=["实时链路"])
api_router.include_router(dashboard.router, prefix="/v1/dashboard", tags=["大屏"])
api_router.include_router(dispatch.router, prefix="/v1/dispatch", tags=["根因派单"])
api_router.include_router(media.router, prefix="/v1/media", tags=["媒体管理"])
api_router.include_router(attachments.router, prefix="/v1/attachments", tags=["附件"])
api_router.include_router(audit_logs.router, prefix="/v1/audit-logs", tags=["操作审计"])
api_router.include_router(dicts.router, prefix="/v1/dicts", tags=["数据字典"])
api_router.include_router(duty.router, prefix="/v1/duty", tags=["值班排班"])
api_router.include_router(inspections.router, prefix="/v1/inspections", tags=["巡检打卡"])
api_router.include_router(videos.router, prefix="/v1/videos", tags=["视频AI"])
api_router.include_router(metrics.router, prefix="/v1/metrics", tags=["指标快照"])
api_router.include_router(commands.router, prefix="/v1/commands", tags=["指令下发"])
api_router.include_router(forecasts.router, prefix="/v1/forecasts", tags=["风险预测"])
api_router.include_router(intelligence.router, prefix="", tags=["智能核心"])
api_router.include_router(subscriptions.router, prefix="", tags=["报告订阅"])
api_router.include_router(reports.router, prefix="/v1", tags=["报表导出"])
