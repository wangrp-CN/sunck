"""ingest 异步调度层单测（mock 处理器，无需 PG/Redis/MQTT）。

验证：
- 启用 + start()：报文入队，由 ingest 工作线程并行处理（异步路径）。
- 队列满：回退同步处理（背压，调用线程执行，不丢报文）。
- 未启用 / 未 start()：enqueue 直接同步处理（等价于历史行为）。
- 生命周期：start/stop 不抛异常、stop 排空在途报文。
"""

import queue
import threading

from app.config import settings
from app.core import ingest, metrics


def _reset_module():
    """将 ingest 模块恢复到干净可启动状态。"""
    ingest._stopped.clear()
    ingest._started = False
    ingest._executor = None
    ingest._processor = None
    ingest._queue = queue.Queue(maxsize=settings.ingest_queue_max)


def _fake_collector(records: list):
    """mock 处理器：记录 (device_type, device_no, 线程名)，不触碰 DB。"""

    def _proc(device_type, parsed):
        records.append((device_type, parsed.get("device_no"), threading.current_thread().name))

    return _proc


def test_enqueue_disabled_runs_inline():
    """未启用时 enqueue 同步处理（调用线程执行）。"""
    _reset_module()
    settings.ingest_enabled = False
    records = []
    ingest.set_processor(_fake_collector(records))

    ingest.enqueue("locate", {"device_no": "D1"})

    assert len(records) == 1
    assert records[0][0] == "locate"
    assert records[0][2] == threading.current_thread().name  # 调用线程（非工作线程）
    # 未 start，不应有 enqueued 计数、应有 inline 计数
    assert metrics.INGEST_ENQUEUED_TOTAL._value.get() == 0
    assert metrics.INGEST_INLINE_TOTAL._value.get() >= 1
    settings.ingest_enabled = True


def test_enqueue_async_and_fallback():
    """启用 + start()：小队列触发「入队(异步) + 满则回退同步」双路径，且不丢报文。"""
    _reset_module()
    settings.ingest_enabled = True
    settings.ingest_workers = 2
    ingest._queue = queue.Queue(maxsize=2)  # 故意设小，制造队列满回退

    records = []
    ingest.set_processor(_fake_collector(records))
    ingest.start()

    n = 6
    for i in range(n):
        ingest.enqueue("locate", {"device_no": f"D{i}"})

    # 等待 worker 排空（带超时，避免测试挂死）
    import time

    waited = 0.0
    while len(records) < n and waited < 5.0:
        time.sleep(0.05)
        waited += 0.05

    ingest.stop()

    # 不丢报文：全部处理
    assert len(records) == n, f"期望处理 {n} 条，实得 {len(records)}"
    # 异步路径：至少部分由 ingest 工作线程处理
    worker_runs = [r for r in records if r[2].startswith("ingest")]
    assert len(worker_runs) >= 1, "异步工作线程路径未被执行"
    # 回退路径：队列满时部分在调用线程同步处理
    inline_runs = [r for r in records if not r[2].startswith("ingest")]
    assert len(inline_runs) >= 1, "队列满回退同步路径未被执行"


def test_stop_drains_in_flight():
    """stop() 前排空在途报文，避免丢弃。"""
    _reset_module()
    settings.ingest_enabled = True
    settings.ingest_workers = 1
    ingest._queue = queue.Queue(maxsize=100)

    records = []
    ingest.set_processor(_fake_collector(records))
    ingest.start()

    # 入队一批后立刻停止，worker 可能尚未消费完
    for i in range(10):
        ingest.enqueue("locate", {"device_no": f"X{i}"})
    ingest.stop()

    # 停止后 drained 逻辑应保证在途报文被处理
    assert len(records) == 10, f"stop 应排空在途报文，实得 {len(records)}"


def test_default_processor_uses_ingest_pool():
    """默认处理器应把上行交给 pipeline.handle_upstream 并传入独立连接池 IngestSessionLocal。"""
    _reset_module()
    settings.ingest_enabled = True
    settings.ingest_workers = 1
    ingest._queue = queue.Queue(maxsize=100)

    from app.core.database import IngestSessionLocal
    from app.service import pipeline as pipeline_mod

    captured = {}

    def _recorder(device_type, parsed, **kwargs):
        captured.update(kwargs)

    pipeline_mod.handle_upstream = _recorder  # monkeypatch 真实处理器
    # _processor 保持 None → _resolve_processor 会构建带独立池的默认包装
    ingest.start()
    ingest.enqueue("locate", {"device_no": "D1"})

    import time

    waited = 0.0
    while "sessionmaker_factory" not in captured and waited < 5.0:
        time.sleep(0.05)
        waited += 0.05
    ingest.stop()

    assert "sessionmaker_factory" in captured, "未向 handle_upstream 传递 sessionmaker_factory"
    assert captured["sessionmaker_factory"] is IngestSessionLocal
