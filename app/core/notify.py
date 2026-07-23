"""多渠道通知中心。

- 站内信(in_app)：落库 `notification` 表，前端铃铛读取并标记已读。
- 短信(sms)/语音(voice)：**预留适配器**——当前未接入第三方网关，仅落库留痕并打 WARNING，
  待凭据就绪后在此补全真实发送（不影响业务一致性）。

设计（v2，与部门数据隔离对齐）：
- 通知**按归属项目的数据范围收敛接收人**，不再向全部活跃用户广播，避免跨项目信息扩散、
  与部门数据隔离（`app.core.data_scope`）冲突。
- 接收人解析 `resolve_recipients_for_project` 复用 `resolve_data_scope`：
  - 超级管理员 / 数据范围=全部 的用户恒为接收人；
  - 其余用户仅当其部门数据范围（已展开含下级）覆盖「项目所属部门」时接收；
  - 项目无归属部门（dept_id 为空）时，仅「全部数据」用户接收（不向无权部门扩散）。
- 业务触发点（告警产生、隐患创建）统一经 `notify_for_project` 收敛后下发。
"""

import logging
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.data_scope import resolve_data_scope
from app.model.notification import Notification
from app.model.project import Project
from app.model.system import User

logger = logging.getLogger("rail_monitor.notify")


class InAppNotifier:
    channel = "in_app"

    def send(
        self, db: Session, user_id: int, title: str, content=None, link=None, category="alarm"
    ):
        db.add(
            Notification(
                user_id=user_id,
                channel=self.channel,
                category=category,
                title=title,
                content=content,
                link=link,
            )
        )


class SmsNotifier:
    """预留：短信网关未配置，仅留痕。"""

    channel = "sms"

    def send(
        self, db: Session, user_id: int, title: str, content=None, link=None, category="alarm"
    ):
        logger.warning("短信通知未启用(channel=sms)，仅落库留痕：user=%s title=%s", user_id, title)
        db.add(
            Notification(
                user_id=user_id,
                channel=self.channel,
                category=category,
                title=title,
                content=content,
                link=link,
            )
        )


class VoiceNotifier:
    """预留：语音网关未配置，仅留痕。"""

    channel = "voice"

    def send(
        self, db: Session, user_id: int, title: str, content=None, link=None, category="alarm"
    ):
        logger.warning(
            "语音通知未启用(channel=voice)，仅落库留痕：user=%s title=%s", user_id, title
        )
        db.add(
            Notification(
                user_id=user_id,
                channel=self.channel,
                category=category,
                title=title,
                content=content,
                link=link,
            )
        )


NOTIFIERS: dict[str, object] = {
    "in_app": InAppNotifier(),
    "sms": SmsNotifier(),
    "voice": VoiceNotifier(),
}


def notify(
    db: Session,
    user_ids,
    title: str,
    content=None,
    *,
    link=None,
    category="alarm",
    channels=("in_app",),
):
    """向一组用户经指定渠道发送通知（去重用户，逐渠道下发）。"""
    seen = set()
    for uid in user_ids:
        if uid in seen:
            continue
        seen.add(uid)
        for ch in channels:
            nt = NOTIFIERS.get(ch)
            if nt:
                nt.send(db, int(uid), title, content=content, link=link, category=category)


def resolve_recipients_for_project(db: Session, project_id: int | None) -> list[int]:
    """按项目数据范围收敛接收人。

    返回其部门数据范围覆盖「项目所属部门」且处于启用状态的用户 ID 列表：

    - ``is_all``（超级管理员 / 数据范围=全部）：恒为接收人；
    - 部门范围用户：仅当其 scope 展开部门集合包含项目所属部门时接收
      （与 ``apply_data_scope`` 判定一致，下方不越权）；
    - 项目无 ``dept_id`` 或 ``project_id`` 为 None：仅「全部数据」用户接收，
      避免把信息扩散到无权部门的用户。

    实现直接复用 ``app.core.data_scope.resolve_data_scope``，与全站数据隔离同源。
    """
    project = db.get(Project, project_id) if project_id else None
    target_dept = project.dept_id if project else None
    users = db.scalars(
        select(User)
        .where(User.is_deleted.is_(False), User.status.is_(True))
        .options(selectinload(User.roles))
    ).all()
    out: list[int] = []
    for u in users:
        scope = resolve_data_scope(u, db)
        if scope.is_all:
            out.append(u.id)
            continue
        if target_dept is not None and target_dept in scope.dept_ids:
            out.append(u.id)
    return out


def notify_for_project(
    db: Session,
    project_id: int | None,
    title: str,
    content=None,
    *,
    link=None,
    category="alarm",
    channels: Iterable[str] = ("in_app",),
) -> int:
    """向「项目数据范围内的用户」发送通知，返回实际接收人数。

    与 ``notify_alarm_raised`` / ``notify_hazard_created`` 共用，确保业务通知
    不再越权广播，与部门数据隔离保持一致。
    """
    user_ids = resolve_recipients_for_project(db, project_id)
    if not user_ids:
        logger.info("通知收敛：项目 %s 在数据范围内无可接收用户（已按数据隔离过滤）", project_id)
        return 0
    notify(db, user_ids, title, content=content, link=link, category=category, channels=channels)
    return len(user_ids)


def notify_alarm_raised(db: Session, alarm, actor_name: str | None = None) -> int:
    """告警产生时推送站内信（v2：按告警所属项目数据范围收敛接收人）。

    修复此前「向全部活跃用户广播」与部门数据隔离冲突的问题——现仅通知
    其部门数据范围覆盖告警归属项目部门的用户（超级管理员恒接收）。
    """
    level = alarm.alarm_level or "未分级"
    dev = alarm.device_name or alarm.device_no or "设备"
    title = f"新告警：{level}级 / {dev}"
    content = alarm.alarm_info or f"类型={alarm.alarm_type}"
    return notify_for_project(
        db,
        alarm.project_id,
        title,
        content=content,
        link="/alarms",
        category="alarm",
        channels=("in_app",),
    )


def notify_hazard_created(db: Session, hazard, actor_name: str | None = None) -> int:
    """隐患创建（含告警转隐患）时推送站内信（按隐患所属项目数据范围收敛接收人）。

    与告警通知同源收敛，确保「监测→治理」闭环里的治理侧通知同样遵守部门数据隔离。
    """
    level = hazard.level or "一般"
    title = f"新隐患：{level}级 / {hazard.title or '未命名'}"
    content = hazard.description or f"类别={hazard.category}"
    return notify_for_project(
        db,
        hazard.project_id,
        title,
        content=content,
        link=f"/hazards?highlight={hazard.id}",
        category="hazard",
        channels=("in_app",),
    )
