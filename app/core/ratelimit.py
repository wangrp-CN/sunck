"""API 限流（基于 Redis 的固定窗口计数）。

设计要点：
- 按「路径 + 客户端 IP」分桶，避免单端点把全局配额耗尽影响其他端点。
- Redis 不可用时**放行（fail-open）**，不阻断业务；仅失去限流保护。
- 默认对全站按 IP 限流，登录/验证码端点收紧（防爆破/防刷）。
- 受 settings.rate_limit_enabled 总开关控制（测试/特殊场景可关）。
"""

import time

from app.config import settings
from app.core.redis import get_redis_client

# 豁免路径：探活、自监控、文档、WebSocket、静态资源（带扩展名）不参与限流。
_EXEMPT_EXACT = {"/health", "/metrics", "/docs", "/redoc", "/openapi.json"}


def _client_ip(request) -> str:
    """取客户端真实 IP：优先 X-Forwarded-For（nginx 透传），回退直连地址。"""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _bucket_key(path: str, ip: str, window: int) -> str:
    slot = int(time.time()) // window
    return f"ratelimit:{path}:{ip}:{slot}"


def is_allowed(path: str, ip: str, limit: int, window: int) -> tuple[bool, int]:
    """固定窗口限流判定。

    返回 (是否放行, 窗口内剩余可用次数)。Redis 异常时放行并剩全额。
    """
    try:
        r = get_redis_client()
        bucket = _bucket_key(path, ip, window)
        count = r.incr(bucket)
        if count == 1:
            r.expire(bucket, window + 1)
        return count <= limit, max(limit - count, 0)
    except Exception:
        # 限流组件故障不应阻断业务（fail-open）
        return True, limit


def decide_limit(path: str) -> tuple[int, str]:
    """根据路径返回 (限额, 作用域标签)。"""
    if path == "/api/v1/auth/login":
        return settings.rate_limit_login, "login"
    if path == "/api/v1/auth/captcha":
        return settings.rate_limit_captcha, "captcha"
    return settings.rate_limit_default, "global"


def is_exempt(path: str) -> bool:
    """是否豁免限流。"""
    if path in _EXEMPT_EXACT:
        return True
    if path.startswith("/ws"):
        return True
    # 静态资源（带扩展名，如 /assets/index-xxxx.js、/favicon.ico）
    if "." in path.split("?")[0]:
        return True
    return False
