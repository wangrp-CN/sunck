"""阶段3 千台设备 MQTT 上行洪泛器（与 Locust HTTP 负载配合构成完整压测）。

为什么单独实现而非塞进 Locust User：
- Locust 的 gevent 猴子补丁与 paho-mqtt 的后台线程存在已知冲突；
- 本脚本用原生线程池驱动 N 台虚拟设备，稳定可控，且与 Locust 进程完全解耦。

行为：
- 每台虚拟设备周期性向 device/locate/up 发布位置报文（与 device_simulator 协议对齐）；
- 报文 device_no 取自 seed_stress 登记的 LOC-S00001..；服务端 resolve_device 命中 →
  走完整 ingestion（落库 DeviceLocation + WS 广播），无激活计划则不产生告警；
- 支持 --devices / --interval / --duration 调节规模与时长；
- 结束时打印吞吐摘要，并写入 --out 指定的 JSON（供报告聚合）。

用法：
    .venv/bin/python scripts/mqtt_flood.py --devices 1000 --interval 2 --duration 180 \
        --out /tmp/mqtt_flood.json
"""

import argparse
import json
import os
import sys
import threading
import time
from datetime import datetime

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from paho.mqtt.client import CallbackAPIVersion, Client  # noqa: E402

BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
PORT = int(os.getenv("MQTT_PORT", "1883"))
DEVICE_PREFIX = "LOC-S"

# 设备巡逻基准点（WGS-84，与演示围栏同区，便于后续接规则引擎时触发）
BASE_LNG, BASE_LAT = 121.5000, 31.2200


class _Counter:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.published = 0
        self.errors = 0

    def inc(self, ok: bool = True) -> None:
        with self.lock:
            if ok:
                self.published += 1
            else:
                self.errors += 1


def _make_payload(device_no: str, tick: int) -> dict:
    # 沿基准点做小幅抖动，制造「移动」轨迹
    lng = BASE_LNG + 0.0003 * (tick % 10) / 10.0
    lat = BASE_LAT + 0.0002 * ((tick // 3) % 7) / 7.0
    return {
        "device_no": device_no,
        "longitude": round(lng, 6),
        "latitude": round(lat, 6),
        "accuracy": 4.5,
        "speed": 1.2,
        "bearing": 270,
        "status": "在线",
        "timestamp": int(time.time()),
    }


def _worker(
    shard: list[str],
    interval: float,
    stop: threading.Event,
    counter: _Counter,
    broker: str,
    port: int,
) -> None:
    cli = Client(callback_api_version=CallbackAPIVersion.VERSION2)
    cli.connect(host=broker, port=port, keepalive=60)
    cli.loop_start()
    tick = 0
    try:
        while not stop.is_set():
            # 先发布本分片内全部设备，再统一等待间隔，
            # 使整体速率 ≈ 设备数 / 间隔（而非线程数 / 间隔）
            for no in shard:
                if stop.is_set():
                    break
                try:
                    cli.publish(
                        "device/locate/up",
                        json.dumps(_make_payload(no, tick), ensure_ascii=False),
                        qos=1,
                    )
                    counter.inc(True)
                except Exception:
                    counter.inc(False)
                tick += 1
            if interval > 0 and not stop.is_set():
                time.sleep(interval)
    finally:
        cli.loop_stop()
        cli.disconnect()


def main() -> None:
    ap = argparse.ArgumentParser(description="千台设备 MQTT 上行洪泛器")
    ap.add_argument("--broker", default=BROKER)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--devices", type=int, default=1000, help="虚拟设备数量")
    ap.add_argument("--interval", type=float, default=2.0, help="每台设备上报间隔(秒)")
    ap.add_argument("--duration", type=int, default=180, help="运行时长(秒)")
    ap.add_argument("--threads", type=int, default=20, help="发布线程数")
    ap.add_argument("--out", default="/tmp/mqtt_flood.json", help="吞吐摘要输出路径")
    args = ap.parse_args()

    device_nos = [f"{DEVICE_PREFIX}{i:05d}" for i in range(1, args.devices + 1)]
    n_threads = max(1, min(args.threads, args.devices))
    shard_size = (len(device_nos) + n_threads - 1) // n_threads
    shards = [device_nos[i * shard_size : (i + 1) * shard_size] for i in range(n_threads)]

    counter = _Counter()
    stop = threading.Event()
    threads = [
        threading.Thread(
            target=_worker,
            args=(s, args.interval, stop, counter, args.broker, args.port),
            daemon=True,
        )
        for s in shards
    ]

    print(
        f"[mqtt_flood] starting: devices={args.devices} interval={args.interval}s "
        f"threads={n_threads} duration={args.duration}s"
    )
    start = time.time()
    for t in threads:
        t.start()
    try:
        while time.time() - start < args.duration:
            time.sleep(1)
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5)

    elapsed = time.time() - start
    rate = counter.published / elapsed if elapsed > 0 else 0
    summary = {
        "devices": args.devices,
        "interval_s": args.interval,
        "duration_s": round(elapsed, 1),
        "published": counter.published,
        "errors": counter.errors,
        "rate_msg_per_s": round(rate, 1),
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f"[mqtt_flood] done: {summary}")


if __name__ == "__main__":
    main()
