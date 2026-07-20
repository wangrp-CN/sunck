"""阶段1 设备模拟器：模拟 3 类设备上行上报 + 接收平台下行指令。

用于联调与演示，不依赖真实硬件即可跑通 M1 端到端闭环：
- 人机定位(LOC-001)：沿巡逻路径移动，周期性「侵入」电子围栏（验证 M1② 围栏侵入告警）
- 大机防侵限(AI-001)：周期性上报 A 防区侵入（接口 3）+ 持续上报坐标（供间距判定基准）
- 列车接近(TA-001)：周期性上报列车接近（接口 5）
- 订阅 device/{type}/{no}/down 与 device/{type}/down：打印平台下发指令（验证 M1③ 指令可达设备）

报文格式与 app/mqtt/protocol.parse_up 严格对齐（见 --self-check 离线自检）。

用法（rail_monitor 目录下）：
    .venv/bin/python scripts/device_simulator.py            # 持续运行
    .venv/bin/python scripts/device_simulator.py --once     # 仅发一轮后退出（快速自测）
    .venv/bin/python scripts/device_simulator.py --interval 2
    .venv/bin/python scripts/device_simulator.py --self-check   # 离线校验报文合规性（不连 broker）
"""

import argparse
import json
import logging
import os
import sys
import time

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from paho.mqtt.client import CallbackAPIVersion, Client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("simulator")

BROKER = os.getenv("MQTT_BROKER", "127.0.0.1")
PORT = int(os.getenv("MQTT_PORT", "1883"))

# 设备编号（须与 seed_demo 一致，服务端才能解析归属项目）
LOC_NO, AI_NO, TA_NO = "LOC-001", "AI-001", "TA-001"

# 定位设备巡逻路径（WGS-84）：东侧起点 → 逐步侵入围栏中心 → 西侧撤出 → 绕回
# 围栏约 x∈[121.4995,121.5005], y∈[31.2195,31.2205]（中心 121.5000,31.2200）
LOCATE_PATH = [
    (121.5030, 31.2200),  # 围栏外·东
    (121.5015, 31.2200),  # 围栏外·东侧近界
    (121.5002, 31.2200),  # 围栏内
    (121.5000, 31.2200),  # 围栏中心
    (121.4998, 31.2200),  # 围栏内·紧邻大机(触发间距)
    (121.4997, 31.2200),  # 围栏内·紧邻大机
    (121.4990, 31.2200),  # 围栏外·西
    (121.5010, 31.2202),  # 围栏外·东北
]

# 大机固定坐标（紧邻围栏西侧，用于间距演示；与 seed_demo 一致）
AI_LNG, AI_LAT = 121.4996, 31.2200


# ---------------------------------------------------------------------------
# 报文构造（与协议层 parse_up 严格对齐，self-check 与持续上报共用）
# ---------------------------------------------------------------------------
def locate_payload(idx: int) -> dict:
    lng, lat = LOCATE_PATH[idx % len(LOCATE_PATH)]
    return {
        "device_no": LOC_NO,
        "longitude": lng,
        "latitude": lat,
        "accuracy": 4.5,
        "speed": 1.2,
        "bearing": 270,
        "status": "在线",
        "timestamp": int(time.time()),
    }


def anti_intrusion_payload(idx: int) -> dict:
    p = {
        "device_no": AI_NO,
        "longitude": AI_LNG,
        "latitude": AI_LAT,
        "status": "在线",
        "timestamp": int(time.time()),
    }
    # 每 5 轮上报一次 A 防区侵入（接口 3）
    if idx % 5 == 0:
        p.update(
            {
                "alarm_status": "告警开始",
                "alarm_info": "A 防区限界侵入",
                "image": "http://minio.example/ai/A.jpg",
                "video": "http://minio.example/ai/A.mp4",
            }
        )
    else:
        p["alarm_status"] = "正常"
    return p


def train_approach_payload(idx: int) -> dict:
    p = {
        "device_no": TA_NO,
        "lane": "上行 I 道",
        "direction": "来车方向：上行",
        "speed": 118.0,
        "status": "在线",
        "timestamp": int(time.time()),
    }
    # 每 6 轮上报一次列车接近（接口 5）
    if idx % 6 == 0:
        p.update({"alarm_status": "告警开始", "alarm_info": "上行列车接近，限速预警"})
    else:
        p["alarm_status"] = "正常"
    return p


def _pub(cli: Client, topic: str, payload: dict) -> None:
    cli.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1)


def on_connect(cli: Client, userdata, flags, reason_code, properties=None) -> None:
    logger.info("模拟器已连接 Broker；订阅下行指令主题")
    cli.subscribe("device/+/+/down", qos=1)
    cli.subscribe("device/+/down", qos=1)


def on_message(cli: Client, userdata, msg) -> None:
    # 平台下发的指令（接口 2/4/6）到达设备侧
    try:
        payload = msg.payload.decode("utf-8")
    except Exception:
        payload = str(msg.payload)
    logger.info("[下行指令→设备] topic=%s payload=%s", msg.topic, payload)


def publish_round(cli: Client, idx: int) -> None:
    _pub(cli, "device/locate/up", locate_payload(idx))
    _pub(cli, "device/anti_intrusion/up", anti_intrusion_payload(idx))
    _pub(cli, "device/train_approach/up", train_approach_payload(idx))
    lng, lat = LOCATE_PATH[idx % len(LOCATE_PATH)]
    logger.info("第 %d 轮上报完成（定位 %.4f,%.4f）", idx, lng, lat)


def self_check() -> int:
    """离线校验三份报文能否被协议层正确解析（不连 broker）。"""
    try:
        from app.core.constants import parse_up_topic  # noqa: E402
        from app.mqtt.protocol import ProtocolError, parse_up  # noqa: E402
    except Exception as exc:  # noqa: BLE001
        logger.error("无法导入协议层（请在有依赖的 venv 中运行）: %s", exc)
        return 2

    cases = [
        ("device/locate/up", "locate", locate_payload(0)),
        ("device/anti_intrusion/up", "anti_intrusion", anti_intrusion_payload(0)),
        ("device/train_approach/up", "train_approach", train_approach_payload(0)),
    ]
    ok = True
    for topic, expected, payload in cases:
        dtype = parse_up_topic(topic)
        topic_ok = dtype == expected
        parse_ok = False
        err = ""
        try:
            parsed = parse_up(expected, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            parse_ok = parsed.get("device_no") == payload["device_no"] and parsed.get(
                "status"
            ) == payload.get("status")
            if expected == "locate":
                parse_ok = (
                    parse_ok
                    and parsed["longitude"] == payload["longitude"]
                    and parsed["latitude"] == payload["latitude"]
                )
            else:
                parse_ok = parse_ok and parsed.get("alarm_status") == payload.get("alarm_status")
        except ProtocolError as exc:
            err = str(exc)
        mark = "✅" if (topic_ok and parse_ok) else "❌"
        if not (topic_ok and parse_ok):
            ok = False
        logger.info(
            "%s topic=%s → device_type=%s | parse device_no=%s%s",
            mark,
            topic,
            dtype,
            payload["device_no"],
            f" | 错误: {err}" if err else "",
        )
    logger.info("报文自检结果：%s", "全部通过 ✅" if ok else "存在失败 ❌")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="阶段1 设备模拟器")
    ap.add_argument("--broker", default=BROKER)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--interval", type=float, default=3.0, help="上报间隔(秒)")
    ap.add_argument("--once", action="store_true", help="仅发一轮后退出")
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="离线校验模拟器报文能否被协议层正确解析（不连 broker）",
    )
    args = ap.parse_args()

    if args.self_check:
        sys.exit(self_check())

    cli = Client(callback_api_version=CallbackAPIVersion.VERSION2)
    cli.on_connect = on_connect
    cli.on_message = on_message
    cli.connect(host=args.broker, port=args.port, keepalive=60)
    cli.loop_start()

    logger.info("设备模拟器启动（broker=%s:%s）", args.broker, args.port)
    idx = 0
    try:
        if args.once:
            publish_round(cli, idx)
            time.sleep(0.5)
            return
        while True:
            publish_round(cli, idx)
            idx += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("模拟器停止")
    finally:
        cli.loop_stop()


if __name__ == "__main__":
    main()
