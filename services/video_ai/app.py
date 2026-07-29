"""视频 AI 参考推理服务（FastAPI）。

契约（与平台 ``app.service.video_ai._call_inference`` 对齐）：
- 平台下发：``POST {VIDEO_AI_ENDPOINT}``，body = ``{"payload": {channel_no, frame_url|frame_b64|demo, model}}``
- 本服务返回：``{"model": "<名称>", "findings": [{"type","label","confidence","bbox"}]}``

启动：``python -m uvicorn services.video_ai.app:app --host 0.0.0.0 --port 8900``
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request

from .detector import CAPABILITIES, analyze_payload

app = FastAPI(
    title="Rail Monitor Video AI Inference Service",
    description="涉铁工程视频 AI 参考推理服务（可替换真实模型）",
    version="1.0.0",
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/capabilities")
def capabilities() -> dict:
    return {"model": "rail-reference-detector-v1", "capabilities": CAPABILITIES}


@app.post("/infer")
@app.post("/")
async def infer(req: Request) -> dict:
    """接收平台下发分析任务，返回结构化 findings。"""
    try:
        body = await req.json()
    except Exception:
        return {"model": "rail-reference-detector-v1", "findings": []}
    payload = body.get("payload", body) if isinstance(body, dict) else {}
    return analyze_payload(payload)


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("VIDEO_AI_PORT", "8900"))
    uvicorn.run("services.video_ai.app:app", host="0.0.0.0", port=port)
