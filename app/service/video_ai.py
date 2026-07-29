"""视频 AI 异常识别（深化⑧ · 推理服务接入就绪）。

平台自身**不做推理**：异常识别由外部 AI 盒子 / 推理服务完成，并经
``POST /videos/events/ingest`` 回推结构化事件（见 ``app/api/v1/videos.py``）。

本模块提供"主动下发分析任务 / 查询分析结果"的接口契约：
- ``video_ai_enabled=False``：返回 ``pending_capability``，提示能力未启用。
- ``video_ai_enabled=True`` 且配置了 ``video_ai_endpoint``：调用外部推理服务，
  成功返回 ``status=done`` + ``findings``（含类型/置信度/标签/可选 bbox）；
  调用失败/超时则优雅降级为 ``not_implemented`` 并附带错误原因（不抛异常影响主流程）。
- ``video_ai_enabled=True`` 但无 ``video_ai_endpoint``：返回 ``not_implemented``，
  避免前端误判为成功。

能力清单（``VIDEO_AI_CAPABILITIES``）来自 ``app.schema.video``，与回推事件类型对齐，
为单一事实来源。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError

from app.config import settings
from app.schema.video import (
    VIDEO_AI_CAPABILITIES,
    VIDEO_AI_CAPABILITY_LABELS,
    VIDEO_AI_CAPABILITY_TYPES,
)

# 对外暴露的能力清单（与 schema 保持一致）
EXPECTED_CAPABILITIES = list(VIDEO_AI_CAPABILITY_TYPES)


def _normalize_finding(item: Any) -> dict:
    """将推理服务返回的单个 finding 归一化为标准结构。"""
    if not isinstance(item, dict):
        return {"type": str(item), "confidence": None, "label": str(item)}
    ftype = str(item.get("type") or item.get("event_type") or "other")
    conf = item.get("confidence")
    try:
        conf = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        conf = None
    return {
        "type": ftype,
        "label": item.get("label") or VIDEO_AI_CAPABILITY_LABELS.get(ftype, ftype),
        "confidence": conf,
        "bbox": item.get("bbox"),
    }


def _call_inference(payload: dict, endpoint: str, timeout: float) -> dict:
    """调用外部推理服务，返回解析后的响应 dict；任何异常向上抛出由 analyze 兜底。"""
    body = json.dumps({"payload": payload}).encode("utf-8")
    req = urllib_request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def analyze(payload: dict) -> dict:
    """对指定通道 / 帧发起异常识别分析。

    参数 payload（示例）：``{"channel_no": "CAM-01", "frame_url": "...", "model": "default"}``。
    返回结构随能力就绪状态变化；``capabilities`` 始终返回，便于前端渲染分析选项。
    """
    base = {
        "requested": payload,
        "capabilities": list(VIDEO_AI_CAPABILITIES),
        "expected_capabilities": EXPECTED_CAPABILITIES,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    if not settings.video_ai_enabled:
        return {
            **base,
            "status": "pending_capability",
            "message": (
                "视频 AI 异常识别能力尚未启用（video_ai_enabled=false）。"
                "接口契约已就绪，待外部推理服务接入后经 /videos/events/ingest 回推事件。"
            ),
        }

    endpoint = settings.video_ai_endpoint
    if not endpoint:
        return {
            **base,
            "status": "not_implemented",
            "message": "推理服务接入尚未实现（video_ai_enabled=true 但未配置 video_ai_endpoint）。",
        }

    # 调用外部推理服务；失败/超时优雅降级，不阻断主流程。
    try:
        resp = _call_inference(payload, endpoint, settings.video_ai_timeout_seconds)
        findings = [_normalize_finding(f) for f in (resp.get("findings") or [])]
        return {
            **base,
            "status": "done",
            "model": resp.get("model"),
            "findings": findings,
            "message": f"推理完成，共识别 {len(findings)} 项异常。",
        }
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        return {
            **base,
            "status": "not_implemented",
            "message": f"推理服务调用失败，已降级为占位：{exc}",
        }
