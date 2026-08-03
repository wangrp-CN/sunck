"""数据模型层（SQLAlchemy ORM）。

各域模型按《开发计划》功能模块拆分：
system（用户/角色/部门）、project、device（三类设备）、person（人员/机械）、
fence（电子围栏）、job（作业计划）、alarm（告警）。

导入本包即把所有表注册到 `Base.metadata`，供 Alembic 生成迁移。
"""

from app.model import (  # noqa: F401
    alarm,
    alarm_policy,
    attachment,
    audit,
    command,
    correlation,
    device,
    dispatch,
    disposition,
    duty_roster,
    feature,
    fence,
    forecast,
    forecast_backtest,
    hazard,
    inspection,
    job,
    knowledge,
    map_asset,
    map_drawing,
    notification,
    notification_delivery,
    person,
    playbook,
    project,
    realtime,
    report_subscription,
    risk_alert,
    snapshot,
    system,
    video,
)
from app.model import dict as dict_model  # noqa: F401
from app.model.base import Base, TimestampMixin  # noqa: F401
