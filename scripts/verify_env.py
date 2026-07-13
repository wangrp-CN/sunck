"""环境验证脚本：检查开发环境是否正确配置（方案A：原生服务）。
用法: .venv/bin/python scripts/verify_env.py
说明: 项目采用方案A——基础设施直接以原生服务运行：
        PostgreSQL(homebrew) / Redis(homebrew, 带密码) / Mosquitto(MQTT) / MinIO(二进制)。
      本脚本按原生默认端口 + 真实凭据连接（Redis 密码取自环境 REDIS_URL/REDIS_PASSWORD），
      验证 Python 官方驱动（psycopg2 / redis-py / paho-mqtt / minio SDK）的连通性。
"""

import importlib
import json
import shutil
import sys

RESULT = {"python": {}, "packages": {}, "services": {}, "ffmpeg": {}, "summary": {}}


def log_ok(cat, name, detail=""):
    RESULT[cat][name] = {"status": "OK", "detail": detail}


def log_warn(cat, name, detail):
    RESULT[cat][name] = {"status": "WARN", "detail": detail}


def log_fail(cat, name, detail):
    RESULT[cat][name] = {"status": "FAIL", "detail": detail}


# ---------- Python ----------
import platform

RESULT["python"] = {
    "version": platform.python_version(),
    "executable": sys.executable,
    "status": "OK",
}

# ---------- 关键包导入 ----------
PKGS = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "gunicorn": "gunicorn",
    "sqlalchemy": "sqlalchemy",
    "alembic": "alembic",
    "psycopg2": "psycopg2",
    "redis": "redis",
    "paho.mqtt": "paho.mqtt",
    "minio": "minio",
    "pydantic": "pydantic",
    "pydantic_settings": "pydantic_settings",
    "httpx": "httpx",
    "pyjwt": "jwt",
    "passlib": "passlib",
    "pillow": "PIL",
    "captcha": "captcha",
    "shapely": "shapely",
    "geopy": "geopy",
    "celery": "celery",
    "opencv": "cv2",
    "pytest": "pytest",
    "pytest_asyncio": "pytest_asyncio",
    "prometheus_client": "prometheus_client",
}
for label, mod in PKGS.items():
    try:
        m = importlib.import_module(mod)
        ver = getattr(m, "__version__", "?")
        log_ok("packages", label, f"v{ver}")
    except Exception as e:  # noqa
        log_fail("packages", label, str(e))

# locust 需独立进程运行（gevent monkey-patch 限制），此处单独用 CLI 校验
import os
import subprocess

try:
    locust_bin = os.path.join(os.path.dirname(sys.executable), "locust")
    out = subprocess.run([locust_bin, "--version"], capture_output=True, text=True, timeout=20)
    if "locust" in out.stdout:
        log_ok("packages", "locust", out.stdout.strip().split()[1])
    else:
        log_warn("packages", "locust", out.stdout + out.stderr)
except Exception as e:  # noqa
    log_warn("packages", "locust", f"CLI 校验跳过: {e}")

# ---------- ffmpeg ----------
ff = shutil.which("ffmpeg")
ffp = shutil.which("ffprobe")
if ff and ffp:
    log_ok("ffmpeg", "ffmpeg+ffprobe", ff)
else:
    log_fail("ffmpeg", "ffmpeg", "未安装（视频转码必需）：brew install ffmpeg")

# ---------- Redis ----------
import os as _os

import redis as redis_lib

# 优先使用应用真实的连接串（含原生 redis 密码），再回退若干候选
_redis_env = _os.environ.get("REDIS_URL")
REDIS_CANDIDATES = [_redis_env] if _redis_env else []
REDIS_CANDIDATES += [
    "redis://:dev_local_redis@127.0.0.1:6379/0",  # 原生 redis（带密码）
    "redis://127.0.0.1:6379/0",
    "redis://127.0.0.1:6380/0",
]
REDIS_CANDIDATES = [u for u in REDIS_CANDIDATES if u]
redis_done = False
for url in REDIS_CANDIDATES:
    try:
        r = redis_lib.from_url(url, socket_connect_timeout=3)
        r.ping()
        r.set("__env_check__", "1")
        r.delete("__env_check__")
        log_ok("services", "redis", url)
        redis_done = True
        break
    except Exception as e:  # noqa
        continue
if not redis_done:
    log_fail(
        "services",
        "redis",
        "默认 6379 不可达；请启动原生 redis（brew services start redis，确认 requirepass 与 .env 一致）",
    )

# ---------- PostgreSQL ----------
import sqlalchemy

PG_CANDIDATES = [
    "postgresql+psycopg2://dev:dev123@127.0.0.1:5432/rail_monitor",
    "postgresql+psycopg2://dev:dev123@127.0.0.1:5433/rail_monitor",
]
pg_done = False
for url in PG_CANDIDATES:
    try:
        eng = sqlalchemy.create_engine(url, pool_pre_ping=True)
        with eng.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
            # ORM 建表验证
            md = sqlalchemy.MetaData()
            t = sqlalchemy.Table(
                "env_check",
                md,
                sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True),
            )
            md.create_all(eng)
            md.drop_all(eng)
        log_ok("services", "postgresql", url)
        pg_done = True
        break
    except Exception as e:  # noqa
        continue
if not pg_done:
    log_fail(
        "services",
        "postgresql",
        "默认 5432 不可达；请启动原生 PostgreSQL（brew services start postgresql@17）并建库：CREATE ROLE dev WITH LOGIN PASSWORD 'dev123'; CREATE DATABASE rail_monitor OWNER dev;",
    )

# ---------- MQTT (Mosquitto 原生) ----------
import paho.mqtt.client as mqtt

MQTT_CANDIDATES = [("127.0.0.1", 1883)]
mqtt_done = False
for host, port in MQTT_CANDIDATES:
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        c.connect(host, port, keepalive=3)
        c.disconnect()
        log_ok("services", "mqtt", f"{host}:{port}")
        mqtt_done = True
        break
    except Exception as e:  # noqa
        continue
if not mqtt_done:
    log_fail(
        "services",
        "mqtt",
        "MQTT 未运行（原生 Mosquitto）：brew services start mosquitto，匿名可连 127.0.0.1:1883",
    )

# ---------- MinIO ----------
try:
    from minio import Minio

    MINIO_EP = "127.0.0.1:9000"
    try:
        mc = Minio(MINIO_EP, access_key="minioadmin", secret_key="minioadmin", secure=False)
        mc.list_buckets()
        log_ok("services", "minio", MINIO_EP)
    except Exception as e:  # noqa
        log_fail(
            "services",
            "minio",
            f"MinIO 未运行（原生）：启动 com.railmonitor.minio 守护（launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.railmonitor.minio.plist），API 127.0.0.1:9000；错误: {e}",
        )
except Exception as e:  # noqa
    log_fail("services", "minio", f"minio 导入失败: {e}")

# ---------- 汇总 ----------
counts = {"OK": 0, "WARN": 0, "FAIL": 0}
for cat in ("packages", "services", "ffmpeg"):
    for name, info in RESULT[cat].items():
        counts[info["status"]] = counts.get(info["status"], 0) + 1
RESULT["summary"] = counts

# 打印
print("=" * 60)
print("环境验证报告")
print("=" * 60)
print(f"Python: {RESULT['python']['version']}  ({RESULT['python']['executable']})")
for cat, title in (("packages", "Python 包"), ("services", "基础设施服务"), ("ffmpeg", "ffmpeg")):
    print(f"\n--- {title} ---")
    for name, info in RESULT[cat].items():
        mark = {"OK": "✅", "WARN": "⚠️", "FAIL": "❌"}[info["status"]]
        print(f"  {mark} {name:14s} {info['detail']}")
print("\n--- 汇总 ---")
print(f"  OK={counts['OK']}  WARN={counts['WARN']}  FAIL={counts['FAIL']}")

with open("scripts/env_check_result.json", "w", encoding="utf-8") as f:
    json.dump(RESULT, f, ensure_ascii=False, indent=2)
print("\n结果已写入 scripts/env_check_result.json")

# 退出码：有 FAIL 则非 0（ffmpeg 缺失也计 FAIL，但属可补救）
sys.exit(1 if counts["FAIL"] else 0)
