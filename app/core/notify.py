"""多渠道通知中心。

- 站内信(in_app)：落库 `notification` 表，前端铃铛读取并标记已读。
- 短信(sms)/语音(voice)：**预留适配器**——当前未接入第三方网关，仅落库留痕并打 WARNING，
  待凭据就绪后在此补全真实发送（不影响业务一致性）。

设计：通知自解释（按 user_id 过滤），不依赖部门数据隔离；告警产生时由
`alarm_service.create_alarm` 触发站内信（去重后仅对新告警广播给活跃用户）。
"""

import logging

from sqlalchemy.orm import Session

from app.model.notification import Notification

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


def notify_alarm_raised(db: Session, alarm, actor_name: str | None = None) -> None:
    """告警产生时推送站内信（MVP：广播给所有活跃用户）。

    说明：当前为最简闭环演示，向全部活跃用户广播站内信。后续可据
    告警所属项目的数据范围 / 用户角色（如 `alarm:list` 关注人）收敛接收人，
    避免跨项目信息扩散。
    """
    from app.model.system import User

    user_ids = [
        u[0]
        for u in db.query(User.id).filter(User.is_deleted.is_(False), User.status.is_(True)).all()
    ]
    if not user_ids:
        return
    level = alarm.alarm_level or "未分级"
    dev = alarm.device_name or alarm.device_no or "设备"
    title = f"新告警：{level}级 / {dev}"
    content = alarm.alarm_info or f"类型={alarm.alarm_type}"
    notify(
        db,
        user_ids,
        title,
        content=content,
        link="/alarms",
        category="alarm",
        channels=("in_app",),
    )
