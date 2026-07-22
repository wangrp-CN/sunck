"""阶段3 Locust HTTP 负载定义（千台设备压测的「查看者」维度）。

说明：
- 本文件用 Locust 的 HttpUser 驱动**前端查看者**对 API 的并发访问压力，
  覆盖仪表盘统计、告警列表、实时位置、设备列表、在线状态、媒体预签名等读路径；
- 「千台设备 MQTT 上行」ingestion 压力由 scripts/mqtt_flood.py（独立进程、后台运行）
  承担，二者配合即构成完整压测。原因：Locust 的 gevent 猴子补丁与 paho-mqtt
  后台线程存在已知冲突，MQTT 上行不适合跑在 Locust 绿程内。
- 鉴权：压测环境验证码默认开启，故直接用 app 的 create_access_token 为 admin
  生成同源令牌（与运行后端同一 SECRET_KEY，合法有效），绕过登录验证码链路。

用法（rail_monitor 目录下）：
    .venv/bin/python -m locust -f scripts/locustfile.py ViewerUser \
        --headless -u 100 -r 20 -t 180s --csv /tmp/locust_viewer
"""

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from locust import HttpUser, between, task  # noqa: E402

HOST = os.getenv("LOCUST_HOST", "http://127.0.0.1:8000")


def _admin_token() -> str:
    """生成 admin 的访问令牌（与运行后端同源 SECRET_KEY，合法有效）。"""
    from app.core.database import SessionLocal  # noqa: E402
    from app.core.security import create_access_token  # noqa: E402
    from app.model.system import User  # noqa: E402

    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == "admin", User.is_deleted.is_(False)).first()
        uid = u.id if u else 1
    finally:
        db.close()
    return create_access_token(uid, expires_minutes=120)


class ViewerUser(HttpUser):
    host = HOST
    wait_time = between(1, 3)

    def on_start(self) -> None:
        self.token = _admin_token()
        self.client.headers.update({"Authorization": f"Bearer {self.token}"})

    @task(5)
    def dashboard_stats(self) -> None:
        self.client.get("/api/v1/dashboard/stats", name="dashboard/stats")

    @task(5)
    def list_alarms(self) -> None:
        self.client.get("/api/v1/alarms?page=1&page_size=20", name="alarms/list")

    @task(4)
    def realtime_locations(self) -> None:
        self.client.get("/api/v1/realtime/locations", name="realtime/locations")

    @task(3)
    def list_devices(self) -> None:
        self.client.get("/api/v1/devices?page=1&page_size=20", name="devices/list")

    @task(2)
    def online_status(self) -> None:
        self.client.get("/api/v1/realtime/online-status", name="realtime/online-status")

    @task(1)
    def media_access(self) -> None:
        # 不存在的 key 返回 404 属正常，仅用于压测媒体鉴权路径
        self.client.get(
            "/api/v1/media/access?key=alarms/2026/07/21/nonexist.png",
            name="media/access",
        )
