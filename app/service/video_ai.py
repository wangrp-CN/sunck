"""视频 AI 异常识别（接口预留，待能力接入 · #④-3）。

平台自身**不做推理**：异常识别由外部 AI 盒子 / 推理服务完成，并经
``POST /videos/events/ingest`` 回推结构化事件（见 ``app/api/v1/videos.py``）。

本模块预留"主动下发分析任务 / 查询分析结果"的接口契约：能力就绪前
``analyze`` 固定返回 ``status=pending_capability``，便于前端 / 编排层提前对接，
能力接入后只需替换函数体为真实推理服务调用（HTTP / gRPC）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.config import settings

# 预期可识别的异常类型（契约，供前端渲染分析选项 / 推理服务对齐）
EXPECTED_CAPABILITIES = [
    "intrusion",  # 侵入/越界
    "fire_smoke",  # 烟火
    "helmet_missing",  # 未戴安全帽
    "idle_person",  # 长时间滞留
    "region_breach",  # 区域入侵
]


def analyze(payload: dict) -> dict:
    """对指定通道 / 帧发起异常识别分析（接口预留）。

    参数 payload（示例）：``{"channel_no": "CAM-01", "frame_url": "...", "model": "default"}``。
    能力就绪前返回占位；``video_ai_enabled`` 为 ``True`` 但推理未实现时同样返回占位，
    并标注 ``not_implemented``，避免前端误判为成功。
    """
    if not settings.video_ai_enabled:
        return {
            "status": "pending_capability",
            "message": (
                "视频 AI 异常识别能力尚未启用（video_ai_enabled=false）。"
                "接口契约已就绪，待外部推理服务接入后经 /videos/events/ingest 回推事件。"
            ),
            "requested": payload,
            "expected_capabilities": EXPECTED_CAPABILITIES,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    # TODO(④-3): 接入真实推理服务——调用 AI 盒子 / 推理集群，转发 payload 并返回
    # {"status": "done", "findings": [...], "confidence": float, ...}。
    return {
        "status": "not_implemented",
        "message": "推理服务接入尚未实现（video_ai_enabled=true 但能力未就绪）。",
        "requested": payload,
        "expected_capabilities": EXPECTED_CAPABILITIES,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
