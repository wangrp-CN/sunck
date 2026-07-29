"""短信 / 语音网关适配器（P2① · 模拟真实数据，可一键切换真实网关）。

设计：
- 平台不关心具体网关厂商，统一经 `GatewayResult` 回执（provider / biz_id / request_id /
  code / message / status / raw），与真实网关回执形态一致，便于排障与对接。
- ``Simulated*Gateway``：**模拟模式**（默认，无需任何第三方凭据）。生成真实形态的回执
  （如阿里云短信的 ``Code/Message/RequestId/BizId``），让「无凭据」阶段也能跑通完整链路、
  生成可核对的触达数据。
- ``Real*Gateway``：**真实模式 + 双厂商抽象**。``sms_provider`` / ``voice_provider`` 取
  ``aliyun`` / ``tencent``（``mock`` 仅用于 simulate 模式）。各厂商调用封装在 ``_aliyun_*`` /
  ``_tencent_*`` 方法内，经懒加载导入厂商 SDK：
  * 凭据缺失 / 厂商未配置 → ``not_configured``；
  * SDK 未安装 / 调用异常 → ``error``（含明确提示，绝不向上抛异常中断业务）；
  * 厂商 SDK 仅在真实调用时导入，**模块导入期不依赖任何第三方 SDK**，平台无 SDK 也能正常启动。
- 切换：``app.config`` 的 ``sms_mode`` / ``voice_mode`` = ``simulate``(默认) | ``real``。
  真实模式配置好对应 ``*_api_key`` + 厂商模板/AppId 并 ``pip install`` 对应 SDK 后，
  业务零改动即可下发真实短信/语音。
"""

from __future__ import annotations

import json
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


# 支持的真实短信厂商（sms_provider 取值）；mock 走模拟网关。
SMS_VENDORS = ("aliyun", "tencent")
# 支持的真实语音厂商（voice_provider 取值）。
VOICE_VENDORS = ("aliyun", "tencent")


class RealSmsGateway:
    """真实短信网关（双厂商：阿里云 / 腾讯云）。

    - ``sms_mode=real`` 时由 ``get_gateway`` 选用本类；``sms_provider`` 决定厂商。
    - 凭据缺失 / 厂商未配置 → ``not_configured``；SDK 未安装 / 调用异常 → ``error``；
      绝不向上抛异常中断业务（``send_via_gateway`` 另有顶层兜底）。
    - 厂商 SDK **懒加载**导入：未安装时返回 ``SDK_MISSING`` 而不在模块导入期报错，
      因此即便没装 aliyun/tencent SDK，平台也能正常启动（仅真实下发不可用）。
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
        if settings.sms_provider not in SMS_VENDORS:
            return GatewayResult(
                channel=self.channel,
                provider=self.provider,
                phone=phone,
                content=content,
                status="not_configured",
                code="BAD_PROVIDER",
                message=f"sms_provider 须为 aliyun|tencent，当前={settings.sms_provider}",
            )
        try:
            return self._call_provider(phone, content, **kwargs)
        except Exception as exc:  # 厂商适配任何意外都降级为 error 回执
            return GatewayResult(
                channel=self.channel,
                provider=settings.sms_provider,
                phone=phone,
                content=content,
                status="error",
                code="EXC",
                message=f"短信网关调用异常: {exc}",
            )

    def _call_provider(self, phone, content, **kwargs):
        if settings.sms_provider == "aliyun":
            return self._aliyun_sms(phone, content, **kwargs)
        if settings.sms_provider == "tencent":
            return self._tencent_sms(phone, content, **kwargs)
        return GatewayResult(
            channel=self.channel,
            provider=settings.sms_provider,
            phone=phone,
            content=content,
            status="error",
            code="BAD_PROVIDER",
            message=f"不支持的短信厂商: {settings.sms_provider}",
        )

    # ---- 阿里云短信（Dysmsapi SendSms） ----
    def _aliyun_sms(self, phone, content, **kwargs):
        if not settings.sms_template_code:
            return GatewayResult(
                channel=self.channel,
                provider="aliyun",
                phone=phone,
                content=content,
                status="not_configured",
                code="NO_TEMPLATE",
                message="未配置阿里云短信模板(sms_template_code)",
            )
        try:
            from alibabacloud_dysmsapi20170525 import models as dysms_models
            from alibabacloud_dysmsapi20170525.client import Client as DysmsClient
            from alibabacloud_tea_openapi import models as open_api_models
            from alibabacloud_tea_util import models as util_models
        except ImportError as exc:
            return GatewayResult(
                channel=self.channel,
                provider="aliyun",
                phone=phone,
                content=content,
                status="error",
                code="SDK_MISSING",
                message=f"未安装阿里云短信 SDK（pip install alibabacloud_dysmsapi20170525 alibabacloud-tea-openapi）: {exc}",
            )
        try:
            cfg = open_api_models.Config(
                access_key_id=settings.sms_api_key, access_key_secret=settings.sms_api_secret
            )
            cfg.endpoint = "dysmsapi.aliyuncs.com"
            client = DysmsClient(cfg)
            tpl_param = kwargs.get("template_param") or {"content": content or ""}
            req = dysms_models.SendSmsRequest(
                phone_numbers=phone,
                sign_name=settings.sms_sign_name,
                template_code=settings.sms_template_code,
                template_param=json.dumps(tpl_param, ensure_ascii=False),
            )
            resp = client.send_sms_with_options(req, util_models.RuntimeOptions())
            body = resp.body
            raw = body.to_map()
            if getattr(body, "code", None) == "OK":
                return GatewayResult(
                    channel=self.channel,
                    provider="aliyun",
                    phone=phone,
                    content=content,
                    status="sent",
                    code=body.code,
                    message=body.message,
                    biz_id=getattr(body, "biz_id", None),
                    request_id=getattr(body, "request_id", None),
                    raw=raw,
                )
            return GatewayResult(
                channel=self.channel,
                provider="aliyun",
                phone=phone,
                content=content,
                status="failed",
                code=body.code,
                message=body.message,
                request_id=getattr(body, "request_id", None),
                raw=raw,
            )
        except Exception as exc:
            return GatewayResult(
                channel=self.channel,
                provider="aliyun",
                phone=phone,
                content=content,
                status="error",
                code="ALIYUN_ERR",
                message=f"阿里云短信调用失败: {exc}",
            )

    # ---- 腾讯云短信（SMS SendSms） ----
    def _tencent_sms(self, phone, content, **kwargs):
        if not settings.sms_app_id or not settings.sms_template_id:
            return GatewayResult(
                channel=self.channel,
                provider="tencent",
                phone=phone,
                content=content,
                status="not_configured",
                code="NO_TMPL",
                message="未配置腾讯云短信 AppId/TemplateId(sms_app_id/sms_template_id)",
            )
        try:
            from tencentcloud.common import credential
            from tencentcloud.sms.v20210111 import models as sms_models
            from tencentcloud.sms.v20210111 import sms_client
        except ImportError as exc:
            return GatewayResult(
                channel=self.channel,
                provider="tencent",
                phone=phone,
                content=content,
                status="error",
                code="SDK_MISSING",
                message=f"未安装腾讯云 SDK（pip install tencentcloud-sdk-python）: {exc}",
            )
        try:
            cred = credential.Credential(settings.sms_api_key, settings.sms_api_secret)
            client = sms_client.SmsClient(cred, settings.tencent_region)
            req = sms_models.SendSmsRequest()
            req.SmsSdkAppId = settings.sms_app_id
            req.SignName = settings.sms_sign_name
            req.TemplateId = settings.sms_template_id
            req.PhoneNumberSet = [phone]
            req.TemplateParamSet = [content or ""]
            resp = client.SendSms(req)
            status_set = getattr(resp, "SendStatusSet", []) or []
            if not status_set:
                return GatewayResult(
                    channel=self.channel,
                    provider="tencent",
                    phone=phone,
                    content=content,
                    status="error",
                    code="NO_STATUS",
                    message="腾讯云未返回发送状态",
                )
            st = status_set[0]
            raw = _safe_serialize(resp)
            if getattr(st, "Code", None) == "Ok":
                return GatewayResult(
                    channel=self.channel,
                    provider="tencent",
                    phone=phone,
                    content=content,
                    status="sent",
                    code=st.Code,
                    message=st.Message,
                    biz_id=getattr(st, "SerialNo", None),
                    request_id=getattr(st, "SerialNo", None),
                    raw=raw,
                )
            return GatewayResult(
                channel=self.channel,
                provider="tencent",
                phone=phone,
                content=content,
                status="failed",
                code=st.Code,
                message=st.Message,
                raw=raw,
            )
        except Exception as exc:
            return GatewayResult(
                channel=self.channel,
                provider="tencent",
                phone=phone,
                content=content,
                status="error",
                code="TENCENT_ERR",
                message=f"腾讯云短信调用失败: {exc}",
            )


class RealVoiceGateway:
    """真实语音网关（双厂商：阿里云 / 腾讯云），契约同 RealSmsGateway。"""

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
        if settings.voice_provider not in VOICE_VENDORS:
            return GatewayResult(
                channel=self.channel,
                provider=self.provider,
                phone=phone,
                content=content,
                status="not_configured",
                code="BAD_PROVIDER",
                message=f"voice_provider 须为 aliyun|tencent，当前={settings.voice_provider}",
            )
        try:
            return self._call_provider(phone, content, **kwargs)
        except Exception as exc:
            return GatewayResult(
                channel=self.channel,
                provider=settings.voice_provider,
                phone=phone,
                content=content,
                status="error",
                code="EXC",
                message=f"语音网关调用异常: {exc}",
            )

    def _call_provider(self, phone, content, **kwargs):
        if settings.voice_provider == "aliyun":
            return self._aliyun_voice(phone, content, **kwargs)
        if settings.voice_provider == "tencent":
            return self._tencent_voice(phone, content, **kwargs)
        return GatewayResult(
            channel=self.channel,
            provider=settings.voice_provider,
            phone=phone,
            content=content,
            status="error",
            code="BAD_PROVIDER",
            message=f"不支持的语音厂商: {settings.voice_provider}",
        )

    # ---- 阿里云语音通知（Dyvmsapi SingleCallByTts） ----
    def _aliyun_voice(self, phone, content, **kwargs):
        if not settings.voice_template_code:
            return GatewayResult(
                channel=self.channel,
                provider="aliyun",
                phone=phone,
                content=content,
                status="not_configured",
                code="NO_TEMPLATE",
                message="未配置阿里云语音模板(voice_template_code)",
            )
        try:
            from alibabacloud_dyvmsapi20170525 import models as dyvms_models
            from alibabacloud_dyvmsapi20170525.client import Client as DyvmsClient
            from alibabacloud_tea_openapi import models as open_api_models
            from alibabacloud_tea_util import models as util_models
        except ImportError as exc:
            return GatewayResult(
                channel=self.channel,
                provider="aliyun",
                phone=phone,
                content=content,
                status="error",
                code="SDK_MISSING",
                message=f"未安装阿里云语音 SDK（pip install alibabacloud_dyvmsapi20170525 alibabacloud-tea-openapi）: {exc}",
            )
        try:
            cfg = open_api_models.Config(
                access_key_id=settings.voice_api_key, access_key_secret=settings.voice_api_secret
            )
            cfg.endpoint = "dyvmsapi.aliyuncs.com"
            client = DyvmsClient(cfg)
            req = dyvms_models.SingleCallByTtsRequest(
                called_number=phone,
                tts_code=settings.voice_template_code,
                tts_param=json.dumps({"content": content or ""}, ensure_ascii=False),
                called_show_number=settings.voice_called_show_number or "",
            )
            resp = client.single_call_by_tts_with_options(req, util_models.RuntimeOptions())
            body = resp.body
            raw = body.to_map()
            if getattr(body, "code", None) == "OK":
                return GatewayResult(
                    channel=self.channel,
                    provider="aliyun",
                    phone=phone,
                    content=content,
                    status="sent",
                    code=body.code,
                    message=body.message,
                    biz_id=getattr(body, "call_id", None),
                    request_id=getattr(body, "request_id", None),
                    raw=raw,
                )
            return GatewayResult(
                channel=self.channel,
                provider="aliyun",
                phone=phone,
                content=content,
                status="failed",
                code=body.code,
                message=body.message,
                request_id=getattr(body, "request_id", None),
                raw=raw,
            )
        except Exception as exc:
            return GatewayResult(
                channel=self.channel,
                provider="aliyun",
                phone=phone,
                content=content,
                status="error",
                code="ALIYUN_ERR",
                message=f"阿里云语音调用失败: {exc}",
            )

    # ---- 腾讯云语音通知（VMS SendTtsVoice） ----
    def _tencent_voice(self, phone, content, **kwargs):
        if not settings.voice_app_id or not settings.voice_template_id:
            return GatewayResult(
                channel=self.channel,
                provider="tencent",
                phone=phone,
                content=content,
                status="not_configured",
                code="NO_TMPL",
                message="未配置腾讯云语音 AppId/TemplateId(voice_app_id/voice_template_id)",
            )
        try:
            from tencentcloud.common import credential
            from tencentcloud.vms.v20200902 import models as vms_models
            from tencentcloud.vms.v20200902 import vms_client
        except ImportError as exc:
            return GatewayResult(
                channel=self.channel,
                provider="tencent",
                phone=phone,
                content=content,
                status="error",
                code="SDK_MISSING",
                message=f"未安装腾讯云 SDK（pip install tencentcloud-sdk-python）: {exc}",
            )
        try:
            cred = credential.Credential(settings.voice_api_key, settings.voice_api_secret)
            client = vms_client.VmsClient(cred, settings.tencent_region)
            req = vms_models.SendTtsVoiceRequest()
            req.TemplateId = settings.voice_template_id
            req.CalledNumber = phone
            req.VoiceSdkAppid = settings.voice_app_id
            req.TemplateParam = [content or ""]  # 模板变量数组，按模板定义顺序
            resp = client.SendTtsVoice(req)
            st = getattr(resp, "SendStatus", None)
            raw = _safe_serialize(resp)
            if st and getattr(st, "Code", None) == "Ok":
                return GatewayResult(
                    channel=self.channel,
                    provider="tencent",
                    phone=phone,
                    content=content,
                    status="sent",
                    code=st.Code,
                    message=getattr(st, "Message", ""),
                    biz_id=getattr(st, "CallId", None),
                    request_id=getattr(st, "CallId", None),
                    raw=raw,
                )
            return GatewayResult(
                channel=self.channel,
                provider="tencent",
                phone=phone,
                content=content,
                status="failed",
                code=getattr(st, "Code", "UNKNOWN"),
                message=getattr(st, "Message", ""),
                raw=raw,
            )
        except Exception as exc:
            return GatewayResult(
                channel=self.channel,
                provider="tencent",
                phone=phone,
                content=content,
                status="error",
                code="TENCENT_ERR",
                message=f"腾讯云语音调用失败: {exc}",
            )


def _safe_serialize(resp) -> dict:
    """腾讯云响应模型 → dict；失败回退为字符串，避免序列化异常影响落库。"""
    try:
        return resp._serialize()
    except Exception:
        try:
            return json.loads(resp.to_json_string())
        except Exception:
            return {"raw": str(resp)}


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
