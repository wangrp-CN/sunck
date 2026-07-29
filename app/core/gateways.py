"""短信 / 语音网关适配器（P2① · 模拟真实数据，可一键切换真实网关）。

设计：
- 平台不关心具体网关厂商，统一经 `GatewayResult` 回执（provider / biz_id / request_id /
  code / message / status / raw），与真实网关回执形态一致，便于排障与对接。
- ``Simulated*Gateway``：**模拟模式**（默认，无需任何第三方凭据）。生成真实形态的回执
  （如阿里云短信的 ``Code/Message/RequestId/BizId``），让「无凭据」阶段也能跑通完整链路、
  生成可核对的触达数据。
- ``Real*Gateway``：**真实模式**。仅当配置了 provider 凭据（``sms_api_key`` 等）才发起真实调用；
  凭据缺失返回 ``status=not_configured``，调用异常返回 ``status=error``——**绝不向上抛异常中断业务**。
- 切换：``app.config`` 的 ``sms_mode`` / ``voice_mode`` = ``simulate``(默认) | ``real``。
  后续接入阿里云/腾讯云/Twilio 时，在 ``Real*Gateway`` 内补全 ``_call_provider`` 即可，契约不变。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.config import settings


@dataclass
class GatewayResult:
    """网关下发回执（统一形态，模拟/真实通用）。"""

    channel: str
    provider: str
    phone: str | None
    content: str | None
    status: str  # sent / failed / no_phone / not_configured / error
    code: str | None = None
    message: str | None = None
    biz_id: str | None = None
    request_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    sent_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_record(self, user_id: int | None = None) -> dict:
        """转为 ``notification_delivery`` 落库字段（raw 序列化为 JSON 文本）。"""
        return {
            "user_id": user_id,
            "channel": self.channel,
            "provider": self.provider,
            "phone": self.phone,
            "content": self.content,
            "biz_id": self.biz_id,
            "request_id": self.request_id,
            "code": self.code,
            "message": self.message,
            "status": self.status,
            "raw": __import__("json").dumps(self.raw, ensure_ascii=False),
        }


def _gen_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:20]}"


class SimulatedSmsGateway:
    """模拟短信网关：生成阿里云风格的回执，无需任何凭据。"""

    channel = "sms"
    provider = "mock-sms"

    def send(self, phone: str | None, content: str | None, **kwargs: Any) -> GatewayResult:
        if not phone:
            return GatewayResult(
                channel=self.channel,
                provider=self.provider,
                phone=phone,
                content=content,
                status="no_phone",
                code="NO_PHONE",
                message="收件人未配置手机号",
            )
        request_id = _gen_id("REQ")
        biz_id = _gen_id("BIZ")
        raw = {
            "Code": "OK",
            "Message": "OK",
            "RequestId": request_id,
            "BizId": biz_id,
        }
        return GatewayResult(
            channel=self.channel,
            provider=self.provider,
            phone=phone,
            content=content,
            status="sent",
            code="OK",
            message="OK",
            biz_id=biz_id,
            request_id=request_id,
            raw=raw,
        )


class SimulatedVoiceGateway:
    """模拟语音网关：生成语音通知风格的回执（CallId），无需任何凭据。"""

    channel = "voice"
    provider = "mock-voice"

    def send(self, phone: str | None, content: str | None, **kwargs: Any) -> GatewayResult:
        if not phone:
            return GatewayResult(
                channel=self.channel,
                provider=self.provider,
                phone=phone,
                content=content,
                status="no_phone",
                code="NO_PHONE",
                message="收件人未配置手机号",
            )
        request_id = _gen_id("REQ")
        call_id = _gen_id("CALL")
        raw = {
            "Code": "OK",
            "Message": "OK",
            "RequestId": request_id,
            "CallId": call_id,
        }
        return GatewayResult(
            channel=self.channel,
            provider=self.provider,
            phone=phone,
            content=content,
            status="sent",
            code="OK",
            message="OK",
            biz_id=call_id,
            request_id=request_id,
            raw=raw,
        )


class RealSmsGateway:
    """真实短信网关（阿里云/腾讯云/Twilio 等）占位适配器。

    凭据缺失 → ``not_configured``；凭据就绪后在此补全 ``_call_provider`` 真实调用即可，
    ``GatewayResult`` 契约不变，上层无需改动。
    """

    channel = "sms"
    provider = "real-sms"

    def send(self, phone: str | None, content: str | None, **kwargs: Any) -> GatewayResult:
        if not settings.sms_api_key:
            return GatewayResult(
                channel=self.channel,
                provider=self.provider,
                phone=phone,
                content=content,
                status="not_configured",
                code="NO_CRED",
                message="未配置短信网关凭据(sms_api_key)",
            )
        # TODO(real): 凭据就绪后在此调用真实网关（如阿里云 SendSms），将返回映射为 GatewayResult。
        try:
            return self._call_provider(phone, content, **kwargs)
        except NotImplementedError as exc:
            return GatewayResult(
                channel=self.channel,
                provider=self.provider,
                phone=phone,
                content=content,
                status="error",
                code="NOT_IMPL",
                message=f"真实短信网关未实现: {exc}",
            )

    @staticmethod
    def _call_provider(phone: str | None, content: str | None, **kwargs: Any) -> GatewayResult:
        raise NotImplementedError("真实短信网关调用待接入（配置 sms_api_key 后实现）")


class RealVoiceGateway:
    """真实语音网关占位适配器，契约同 RealSmsGateway。"""

    channel = "voice"
    provider = "real-voice"

    def send(self, phone: str | None, content: str | None, **kwargs: Any) -> GatewayResult:
        if not settings.voice_api_key:
            return GatewayResult(
                channel=self.channel,
                provider=self.provider,
                phone=phone,
                content=content,
                status="not_configured",
                code="NO_CRED",
                message="未配置语音网关凭据(voice_api_key)",
            )
        try:
            return self._call_provider(phone, content, **kwargs)
        except NotImplementedError as exc:
            return GatewayResult(
                channel=self.channel,
                provider=self.provider,
                phone=phone,
                content=content,
                status="error",
                code="NOT_IMPL",
                message=f"真实语音网关未实现: {exc}",
            )

    @staticmethod
    def _call_provider(phone: str | None, content: str | None, **kwargs: Any) -> GatewayResult:
        raise NotImplementedError("真实语音网关调用待接入（配置 voice_api_key 后实现）")


def get_gateway(channel: str):
    """按配置选择网关：simulate(默认) → 模拟；real → 真实(凭据门控)。"""
    if channel == "sms":
        return SimulatedSmsGateway() if settings.sms_mode != "real" else RealSmsGateway()
    if channel == "voice":
        return SimulatedVoiceGateway() if settings.voice_mode != "real" else RealVoiceGateway()
    raise ValueError(f"未知通知渠道: {channel}")


def send_via_gateway(
    channel: str, phone: str | None, content: str | None, **kwargs: Any
) -> GatewayResult:
    """统一入口：选择网关并下发，返回回执（永不抛异常）。"""
    try:
        return get_gateway(channel).send(phone, content, **kwargs)
    except Exception as exc:  # 兜底：任何意外都不应中断业务通知
        return GatewayResult(
            channel=channel,
            provider="error",
            phone=phone,
            content=content,
            status="error",
            code="EXC",
            message=f"网关调用异常: {exc}",
        )
