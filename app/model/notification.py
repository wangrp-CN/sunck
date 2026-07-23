"""通知中心域模型：站内信/短信/语音等多渠道通知的统一落库载体。

- 站内信(in_app) 为平台内通知，前端铃铛读取并标记已读。
- 短信(sms)/语音(voice) 为预留渠道：当前未接入第三方网关，落库留痕即可，
  待凭据就绪后在 app.core.notify 的适配器中补全真实发送。
- 通知自解释（按 user_id 过滤），无需部门数据隔离。
"""

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, TimestampMixin


class Notification(Base, TimestampMixin):
    __tablename__ = "notification"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="接收用户",
    )
    # 渠道：in_app(站内信)/sms(短信)/voice(语音)
    channel: Mapped[str] = mapped_column(
        String(16), default="in_app", index=True, comment="通知渠道"
    )
    # 类别：alarm(告警)/system(系统)/hazard(隐患) 等
    category: Mapped[str] = mapped_column(
        String(32), default="alarm", index=True, comment="通知类别"
    )
    title: Mapped[str] = mapped_column(String(255), comment="标题")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="内容")
    # 跳转链接（前端路由，如 /hazards?highlight=123）
    link: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="跳转链接")
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True, comment="是否已读"
    )
