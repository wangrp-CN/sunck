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
from fastapi.responses import JSONResponse
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
from app.core.ratelimit import _client_ip, decide_limit, is_allowed, is_exempt
from app.core.responses import ApiResponse
from app.mqtt import client as mqtt_client
from app.ws import bridge
from app.ws.router import router as ws_router

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：生产环境安全护栏（不安全默认值直接拒绝启动，fail-closed）
    from app.config import assert_production_safe

    assert_production_safe()

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


@app.get("/ws/{path:path}", include_in_schema=False, tags=["WebSocket"])
def ws_http_guard(path: str) -> JSONResponse:
    """WebSocket 实时通道的 HTTP 兜底。

    `/ws/alarm` 等仅注册为 WebSocket 路由；当收到**未带 Upgrade 的裸 HTTP 请求**
    （如监控探针、反向代理未透传 Upgrade、手动 curl）时，Starlette 会回默认
    404 `detail="Not Found"`，前端/控制台据此报「message: Not Found」令人困惑。
    此处显式返回 426 Upgrade Required 与明确指引，消除歧义；真正的 WebSocket
    握手（Upgrade 请求）仍由 ws_router 的 `@router.websocket` 处理，互不干扰。
    """
    body = ApiResponse.fail(
        "该端点为 WebSocket 实时通道，请使用 WebSocket 协议连接"
        "（例如 ws://<host>/ws/alarm?token=<JWT>）",
        code=426,
    )
    return JSONResponse(status_code=426, content=body.model_dump())


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


class RateLimitMiddleware(BaseHTTPMiddleware):
    """API 限流（防爆破/防刷）：按「路径+客户端IP」固定窗口计数。

    豁免 /health、/metrics、/docs、/openapi.json、/ws 与静态资源；
    登录/验证码端点走更严配额。Redis 不可用时放行（fail-open）。
    """

    async def dispatch(self, request: Request, call_next):
        if not settings.rate_limit_enabled:
            return await call_next(request)
        path = request.url.path
        if is_exempt(path):
            return await call_next(request)
        limit, _scope = decide_limit(path)
        allowed, _remaining = is_allowed(
            path, _client_ip(request), limit, settings.rate_limit_window_seconds
        )
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"code": 429, "message": "请求过于频繁，请稍后再试", "data": None},
            )
        return await call_next(request)


app.add_middleware(RateLimitMiddleware)

# 操作审计中间件：写请求自动落审计日志（受 settings.audit_enabled 总开关控制）
from app.core.audit import AuditMiddleware  # noqa: E402

app.add_middleware(AuditMiddleware)


@app.get("/health", tags=["系统"])
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


@app.get("/metrics", tags=["系统"])
def metrics():
    from fastapi.responses import Response

    # 抓取前刷新 DB 连接池实时指标（饱和度/容量/借出计数）。
    try:
        from app.core.metrics import update_pool_metrics

        update_pool_metrics()
    except Exception:  # noqa: BLE001
        pass
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
