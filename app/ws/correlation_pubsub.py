"""跨设备共因事件组实时推送：Redis Pub/Sub 桥接。

关联计算可能运行在**独立 systemd 进程**（snapshot_job 每日定时）或 **API 进程**
（手动触发 ``POST /correlations/run``），而 WebSocket 客户端只连在 API 进程。因此采用
Redis 频道 ``ws:correlation`` 作为跨进程桥：

- 计算进程把"新增跨设备共因" ``publish`` 到 Redis；
- API 进程常驻**订阅线程**收到后，转发至内存 WebSocket 频道
  （``corr:global`` / ``corr:project:N``），由 ``/ws/correlation`` 端点下发给前端。

指纹去重：同一共因事件（project + 空间范围 + 起始时间）7 天内只推送一次，
避免每日重算反复轰炸。计算进程与 API 进程共用同一 Redis，故无论哪侧计算，
前端都能经订阅线程收到。
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from app.config import settings
from app.core.redis import get_redis_client
from app.ws import bridge

logger = logging.getLogger("rail_monitor.ws.correlation")

REDIS_CHANNEL = "ws:correlation"
# 指纹去重 TTL 改由配置 ``settings.correlation_fp_ttl_seconds`` 驱动（默认 7 天），
# 便于按业务节奏调优（见 app/config.py）。此处保留常量名仅为兼容可能的外部引用。
FP_TTL_SECONDS = settings.correlation_fp_ttl_seconds


def _fingerprint(project_id: Any, spatial_type: str, scope_key: str, started_at: Any) -> str:
    sa = started_at.isoformat() if started_at else "na"
    return f"corr:{project_id}:{spatial_type}:{scope_key}:{sa}"


def publish_new_cross_device_groups(groups: list[Any]) -> int:
    """把"新增跨设备共因事件组"发布到 Redis 频道（按指纹去重）。

    入参为 ``CorrelatedEventGroup`` ORM 行（已 commit，``id``/``to_dict`` 可用）。
    返回本次实际发布的条数。任何异常均被吞掉，不阻断关联计算主流程。
    """
    published = 0
    try:
        r = get_redis_client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("关联事件 WS 发布跳过（Redis 不可用）: %s", exc)
        return 0

    for g in groups:
        if not getattr(g, "is_cross_device", False):
            continue
        fp = _fingerprint(g.project_id, g.spatial_type, g.scope_key, g.started_at)
        key = f"correlation:pushed:{fp}"
        try:
            # 去重开关关闭（调试/重放）或指纹未命中 → 推送
            if settings.correlation_dedup_enabled and r.exists(key):
                continue
            ws_payload = {
                "type": "correlation",
                "action": "new_cross_device",
                "data": g.to_dict(),
            }
            channels = ["corr:global"]
            if g.project_id:
                channels.append(f"corr:project:{g.project_id}")
            wrapper = {"ws_channels": channels, "payload": ws_payload}
            r.publish(REDIS_CHANNEL, json.dumps(wrapper, ensure_ascii=False, default=str))
            r.set(key, "1", ex=settings.correlation_fp_ttl_seconds)
            published += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("关联事件 WS 发布单条失败(已忽略): %s", exc)
    if published:
        logger.info("关联事件 WS 发布 %d 条跨设备共因", published)
    return published


def _subscriber_loop(stop_event: threading.Event) -> None:
    """API 进程常驻订阅循环：收到 Redis 消息即转发至 WS 频道。"""
    while not stop_event.is_set():
        try:
            r = get_redis_client()
            pubsub = r.pubsub()
            pubsub.subscribe(REDIS_CHANNEL)
            logger.info("关联事件 WS 订阅线程已启动 channel=%s", REDIS_CHANNEL)
            while not stop_event.is_set():
                msg = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg is None:
                    continue
                if msg.get("type") != "message":
                    continue
                try:
                    m = json.loads(msg["data"])
                    payload = m.get("payload")
                    if not payload:
                        continue
                    for ch in m.get("ws_channels", ["corr:global"]):
                        bridge.emit(ch, payload)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("关联事件 WS 转发失败: %s", exc)
            try:
                pubsub.close()
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("关联事件 WS 订阅断开，5s 后重试: %s", exc)
            if stop_event.wait(5):
                break


def start_correlation_subscriber() -> threading.Event:
    """启动 API 进程常驻订阅线程，返回停止事件（用于优雅关闭）。"""
    stop = threading.Event()
    t = threading.Thread(target=_subscriber_loop, args=(stop,), daemon=True, name="corr-ws-sub")
    t.start()
    return stop
