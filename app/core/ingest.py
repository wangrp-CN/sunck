"""上行 ingestion 异步调度层（阶段3 待办收敛：解耦 MQTT 接收与落库）。

背景：
- 原 `handlers.on_message` 在 paho 网络线程内**同步**调用 `pipeline.handle_upstream`，
  每条上行开会话/落库/规则判定/告警/提交。千台设备洪泛时单线程串行处理 +
  连接池争用 → 处理线程被拖慢、MQTT 线程阻塞、报文易在 pool_timeout 后落库失败。
- 本模块把「接收」与「处理」解耦：on_message 仅做解析 + 入队（极快，立即 ack），
  由 N 个工作线程并行调用既有 `pipeline.handle_upstream`（逻辑零改动）。

安全保障（不丢数据）：
- 有界队列 `ingest_queue_max`；队列满时**回退同步处理**（背压），不会丢弃报文。
- 未启用（ingest_enabled=False）或未 start() 时，enqueue 直接同步处理，等价于历史行为。
- 关闭时先排空队列再停线程池，尽量不丢在途报文。

注意：worker 线程调用 `handle_upstream` 内部的 WS 推送经 ws.bridge 跨线程投递，
与历史（MQTT 线程推送）行为一致，无回归。
"""

import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.config import settings
from app.core import metrics
from app.core.database import IngestSessionLocal

logger = logging.getLogger("rail_monitor.ingest")

# 单条处理单元： (device_type, parsed)
_Item = tuple

_queue: "queue.Queue[_Item]" = queue.Queue(maxsize=settings.ingest_queue_max)
_executor = None
_stopped = threading.Event()
_started = False
# 处理函数（默认懒加载为 pipeline.handle_upstream，测试可 set_processor 注入 mock）
_processor = None
_lock = threading.Lock()


def set_processor(func) -> None:
    """覆盖单条处理函数（主要用于测试注入 mock，避免依赖 DB/Redis）。"""
    global _processor
    _processor = func


def _resolve_processor():
    global _processor
    if _processor is None:
        from app.core.database import IngestSessionLocal
        from app.service import pipeline

        def _default(dtype, parsed, db=None, autocommit=True):
            # 走 ingestion 独立连接池，与 HTTP API 流量隔离（维度⑥）
            return pipeline.handle_upstream(
                dtype, parsed, db=db, autocommit=autocommit, sessionmaker_factory=IngestSessionLocal
            )

        _processor = _default
    return _processor


def _run(item: _Item) -> None:
    """单条处理（inline 回退 / stop 排空用，逐条独立会话、自动提交）。"""
    dtype, parsed = item
    start = time.perf_counter()
    try:
        _resolve_processor()(dtype, parsed)
        metrics.INGEST_PROCESSED_TOTAL.inc()
    except Exception:  # noqa: BLE001
        metrics.INGEST_ERRORS_TOTAL.inc()
        logger.exception("ingest worker 处理失败 %s/%s", dtype, parsed.get("device_no"))
    finally:
        metrics.INGEST_PROCESS_LATENCY.observe(time.perf_counter() - start)
        metrics.INGEST_QUEUE_SIZE.set(_queue.qsize())


def _flush_batch(items: list[_Item]) -> None:
    """批量处理：单会话累积落库，一次性 commit，commit 后再推送 WS（不丢数据）。

    - 正常：一条 IngestSessionLocal 会话处理整批，仅一次 db.commit()。
    - 失败：回滚并回退为逐条处理（与历史行为一致），保证在途报文不丢。
    - 推送统一在批量 commit 之后，避免客户端早于落库看到位置/告警。
    """
    if not items:
        return
    proc = _resolve_processor()
    db = IngestSessionLocal()
    ok = 0
    msgs: list[tuple[str, dict]] = []
    try:
        for dtype, parsed in items:
            t0 = time.perf_counter()
            try:
                summary = proc(dtype, parsed, db=db, autocommit=False)
            finally:
                metrics.INGEST_PROCESS_LATENCY.observe(time.perf_counter() - t0)
            ok += 1
            if isinstance(summary, dict):
                msgs.extend(summary.get("messages", []))
        db.commit()
        metrics.INGEST_PROCESSED_TOTAL.inc(ok)
        # commit 后再推送，保证客户端所见即已落库
        from app.ws import bridge

        for ch, m in msgs:
            bridge.emit(ch, m)
    except Exception:  # noqa: BLE001
        db.rollback()
        metrics.INGEST_ERRORS_TOTAL.inc()
        logger.exception("ingest 批处理失败，回退逐条处理 %d 条", len(items))
        for dtype, parsed in items:
            _run((dtype, parsed))
    finally:
        db.close()
        metrics.INGEST_QUEUE_SIZE.set(_queue.qsize())


def _consume() -> None:
    """工作线程：攒批处理，凑满 batch_size 或等待 batch_max_wait 秒即 flush。"""
    batch: list[_Item] = []
    batch_start = 0.0
    while not _stopped.is_set():
        try:
            item = _queue.get(timeout=0.5)
        except queue.Empty:
            # 空闲：若有未 flush 的批量，立即落库
            if batch:
                _flush_batch(batch)
                batch = []
                batch_start = 0.0
            continue
        batch.append(item)
        now = time.perf_counter()
        if not batch_start:
            batch_start = now
        if settings.ingest_batch_size > 0 and (
            len(batch) >= settings.ingest_batch_size
            or (now - batch_start) >= settings.ingest_batch_max_wait
        ):
            _flush_batch(batch)
            batch = []
            batch_start = 0.0
    # 退出前排空在途批量
    if batch:
        _flush_batch(batch)


def start() -> None:
    """启动工作线程池。未启用时仅记录，enqueue 会自动回退同步处理。"""
    global _executor, _started
    with _lock:
        if _started:
            return
        _started = True
    if not settings.ingest_enabled:
        logger.info("ingest 未启用（ingest_enabled=False），on_message 将同步处理")
        return
    _stopped.clear()
    _executor = ThreadPoolExecutor(max_workers=settings.ingest_workers, thread_name_prefix="ingest")
    # 每个 worker 一个常驻消费循环
    for _ in range(settings.ingest_workers):
        _executor.submit(_consume)
    logger.info(
        "ingest 工作池已启动：workers=%d queue_max=%d",
        settings.ingest_workers,
        settings.ingest_queue_max,
    )


def stop() -> None:
    """优雅停止：先排空队列（在途报文尽量处理），再停线程池。"""
    global _executor, _started
    with _lock:
        if not _started:
            return
        _started = False
    _stopped.set()
    # 排空在途报文（最多处理 maxsize 条，避免极端情况死循环）
    drained = 0
    limit = settings.ingest_queue_max + 1
    while not _queue.empty() and drained < limit:
        try:
            item = _queue.get_nowait()
        except queue.Empty:
            break
        _run(item)
        drained += 1
    if drained:
        logger.info("ingest 停止前排空在途报文 %d 条", drained)
    if _executor is not None:
        _executor.shutdown(wait=True)
        _executor = None
    logger.info("ingest 工作池已停止")


def enqueue(device_type: str, parsed: dict) -> None:
    """入队一条上行报文；未启用/未启动时同步处理，队列满时回退同步处理。"""
    if not settings.ingest_enabled or not _started:
        metrics.INGEST_INLINE_TOTAL.inc()
        _run((device_type, parsed))
        return
    metrics.INGEST_ENQUEUED_TOTAL.inc()
    item = (device_type, parsed)
    try:
        _queue.put_nowait(item)
        metrics.INGEST_QUEUE_SIZE.set(_queue.qsize())
    except queue.Full:
        # 背压：队列满则同步处理（不丢数据，仅退化吞吐）
        metrics.INGEST_INLINE_TOTAL.inc()
        _run(item)
