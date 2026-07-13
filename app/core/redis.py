"""Redis 客户端工厂（懒加载，不在导入时连接）。"""

import redis

from app.config import settings

_pool: redis.ConnectionPool | None = None


def get_redis_client() -> redis.Redis:
    """返回（复用连接池的）Redis 客户端。首次调用时建立连接池。"""
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)
    return redis.Redis(connection_pool=_pool)
