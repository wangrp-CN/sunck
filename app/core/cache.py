"""轻量 HTTP 响应缓存（Redis 支撑）。

用途：监控大屏 / 实时看板类高频只读端点，在 100+ 并发查看者场景下，
同一用户短时间内（TTL 内）重复拉取相同聚合结果会产生大量重复 DB 计算，
成为并发时延的主要来源。以「user_id + 路径 + 查询串」为键做短 TTL 缓存，
把 N 个并发请求折叠为每 TTL 窗口 1 次真实计算。

- 键含 user_id：部门数据隔离天然生效（不同用户不会命中彼此缓存）。
- TTL 短（默认 3s）：监控数据允许秒级陈旧，换取并发下时延与吞吐数量级改善。
- 任何异常（Redis 不可用等）静默降级为「不缓存、直接放行」，不影响主流程。
"""

import hashlib
import json
from typing import Any, Optional

from app.config import settings
from app.core.redis import get_redis_client

RESP_CACHE_TTL = 3  # 秒


def _make_key(user_id: int, path: str, query: str) -> str:
    h = hashlib.md5(f"{user_id}|{path}|{query}".encode("utf-8")).hexdigest()
    return f"resp_cache:{h}"


def get_cached_json(user_id: int, path: str, query: str) -> Optional[dict]:
    """命中返回缓存的响应 dict；未命中 / 异常返回 None。"""
    if not settings.resp_cache_enabled:
        return None
    try:
        raw = get_redis_client().get(_make_key(user_id, path, query))
        if raw:
            return json.loads(raw)
    except Exception:
        return None
    return None


def set_cached_json(user_id: int, path: str, query: str, payload: Any) -> None:
    """写入响应 dict（JSON 序列化，datetime 等按 str 兜底）。异常静默忽略。"""
    if not settings.resp_cache_enabled:
        return
    try:
        get_redis_client().setex(
            _make_key(user_id, path, query),
            RESP_CACHE_TTL,
            json.dumps(payload, ensure_ascii=False, default=str),
        )
    except Exception:
        pass
