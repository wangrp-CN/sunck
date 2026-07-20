"""实时链路端到端联调（阶段1 → 联调里程碑）。

为什么需要它：
- 既有 tests/test_realtime.py 仅 monkeypatch `bridge.emit` 后直接调用
  `pipeline.handle_upstream`，**完全绕过 MQTT broker**，不是真正的链路联调。
- 本脚本启动「隔离」原生服务（临时 mosquitto + 真实 FastAPI 进程），
  用真实 MQTT 报文跑通整条链路，验证下列闭环：

    设备/模拟器 --MQTT(device/{type}/up)--> 平台 on_message
      --> protocol.parse_up --> pipeline.handle_upstream
        --> location_service 落库 DeviceLocation
        --> rule_engine 判定（围栏侵入 / 大机间距过近 / 列车·大机自报）
        --> alarm_service 去重创建 Alarm
        --> ws.bridge.emit --> WebSocket(/ws/alarm) 推送
    平台 POST /api/v1/realtime/command
      --> protocol.build_command --> mqtt.publish(device/{type}/{no}/down)
      --> 设备侧订阅收到下行指令

运行：
    .venv/bin/python scripts/realtime_integration.py        # 人工联调，打印报告
    RUN_E2E=1 pytest -m integration                    # CI 中选跑

设计要点（隔离、可复现、可清理）：
- 临时 broker 监听 127.0.0.1:1889（anonymous），与宿主 1883 互不干扰；
  宿主若已起 8000 服务，其连的是 1883，不会收到本脚本的报文，零串扰。
- 应用子进程通过环境变量 MQTT_PORT=1889 指向临时 broker。
- 所有测试数据以 ITG- 前缀唯一标记，teardown 按 device_no/project 精确清理。
- 告警去重键（Redis）按 ITG-* 前缀预先/事后清理，避免 300s 窗口污染。
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any

# 让脚本既能被 `python scripts/realtime_integration.py` 直接运行，
# 也能被 tests/test_realtime_integration.py 导入（app 在仓库根可导入）。
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import httpx  # noqa: E402
import websocket  # websocket-client  # noqa: E402
from paho.mqtt.client import CallbackAPIVersion, Client  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.redis import get_redis_client  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.core.constants import (  # noqa: E402
    ALARM_TYPE_DEVICE,
    ALARM_TYPE_DISTANCE,
    ALARM_TYPE_FENCE,
    DEVICE_TYPE_ANTI_INTRUSION,
    DEVICE_TYPE_LOCATE,
    DEVICE_TYPE_TRAIN_APPROACH,
)
from app.model.alarm import Alarm  # noqa: E402
from app.model.device import (  # noqa: E402
    AntiIntrusionDevice,
    LocateDevice,
    TrainApproachDevice,
)
from app.model.fence import ElectronicFence  # noqa: E402
from app.model.job import (  # noqa: E402
    WorkPlan,
    WorkPlanDevice,
    WorkPlanFence,
)
from app.model.project import Project  # noqa: E402
from app.model.realtime import DeviceLocation  # noqa: E402
from app.model.system import User  # noqa: E402

# ---------------------------------------------------------------------------
# 联调常量（唯一前缀，防止与开发库/宿主服务串扰）
# ---------------------------------------------------------------------------
PREFIX = "ITG"
LOC_NO = f"{PREFIX}-LOC-1"
AI_NO = f"{PREFIX}-AI-1"
TA_NO = f"{PREFIX}-TA-1"
FENCE_NAME = f"{PREFIX}-FENCE"
PROJ_NAME = f"{PREFIX}-PROJ"

# 大机固定坐标（紧邻围栏西侧，用于间距演示）；
# 围栏外紧邻点（用于单独验证 distance 不触发 fence）
_AI_LNG, _AI_LAT = 121.4996, 31.2200
_DIST_LNG, _DIST_LAT = 121.4993, 31.2200  # 围栏外(x<121.4995)但距大机≈33m<50m

BROKER_HOST = "127.0.0.1"
BROKER_PORT = 1889
APP_PORT = 8011
APP_BASE = f"http://{BROKER_HOST}:{APP_PORT}"
WS_BASE = f"ws://{BROKER_HOST}:{APP_PORT}/ws/alarm"

# 围栏 WKT（中心 121.5000,31.2200），与 tests/test_realtime.py 一致
_FENCE_WKT = (
    "POLYGON(("
    "121.4995 31.2195, 121.5005 31.2195, "
    "121.5005 31.2205, 121.4995 31.2205, "
    "121.4995 31.2195))"
)


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------
def _wait_port(host: str, port: int, timeout: float = 30.0) -> bool:
    """轮询直到 TCP 端口可连接。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def _log(step: str, ok: bool, detail: str = "") -> dict:
    mark = "✅" if ok else "❌"
    line = f"  {mark} {step}" + (f" — {detail}" if detail else "")
    print(line)
    return {"step": step, "ok": ok, "detail": detail}


# ---------------------------------------------------------------------------
# 隔离 MQTT broker
# ---------------------------------------------------------------------------
@contextmanager
def mosquitto_broker():
    """启动一个临时匿名 mosquitto（端口 1889），退出时清理。"""
    bin_path = shutil.which("mosquitto") or "/opt/homebrew/sbin/mosquitto"
    if not os.path.exists(bin_path):
        raise RuntimeError("未找到 mosquitto 可执行文件，无法启动隔离 broker")
    cfg = os.path.join("/tmp", "realtime_e2e_mqtt.conf")
    with open(cfg, "w", encoding="utf-8") as f:
        f.write(f"listener {BROKER_PORT} {BROKER_HOST}\n")
        f.write("allow_anonymous true\n")
        f.write("log_dest stdout\n")
    proc = subprocess.Popen(
        [bin_path, "-c", cfg],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_port(BROKER_HOST, BROKER_PORT, timeout=15):
            raise RuntimeError("mosquitto 启动后端口不可达")
        yield proc
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------------------
# 真实 FastAPI 进程（uvicorn 子进程，连隔离 broker）
# ---------------------------------------------------------------------------
@contextmanager
def app_server():
    """以 MQTT_PORT=1889 启动 uvicorn 子进程，退出时清理。"""
    env = dict(os.environ)
    env["MQTT_PORT"] = str(BROKER_PORT)
    env["DEBUG"] = "false"  # 关闭 SQL echo，避免联调日志刷屏
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = _REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    log_path = os.path.join("/tmp", "realtime_e2e_server.log")
    logf = open(log_path, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            BROKER_HOST,
            "--port",
            str(APP_PORT),
        ],
        cwd=_REPO_ROOT,
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
    )
    try:
        if not _wait_port(BROKER_HOST, APP_PORT, timeout=30):
            raise RuntimeError(f"uvicorn 端口 {APP_PORT} 不可达；详见 {log_path}")
        # 等 /health 返回 200
        ready = False
        for _ in range(40):
            try:
                r = httpx.get(f"{APP_BASE}/health", timeout=2)
                if r.status_code == 200:
                    ready = True
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        if not ready:
            raise RuntimeError(f"uvicorn /health 未就绪；详见 {log_path}")
        yield proc
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            logf.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# MQTT 捕获器（模拟设备侧订阅下行指令）
# ---------------------------------------------------------------------------
class MqttCapture:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self.received: list[tuple[str, str]] = []
        self._ev = threading.Event()
        self._cli = Client(callback_api_version=CallbackAPIVersion.VERSION2)
        self._topic: str | None = None

    def connect(self, topic: str) -> None:
        self._topic = topic
        self._cli.on_connect = self._on_connect
        self._cli.on_message = self._on_message
        self._cli.connect(self._host, self._port, keepalive=60)
        self._cli.loop_start()

    def _on_connect(self, cli, u, f, rc, p=None):
        cli.subscribe(self._topic, qos=1)

    def _on_message(self, cli, u, msg) -> None:
        self.received.append((msg.topic, msg.payload.decode("utf-8", "replace")))
        self._ev.set()

    def wait_for(self, predicate, timeout: float = 8.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if any(predicate(t, p) for t, p in self.received):
                return True
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            self._ev.wait(min(0.2, remaining))
        return any(predicate(t, p) for t, p in self.received)

    def close(self) -> None:
        try:
            self._cli.loop_stop()
            self._cli.disconnect()
        except Exception:
            pass


def _publish(host: str, port: int, topic: str, payload: dict) -> None:
    """模拟设备侧上行一条报文。"""
    cli = Client(callback_api_version=CallbackAPIVersion.VERSION2)
    cli.connect(host, port, keepalive=60)
    cli.loop_start()
    try:
        cli.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1)
        time.sleep(0.3)  # 等待 broker 投递 + 平台 on_message 处理
    finally:
        cli.loop_stop()
        cli.disconnect()


def _recv_until(ws, want_types: set[str], max_msgs: int = 6, timeout: float = 12) -> list[dict]:
    """从 WS 收取消息，直到见到全部 want_types 或超时/达上限。"""
    ws.settimeout(timeout)
    got: list[dict] = []
    seen: set[str] = set()
    try:
        while len(seen) < len(want_types) and len(got) < max_msgs:
            raw = ws.recv()
            if raw is None:
                break
            msg = json.loads(raw)
            got.append(msg)
            if msg.get("type") in want_types:
                seen.add(msg["type"])
    except websocket.WebSocketTimeoutException:
        pass
    return got


# ---------------------------------------------------------------------------
# 测试数据
# ---------------------------------------------------------------------------
def _setup_data(db) -> tuple[int, int]:
    """创建 项目 + 围栏 + 三类设备 + 激活作业计划，返回 (project_id, plan_id)。

    注：rule_engine_v2 为「计划感知」，告警仅在存在 is_start=True 且
    status='执行中' 且处于 plan_start/plan_end 时间窗内、且覆盖该设备的
    作业计划时才产生。联调必须创建这样一个激活计划，否则上行不会生成告警。
    """
    proj = Project(name=PROJ_NAME, dept_id=None, status="在建")
    db.add(proj)
    db.flush()
    fence = ElectronicFence(
        project_id=proj.id,
        name=FENCE_NAME,
        fence_type="人员禁区",
        enabled=True,
        geometry_wkt=_FENCE_WKT,
    )
    db.add(fence)
    db.add(LocateDevice(project_id=proj.id, name=f"{PREFIX}-定位", device_no=LOC_NO, status="在线"))
    db.add(
        AntiIntrusionDevice(
            project_id=proj.id,
            name=f"{PREFIX}-大机",
            device_no=AI_NO,
            status="在线",
            longitude=_AI_LNG,
            latitude=_AI_LAT,
        )
    )
    db.add(
        TrainApproachDevice(
            project_id=proj.id, name=f"{PREFIX}-列车", device_no=TA_NO, status="在线"
        )
    )

    # 激活作业计划：覆盖全部三类设备 + 围栏，开启全部触发条件，宽时间窗
    plan = WorkPlan(
        project_id=proj.id,
        name=f"{PREFIX}-PLAN",
        is_start=True,
        status="执行中",
        description="实时链路联调激活计划",
        plan_start=datetime(2026, 1, 1),
        plan_end=datetime(2027, 12, 31),
        rule_json=json.dumps(
            {
                "monitor_target": "person",
                "trigger_conditions": [
                    "fence_intrusion",
                    "distance_too_close",
                    "device_alarm",
                ],
                "time_range": "全天",
                "dwell_time": 0,
            },
            ensure_ascii=False,
        ),
    )
    db.add(plan)
    db.flush()
    for dtype, dno in (
        (DEVICE_TYPE_LOCATE, LOC_NO),
        (DEVICE_TYPE_ANTI_INTRUSION, AI_NO),
        (DEVICE_TYPE_TRAIN_APPROACH, TA_NO),
    ):
        db.add(WorkPlanDevice(plan_id=plan.id, device_type=dtype, device_no=dno))
    db.add(WorkPlanFence(plan_id=plan.id, fence_id=fence.id))
    db.commit()
    return proj.id, plan.id


def _admin_token() -> str:
    db = SessionLocal()
    try:
        u = db.scalar(select(User).where(User.username == "admin", User.is_deleted.is_(False)))
        if u is None:
            raise RuntimeError("开发库缺少 admin 用户（请先执行 seed_rbac.py）")
        return create_access_token(u.id)
    finally:
        db.close()


def _cleanup(plan_id: int | None = None) -> None:
    db = SessionLocal()
    try:
        db.execute(
            delete(DeviceLocation).where(DeviceLocation.device_no.in_([LOC_NO, AI_NO, TA_NO]))
        )
        db.execute(delete(Alarm).where(Alarm.device_no.in_([LOC_NO, AI_NO, TA_NO])))
        db.execute(delete(LocateDevice).where(LocateDevice.device_no == LOC_NO))
        db.execute(delete(AntiIntrusionDevice).where(AntiIntrusionDevice.device_no == AI_NO))
        db.execute(delete(TrainApproachDevice).where(TrainApproachDevice.device_no == TA_NO))
        db.execute(delete(ElectronicFence).where(ElectronicFence.name == FENCE_NAME))
        db.execute(delete(Project).where(Project.name == PROJ_NAME))
        if plan_id is not None:
            db.execute(delete(WorkPlanDevice).where(WorkPlanDevice.plan_id == plan_id))
            db.execute(delete(WorkPlanFence).where(WorkPlanFence.plan_id == plan_id))
            db.execute(delete(WorkPlan).where(WorkPlan.id == plan_id))
        db.commit()
    finally:
        db.close()
    # 清理告警去重键，避免 300s 窗口污染后续运行
    try:
        r = get_redis_client()
        for k in r.keys(f"alarm:dedup:{PREFIX}-*"):
            r.delete(k)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def run_e2e(verbose: bool = True) -> tuple[bool, list[dict]]:
    """执行端到端联调，返回 (是否全部通过, 步骤明细)。"""
    steps: list[dict] = []
    if verbose:
        print("\n=== 实时链路端到端联调 ===\n")

    ws = None
    capture = None
    plan_id: int | None = None
    try:
        # 1) 隔离 broker
        if verbose:
            print("[1] 启动隔离 MQTT broker (:%d)" % BROKER_PORT)
        try:
            with mosquitto_broker() as _broker:
                # 2) 真实应用进程
                if verbose:
                    print("[2] 启动 FastAPI 进程 (:%d，连隔离 broker)" % APP_PORT)
                try:
                    with app_server() as _server:
                        # 3) 准备数据 + 令牌
                        if verbose:
                            print("[3] 准备测试数据（项目/围栏/设备）与鉴权令牌")
                        db = SessionLocal()
                        try:
                            project_id, plan_id = _setup_data(db)
                        finally:
                            db.close()
                        steps.append(
                            _log("创建测试项目/围栏/设备", True, f"project_id={project_id}")
                        )
                        token = _admin_token()

                        # 4) WebSocket 订阅项目频道
                        if verbose:
                            print("[4] 连接 WebSocket 订阅 project:%d 频道" % project_id)
                        ws_url = f"{WS_BASE}?token={token}&project_id={project_id}"
                        try:
                            ws = websocket.create_connection(ws_url, timeout=10)
                        except Exception as exc:  # noqa: BLE001
                            steps.append(_log("WebSocket 连接/鉴权", False, str(exc)))
                            return False, steps
                        # 心跳自检
                        ws.send("ping")
                        pong = ws.recv()
                        ws.settimeout(12)
                        steps.append(_log("WebSocket 鉴权+心跳", pong == "pong", f"recv={pong!r}"))

                        # 4.5) 大机先上报位置，使其进入 latest_locations（间距判定依赖）
                        if verbose:
                            print("[4.5] 大机设备上报位置（供间距判定基准）")
                        _publish(
                            BROKER_HOST,
                            BROKER_PORT,
                            "device/anti_intrusion/up",
                            {
                                "device_no": AI_NO,
                                "status": "在线",
                                "longitude": _AI_LNG,
                                "latitude": _AI_LAT,
                                "alarm_status": "正常",
                                "timestamp": int(time.time()),
                            },
                        )
                        steps.append(_log("大机位置落库(供间距基准)", True))

                        # 5) 上行①：定位设备进入围栏 → 落库 + 围栏侵入告警 + WS 推送
                        if verbose:
                            print("[5] 模拟定位设备上报告文（落入围栏中心）")
                        _publish(
                            BROKER_HOST,
                            BROKER_PORT,
                            "device/locate/up",
                            {
                                "device_no": LOC_NO,
                                "status": "在线",
                                "longitude": 121.5000,  # 围栏中心
                                "latitude": 31.2200,
                                "accuracy": 4.0,
                                "speed": 1.2,
                                "bearing": 270,
                                "timestamp": int(time.time()),
                            },
                        )
                        msgs = _recv_until(ws, {"location", "alarm"}, max_msgs=4, timeout=12)
                        types = {m.get("type") for m in msgs}
                        loc_ok = any(
                            m.get("type") == "location" and m["data"].get("device_no") == LOC_NO
                            for m in msgs
                        )
                        fence_alarm = next(
                            (
                                m
                                for m in msgs
                                if m.get("type") == "alarm"
                                and m["data"].get("alarm_type") == ALARM_TYPE_FENCE
                                and m["data"].get("device_no") == LOC_NO
                            ),
                            None,
                        )
                        steps.append(
                            _log(
                                "WS 收到 location + fence_intrusion 告警",
                                loc_ok and fence_alarm is not None,
                                f"收到类型={sorted(types)}",
                            )
                        )

                        # 落库校验
                        db = SessionLocal()
                        try:
                            loc_row = db.scalar(
                                select(DeviceLocation)
                                .where(DeviceLocation.device_no == LOC_NO)
                                .order_by(DeviceLocation.id.desc())
                            )
                            fence_row = db.scalar(
                                select(Alarm).where(
                                    Alarm.device_no == LOC_NO, Alarm.alarm_type == ALARM_TYPE_FENCE
                                )
                            )
                        finally:
                            db.close()
                        steps.append(
                            _log(
                                "落库 DeviceLocation + Alarm(fence_intrusion)",
                                loc_row is not None and fence_row is not None,
                                f"loc={loc_row is not None}, alarm={fence_row is not None}",
                            )
                        )

                        # 5b) 定位设备在围栏外紧邻大机 → 仅触发 间距告警（不触发围栏）
                        if verbose:
                            print("[5b] 模拟定位设备在大机附近(围栏外)上报 → 间距告警")
                        _publish(
                            BROKER_HOST,
                            BROKER_PORT,
                            "device/locate/up",
                            {
                                "device_no": LOC_NO,
                                "status": "在线",
                                "longitude": _DIST_LNG,
                                "latitude": _DIST_LAT,
                                "accuracy": 4.0,
                                "speed": 0.5,
                                "bearing": 270,
                                "timestamp": int(time.time()),
                            },
                        )
                        msgs_d = _recv_until(ws, {"alarm"}, max_msgs=2, timeout=12)
                        dist_alarm = next(
                            (
                                m
                                for m in msgs_d
                                if m.get("type") == "alarm"
                                and m["data"].get("alarm_type") == ALARM_TYPE_DISTANCE
                                and m["data"].get("device_no") == LOC_NO
                            ),
                            None,
                        )
                        steps.append(
                            _log(
                                "WS 收到 distance_too_close 间距告警",
                                dist_alarm is not None,
                                f"info={dist_alarm['data'].get('alarm_info') if dist_alarm else None}",
                            )
                        )
                        db = SessionLocal()
                        try:
                            dist_row = db.scalar(
                                select(Alarm).where(
                                    Alarm.device_no == LOC_NO,
                                    Alarm.alarm_type == ALARM_TYPE_DISTANCE,
                                )
                            )
                        finally:
                            db.close()
                        steps.append(
                            _log(
                                "落库 Alarm(distance_too_close)",
                                dist_row is not None,
                                f"info={dist_row.alarm_info if dist_row else None}",
                            )
                        )

                        # 6) 上行②：大机设备自报告警 → device_alarm + WS 推送
                        if verbose:
                            print("[6] 模拟大机设备自报告警（接口3）")
                        _publish(
                            BROKER_HOST,
                            BROKER_PORT,
                            "device/anti_intrusion/up",
                            {
                                "device_no": AI_NO,
                                "status": "在线",
                                "longitude": 121.4996,
                                "latitude": 31.2200,
                                "alarm_status": "告警开始",
                                "alarm_info": "A 防区限界侵入",
                                "image": "http://minio.example/ai/A.jpg",
                                "video": "http://minio.example/ai/A.mp4",
                                "timestamp": int(time.time()),
                            },
                        )
                        msgs2 = _recv_until(ws, {"location", "alarm"}, max_msgs=4, timeout=12)
                        dev_alarm = next(
                            (
                                m
                                for m in msgs2
                                if m.get("type") == "alarm"
                                and m["data"].get("alarm_type") == ALARM_TYPE_DEVICE
                                and m["data"].get("device_no") == AI_NO
                            ),
                            None,
                        )
                        steps.append(
                            _log(
                                "WS 收到 device_alarm（大机自报）",
                                dev_alarm is not None,
                                f"alarm_level={dev_alarm['data'].get('alarm_level') if dev_alarm else None}",
                            )
                        )
                        db = SessionLocal()
                        try:
                            dev_row = db.scalar(
                                select(Alarm).where(
                                    Alarm.device_no == AI_NO, Alarm.alarm_type == ALARM_TYPE_DEVICE
                                )
                            )
                        finally:
                            db.close()
                        steps.append(
                            _log(
                                "落库 Alarm(device_alarm) 含媒体",
                                dev_row is not None and dev_row.media_urls is not None,
                                f"media={dev_row.media_urls if dev_row else None}",
                            )
                        )

                        # 6b) 列车接近上行 → device_alarm(列车) + WS 推送
                        if verbose:
                            print("[6b] 模拟列车接近上报告警（接口5）")
                        _publish(
                            BROKER_HOST,
                            BROKER_PORT,
                            "device/train_approach/up",
                            {
                                "device_no": TA_NO,
                                "status": "在线",
                                "lane": "上行 I 道",
                                "direction": "来车方向：上行",
                                "speed": 118.0,
                                "alarm_status": "告警开始",
                                "alarm_info": "上行列车接近，限速预警",
                                "timestamp": int(time.time()),
                            },
                        )
                        msgs_t = _recv_until(ws, {"alarm"}, max_msgs=2, timeout=12)
                        ta_alarm = next(
                            (
                                m
                                for m in msgs_t
                                if m.get("type") == "alarm"
                                and m["data"].get("alarm_type") == ALARM_TYPE_DEVICE
                                and m["data"].get("device_no") == TA_NO
                            ),
                            None,
                        )
                        steps.append(
                            _log(
                                "WS 收到 device_alarm（列车接近）",
                                ta_alarm is not None,
                                f"info={ta_alarm['data'].get('alarm_info') if ta_alarm else None}",
                            )
                        )
                        db = SessionLocal()
                        try:
                            ta_row = db.scalar(
                                select(Alarm).where(
                                    Alarm.device_no == TA_NO,
                                    Alarm.alarm_type == ALARM_TYPE_DEVICE,
                                )
                            )
                        finally:
                            db.close()
                        steps.append(
                            _log(
                                "落库 Alarm(device_alarm/列车)",
                                ta_row is not None,
                                f"info={ta_row.alarm_info if ta_row else None}",
                            )
                        )

                        # 7) 下行：POST /command → broker 设备主题收到指令
                        if verbose:
                            print("[7] 下发设备指令并验证到达设备侧主题")
                        capture = MqttCapture(BROKER_HOST, BROKER_PORT)
                        capture.connect(f"device/locate/{LOC_NO}/down")
                        time.sleep(0.5)
                        r = httpx.post(
                            f"{APP_BASE}/api/v1/realtime/command",
                            headers={"Authorization": f"Bearer {token}"},
                            json={
                                "device_type": "locate",
                                "device_no": LOC_NO,
                                "action": "restart",
                                "params": {},
                            },
                            timeout=10,
                        )
                        steps.append(
                            _log(
                                "下发指令 API 200", r.status_code == 200, f"status={r.status_code}"
                            )
                        )
                        reached = capture.wait_for(
                            lambda t, p: t == f"device/locate/{LOC_NO}/down", timeout=8
                        )
                        steps.append(
                            _log(
                                "下行指令到达设备主题",
                                reached,
                                f"收到={capture.received[-1] if capture.received else None}",
                            )
                        )
                except Exception as exc:  # noqa: BLE001
                    steps.append(_log("启动 FastAPI 进程", False, str(exc)))
                    return False, steps
        except Exception as exc:  # noqa: BLE001
            return False, [_log("启动隔离 MQTT broker", False, str(exc))]
    except Exception as exc:  # noqa: BLE001
        steps.append(_log("联调过程异常", False, f"{type(exc).__name__}: {exc}"))
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if capture is not None:
            capture.close()
        _cleanup(plan_id)

    all_ok = all(s["ok"] for s in steps)
    if verbose:
        print("\n=== 联调结果：%s ===" % ("全部通过 ✅" if all_ok else "存在失败 ❌"))
    return all_ok, steps


if __name__ == "__main__":
    ok, _ = run_e2e(verbose=True)
    sys.exit(0 if ok else 1)
