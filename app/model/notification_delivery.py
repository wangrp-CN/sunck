"""短信/语音网关触达记录（P2① · 模拟真实数据）。

- 平台短信(sms)/语音(voice) 经网关适配器下发；在「模拟模式」(`sms_mode/voice_mode=simulate`，
  默认，无需第三方凭据) 下由 `app.core.gateways` 生成**真实形态的网关回执**
  （provider / biz_id / request_id / code / message / status / raw），本表落库留存，
  可直接查询、核对，等价于真实网关的「发送回执」。
- 真实模式(`real`) 配置 provider 凭据后改为调用真实网关；凭据缺失时回执 status=`not_configured`。
- 该表为网关回执审计载体，与 `notification`(站内信/渠道留痕) 解耦：前者记「是否真正送达第三方」，
  后者记「平台内通知实体」。
"""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, TimestampMixin


class NotificationDelivery(Base, TimestampMixin):
    __tablename__ = "notification_delivery"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 关联接收用户；测试发送 / 无登录上下文可为空
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="接收用户（测试发送可空）",
    )
    # 渠道：sms(短信)/voice(语音)
    channel: Mapped[str] = mapped_column(String(16), index=True, comment="渠道")
    # 网关提供方：mock(模拟) / aliyun / twilio / ...
    provider: Mapped[str] = mapped_column(String(32), default="mock", comment="网关提供方")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="接收手机号")
    content: Mapped[str | None] = mapped_column(Text, nullable=True, comment="发送内容")
    # 网关回执字段（模拟真实数据形态）
    biz_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="业务流水号")
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="请求ID")
    code: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="网关返回码")
    message: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="网关返回信息")
    # 触达状态：sent / failed / no_phone / not_configured / error
    status: Mapped[str] = mapped_column(String(24), default="sent", index=True, comment="触达状态")
    # 网关原始响应（JSON 字符串），便于排障与对接
    raw: Mapped[str | None] = mapped_column(Text, nullable=True, comment="网关原始响应(JSON)")
