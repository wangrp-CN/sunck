"""应用入口：装配 FastAPI 应用并暴露启动入口。

职责：
- 配置日志、CORS、全局异常处理。
- 挂载 API 路由（/api）与 WebSocket 路由（/ws）。
- 启动/停止 MQTT 客户端（连接失败不影响应用启动）。
- 提供 /health（健康检查）、/metrics（Prometheus 指标）、/docs。

运行：
    python app/main.py            # 直接启动（__main__ 分支）
    uvicorn app.main:app --reload # 开发热重载
"""

import os
import sys

# 确保项目根目录（含 app/ 的那一层）始终在 sys.path 中，
# 兼容从任意 cwd 或以 python app/main.py 方式启动。
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import asyncio
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# 确保 ORM 元数据注册（供 Alembic 与运行时使用）
import app.model  # noqa: E402,F401
from app.api import api_router
from app.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.ingest import start as ingest_start
from app.core.ingest import stop as ingest_stop
from app.core.logging import configure_logging
from app.core.metrics import HTTP_REQUEST_COUNT, HTTP_REQUEST_LATENCY
from app.mqtt import client as mqtt_client
from app.ws import bridge
from app.ws.router import router as ws_router

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：绑定事件循环到 WS 桥接（供 MQTT 线程跨线程推送）
    bridge.set_event_loop(asyncio.get_running_loop())
    # 启动：尝试连接 MQTT（失败仅告警，不阻断应用）
    try:
        mqtt_client.connect()
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger("rail_monitor").warning("MQTT 连接失败，实时链路暂不可用: %s", exc)
    # 启动：上行 ingestion 异步工作池（解耦接收与落库）
    try:
        ingest_start()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("rail_monitor").warning("ingest 工作池启动失败: %s", exc)
    yield
    # 关闭
    try:
        ingest_stop()
    except Exception:  # noqa: BLE001
        pass
    try:
        mqtt_client.get_client().loop_stop()
    except Exception:
        pass


app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)
app.include_router(api_router)
app.include_router(ws_router)


class MetricsMiddleware(BaseHTTPMiddleware):
    """统计 HTTP 请求数与时延，排除自监控端点避免污染指标。"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # 跳过 /metrics、/health 自身的抓取，避免自监控污染
        if path in ("/metrics", "/health"):
            return await call_next(request)
        method = request.method
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - start
            HTTP_REQUEST_COUNT.labels(method=method, path=path, status=status).inc()
            HTTP_REQUEST_LATENCY.labels(method=method, path=path).observe(elapsed)


app.add_middleware(MetricsMiddleware)


@app.get("/health", tags=["系统"])
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.get("/metrics", tags=["系统"])
def metrics():
    from fastapi.responses import Response

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
