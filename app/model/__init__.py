"""数据模型层（SQLAlchemy ORM）。

各域模型按《开发计划》功能模块拆分：
system（用户/角色/部门）、project、device（三类设备）、person（人员/机械）、
fence（电子围栏）、job（作业计划）、alarm（告警）。

导入本包即把所有表注册到 `Base.metadata`，供 Alembic 生成迁移。
"""

from app.model import (  # noqa: F401
    alarm,
    attachment,
    audit,
    device,
    fence,
    hazard,
    inspection,
    job,
    notification,
    person,
    project,
    realtime,
    snapshot,
    system,
    video,
)
from app.model import dict as dict_model  # noqa: F401
from app.model.base import Base, TimestampMixin  # noqa: F401
