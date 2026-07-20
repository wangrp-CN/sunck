# 环境配置与验证报告（ENV_CHECK）

> 项目：`rail_monitor`（涉铁工程智能监控平台后端）
> 生成：2026-07-10
> 虚拟环境：`.venv`（基于受管 Python 3.13.12）
> 结论：**29 项检查全部通过（OK=29 / WARN=0 / FAIL=0）**，应用层 `/health`、`/metrics` 实测 200。

---

## 一、已安装并验证的依赖（含实际版本）

### 1.1 Python 第三方库（全部安装成功，无冲突、无失败）

| 类别 | 包 | 锁定版本 | 用途 |
|---|---|---|---|
| P0 核心 | fastapi | 0.139.0 | Web 框架（REST+WebSocket） |
| P0 | uvicorn | 0.51.0 | ASGI 服务器 |
| P0 | gunicorn | 26.0.0 | 生产进程管理 |
| P0 | sqlalchemy | 2.0.51 | ORM |
| P0 | alembic | 1.18.5 | 数据库迁移 |
| P0 | psycopg2-binary | 2.9.12 | PostgreSQL 驱动 |
| P0 | redis | 8.0.1 | Redis 客户端 |
| P0 | paho-mqtt | 2.1.0 | MQTT 客户端 |
| P0 | minio | 7.2.20 | 对象存储客户端 |
| P0 | python-dotenv | 1.2.2 | 环境变量 |
| P1 | pydantic / pydantic-settings | 2.13.4 / 2.14.2 | 校验/配置 |
| P1 | httpx | 0.28.1 | 异步 HTTP |
| P1 | pyjwt | 2.13.0 | JWT 鉴权 |
| P1 | passlib / bcrypt | 1.7.4 / 4.0.1 | 密码哈希（已知兼容组合） |
| P1 | pillow / captcha | 12.3.0 / 0.7.1 | 验证码/图像 |
| P1 | shapely / geopy | 2.1.2 / 2.4.1 | 地理计算 |
| P1 | celery | 5.6.3 | 异步任务 |
| P1 | opencv-python-headless | 5.0.0.93 | 视频抽帧 |
| P2 | pytest / pytest-asyncio | 9.1.1 / 1.4.0 | 测试 |
| P2 | locust | 2.45.0 | 压测 |
| P2 | prometheus-client | 0.25.0 | 指标 |

> 完整锁定见 `requirements.lock.txt`（95 行）。`flask/flask-login` 等为 locust 的传递依赖，非直接使用。

### 1.2 基础设施服务（已连通验证）

| 服务 | 验证地址（方案A：原生服务） | 说明 | 验证结果 |
|---|---|---|---|
| Redis | 127.0.0.1:6379（密码 dev_local_redis） | homebrew redis | ✅ set/get 通过 |
| PostgreSQL | 127.0.0.1:5432（库 rail_monitor，角色 dev） | homebrew postgresql@17 | ✅ 连接 + ORM 建表/删表通过 |
| MQTT（Mosquitto） | 127.0.0.1:1883（匿名） | homebrew mosquitto，非 EMQX | ✅ connect 通过 |
| MinIO | 127.0.0.1:9000 | 原生 minio 二进制（数据 ~/minio_data，持久化避免 /tmp 重启丢失） | ✅ list_buckets 通过 |
| ffmpeg | /opt/homebrew/bin/ffmpeg (8.1.2) | — | ✅ ffprobe 可用 |

> 注：本项目已绑定【方案A：原生服务】（见 OPTION_A.md），基础设施以原生服务直接运行，不依赖 Docker 容器。

### 1.3 应用层端到端

- `uvicorn app.main:app` 启动成功，`GET /health` → `{"status":"ok","app":"涉铁工程智能监控平台"}`（200）
- `GET /metrics` → Prometheus 指标输出（200）
- `pytest tests/` → 2 passed（FastAPI 组装 + /health + /metrics）

---

## 二、环境验证方法（在你的开发机上复现）

```bash
cd rail_monitor
source .venv/bin/activate

# 1) Python 包导入冒烟
python scripts/smoke_test.py

# 2) 基础设施 + ffmpeg 综合检查（输出报告并写 env_check_result.json）
python scripts/verify_env.py

# 3) 单元测试
pytest tests/ -q

# 4) 启动依赖服务（需 Docker）
docker compose up -d                 # 核心 4 项
docker compose --profile optional up -d   # 另含 TimescaleDB/RabbitMQ/Prometheus/Grafana

# 5) 启动应用
uvicorn app.main:app --reload --port 8000
curl http://127.0.0.1:8000/health
```

---

## 三、遇到的问题与解决方案（已记录）

| # | 问题 | 根因 | 解决 / 方案 |
|---|---|---|---|
| 1 | 本隔离沙箱 `docker` 守护进程未运行（`docker.sock` 不存在） | 沙箱无 hypervisor，无法起 Docker 引擎 | `docker-compose.yml` 已就绪；在装有 Docker 的开发机执行 `docker compose up -d` 即可。沙箱内改用 homebrew 原生 PG/Redis + MinIO 单机二进制完成连通验证 |
| 2 | `locust` 在同进程内 `import` 报 `RecursionError` | locust 在 `__init__` 中对 gevent 做 monkey-patch，与已加载的 urllib3/anyio/redis 冲突（已知行为） | **非依赖冲突**，正常以 CLI 使用（`locust -f ...`）不受影响；验证脚本改用子进程 `locust --version` 校验通过 |
| 3 | 沙箱默认 6379/5432 已被预装实例占用，且 Redis 设了密码、PG 超户非 `dev` | 环境预置的 homebrew PG/Redis 占用了默认端口 | 验证时改用空闲端口（Redis 6380、PG 5433）独立实例；生产用 Docker 默认端口即可 |
| 4 | 开发机若同时运行原生 PG/Redis 与 Docker 版，端口 5432/6379 会冲突 | 两套服务抢同一端口 | 启动 Docker 前先停原生实例（`brew services stop postgresql redis`），或修改 `docker-compose.yml` 端口映射 |
| 5 | `passlib` 1.7.4 与 `bcrypt>=4.1` 存在已知 API 不兼容 | bcrypt 4.1+ 移除了部分属性 | 显式锁定 `bcrypt==4.0.1`（已在 requirements.txt 固定），安装无报错 |
| 6 | 报告未指定各依赖精确版本 | 原分析文档按"优先级分类"未锁版本 | 本次安装后 `pip freeze > requirements.lock.txt` 锁定全部实际版本，保证可复现 |

---

## 四、待在开发机确认/补充项

1. **Docker 服务**：沙箱无法起 Docker，PG/Redis/MQTT/MinIO 的"生产容器"需在你的开发机用 `docker compose up -d` 拉起并建库（`CREATE DATABASE rail_monitor;`）。
2. **高德地图 Key**：`.env` 中 `AMAP_WEB_KEY` 需填入真实 Web 服务 Key（前端 JS API 与后端逆地理编码共用）。
3. **前端工程化**：报告 P1 的 Vite+Vue3+ECharts+高德 JS API 前端脚手架尚未生成（本次聚焦后端/基础设施环境）；如需可单独初始化 `frontend/`。
4. **Nginx**：配置 `nginx.conf` 已就绪，部署时 `cp` 到 nginx servers 目录并 `nginx -s reload`。
5. **密钥安全**：`.env` 已被 `.gitignore` 忽略，切勿提交真实密钥。

---

## 五、目录结构

```
rail_monitor/
├── .venv/                 # 虚拟环境（已装全部依赖）
├── .env.example           # 环境变量模板
├── .gitignore
├── requirements.txt       # 依赖清单（按优先级分类）
├── requirements.lock.txt  # 锁定版本（pip freeze）
├── install.log            # pip 安装日志
├── docker-compose.yml     # 基础设施编排（P0 + P2 可选 profile）
├── nginx.conf             # Nginx 反向代理
├── app/
│   ├── __init__.py
│   ├── config.py          # pydantic-settings 读取 .env
│   └── main.py            # 最小可运行 FastAPI（health/ws/metrics）
├── tests/test_health.py   # pytest 用例
├── scripts/
│   ├── smoke_test.py      # 包导入冒烟
│   ├── verify_env.py      # 综合验证（输出 env_check_result.json）
│   └── env_check_result.json
└── deploy/prometheus.yml  # Prometheus 抓取配置
```
