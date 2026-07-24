# 涉铁工程智能监控平台 · 生产部署手册

> 适用对象：运维 / 实施。描述在 Linux（systemd）上将本平台以「Nginx 反代 + 后端守护进程 + 前端静态托管」方式上线的完整步骤。
> 配套文件：`deploy/rail-monitor-api.service`、`deploy/rail-monitor-simulator.service`、`deploy/nginx.conf`。

---

## 0. 目标架构

```
                        ┌─────────────────────────────┐
   浏览器 ──http/https──▶│  Nginx (80/443)             │
                        │  - 静态托管 web/dist        │
                        │  - /api  → 127.0.0.1:8000   │
                        │  - /ws   → 127.0.0.1:8000   │
                        │  - /health /metrics 透传    │
                        └──────────────┬──────────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │  FastAPI (uvicorn :8000)     │
                        │  systemd: rail-monitor-api   │
                        └───┬──────┬──────┬──────┬─────┘
                            │      │      │      │
                          PostgreSQL Redis Mosquitto MinIO
                          (PG17)  (6379) (1883)  (:9000)
```

**路径约定**：项目统一部署于 `/opt/rail_monitor`；前端构建产出 `/opt/rail_monitor/web/dist`；运行用户 `railmonitor`。

---

## 1. 前置依赖

| 组件 | 版本/要求 | 说明 |
|---|---|---|
| OS | Linux (systemd) | 本文以 Ubuntu 22.04+ 为例 |
| Python | 3.13.x | 后端虚拟环境 `.venv` |
| Node.js | 22.x | 仅用于**构建**前端（运行时不需要） |
| PostgreSQL | 17 | 数据库 `rail_monitor` |
| Redis | 6+ | 缓存 / 在线状态 / 限流 |
| Mosquitto | 2.x | MQTT broker（匿名或账号均可） |
| MinIO | 最新 | 对象存储（附件 / 媒体） |
| Nginx | 1.20+ | 反向代理 + 静态托管 |

> 开发机可用 `scripts/native-services.sh` 一键拉起 PG/Redis/MQTT/MinIO；生产环境请按各自发行版文档安装并设为开机自启。

---

## 2. 获取代码与目录准备

```bash
sudo useradd -r -s /bin/false railmonitor
sudo mkdir -p /opt/rail_monitor
sudo chown -R railmonitor:railmonitor /opt/rail_monitor
# 将仓库内容放到 /opt/rail_monitor（建议 git clone 或 scp 产物）
```

---

## 3. 后端部署

### 3.1 虚拟环境与依赖

```bash
cd /opt/rail_monitor
sudo -u railmonitor python3.13 -m venv .venv
sudo -u railmonitor .venv/bin/pip install -U pip
sudo -u railmonitor .venv/bin/pip install -r requirements.txt
```

### 3.2 数据库迁移（建表 / 补齐索引）

```bash
sudo -u railmonitor .venv/bin/alembic upgrade head
```

> 首次部署即执行到 head；后续升级重复此命令即可（迁移链向下兼容）。

### 3.3 配置文件 `.env`（权限 600，切勿提交）

```bash
sudo -u railmonitor touch /opt/rail_monitor/.env
sudo chmod 600 /opt/rail_monitor/.env
sudo -u railmonitor vi /opt/rail_monitor/.env
```

**模板（生产请替换为强密码 / 真实地址）：**

```dotenv
# ---------- 应用 ----------
APP_ENV=production
DEBUG=false
LOG_LEVEL=INFO
# CORS：生产请改为前端实际域名，逗号分隔；不要用 "*"
CORS_ORIGINS=https://monitor.example.com

# ---------- 安全 / 认证 ----------
SECRET_KEY=请替换为至少 32 位随机串
ACCESS_TOKEN_EXPIRE_MINUTES=1440
REFRESH_TOKEN_EXPIRE_DAYS=30
# 生产环境【保持开启】验证码（需求 §2.2.1 必填）；仅测试/CI 才设 false
CAPTCHA_ENABLED=true
RESP_CACHE_ENABLED=true
AUDIT_ENABLED=true
# 初始超管（首次播种写入；生产务必修改默认口令）
DEFAULT_ADMIN_USERNAME=admin
DEFAULT_ADMIN_PASSWORD=Admin@请修改强口令

# ---------- PostgreSQL ----------
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=rail_monitor
POSTGRES_USER=rail_monitor
POSTGRES_PASSWORD=强密码
# 连接池（按实际 worker 数调整；单 worker 约 30 连接）
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
DB_POOL_TIMEOUT=10
INGEST_DB_POOL_SIZE=12
INGEST_DB_MAX_OVERFLOW=8
READ_DB_POOL_SIZE=10
READ_DB_POOL_OVERFLOW=10

# ---------- Redis ----------
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=强密码   # 与 Redis 实例配置一致；为空则无密码

# ---------- MQTT（Mosquitto） ----------
MQTT_BROKER=127.0.0.1
MQTT_PORT=1883
MQTT_USERNAME=            # 匿名可留空
MQTT_PASSWORD=

# ---------- 实时链路 ----------
ONLINE_THRESHOLD_SECONDS=300

# ---------- 上行 ingestion（阶段3 甜点参数，通常无需改） ----------
INGEST_ENABLED=true
INGEST_WORKERS=8
INGEST_QUEUE_MAX=20000
INGEST_BATCH_SIZE=200
INGEST_BATCH_MAX_WAIT=0.5

# ---------- MinIO 对象存储 ----------
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=强密码
MINIO_BUCKET=rail-monitor
MINIO_SECURE=false
# 经 nginx 同源代理媒体时设为 https://<域名>/files（详见 §6.4）
MINIO_PUBLIC_URL=

# ---------- 高德地图 Web 服务（坐标逆编码/地图显示） ----------
AMAP_WEB_KEY=
```

> 变量名不区分大小写；`config.py` 中以 `POSTGRES_*`、`REDIS_*`、`MQTT_*`、`MINIO_*` 等读取。

### 3.4 安装并启用 systemd 单元

```bash
sudo cp deploy/rail-monitor-api.service /etc/systemd/system/
# 真实设备接入后无需模拟器；开发/演示期可启用：
# sudo cp deploy/rail-monitor-simulator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rail-monitor-api
# sudo systemctl enable --now rail-monitor-simulator
sudo journalctl -u rail-monitor-api -f   # 观察启动日志
```

---

## 4. 前端部署（构建 + Nginx 托管）

### 4.1 构建

```bash
cd /opt/rail_monitor/web
npm ci
# 如需自定义 API 基址（默认同源 /api，一般无需改）：
# echo "VITE_API_BASE=/api" > .env
npm run build          # 产出 web/dist
```

### 4.2 放置 Nginx 配置

```bash
sudo cp deploy/nginx.conf /etc/nginx/conf.d/rail-monitor.conf
sudo nginx -t          # 语法校验，必须输出 "test is successful"
sudo systemctl reload nginx
```

> 默认 server 监听 80、`server_name _`、静态根 `/opt/rail_monitor/web/dist`。
> 生产建议启用 HTTPS（见 `nginx.conf` 末尾注释：certbot 或手动 443 块 + 80 跳转）。

---

## 5. 启动顺序与验证

依赖启动顺序（均设为开机自启即可，单元已声明 After/Wants）：

```
PostgreSQL → Redis → Mosquitto → MinIO → rail-monitor-api → (simulator) → nginx
```

### 5.1 健康检查

```bash
# 后端存活（nginx 透传 /health）
curl -fsS http://127.0.0.1/health && echo " OK"

# OpenAPI 文档结构（公网被拦截，内网可用）
curl -fsS http://127.0.0.1/openapi.json | head -c 200; echo

# 业务冒烟：登录拿到 token，探几个 P3 新端点
TOKEN=$(curl -s -X POST http://127.0.0.1/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"<你的口令>"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['data']['access_token'])")
curl -s http://127.0.0.1/api/v1/devices/health -H "Authorization: Bearer $TOKEN" | head -c 300; echo
curl -s "http://127.0.0.1/api/v1/dashboard/project-compare?days=7" -H "Authorization: Bearer $TOKEN" | head -c 300; echo
curl -s http://127.0.0.1/api/v1/inspections/stats -H "Authorization: Bearer $TOKEN" | head -c 300; echo
curl -s http://127.0.0.1/api/v1/videos/channels -H "Authorization: Bearer $TOKEN" | head -c 300; echo
```

> 前端页面直接访问 `http://<域名>/` 即可；登录后在「系统管理 / 数据字典」「巡检」「视频 AI」「设备健康」「对比大屏」「作业计划」等菜单验证新模块。

---

## 6. 运维与回滚

### 6.1 常用命令

```bash
sudo systemctl restart rail-monitor-api          # 重启后端
sudo systemctl status  rail-monitor-api          # 状态
sudo journalctl -u rail-monitor-api -n 200 --no-pager   # 日志
sudo nginx -t && sudo systemctl reload nginx     # 改完配置后重载
```

### 6.2 版本升级

```bash
cd /opt/rail_monitor
git pull                # 或替换产物
sudo -u railmonitor .venv/bin/pip install -r requirements.txt
sudo -u railmonitor .venv/bin/alembic upgrade head   # 迁移增量
cd web && npm ci && npm run build
sudo systemctl restart rail-monitor-api
sudo systemctl reload nginx
```

### 6.3 回滚

- 保留上一个 `web/dist` 备份（如 `dist.bak`），回滚时换回并 `reload nginx`。
- 后端回滚到上一 Git 提交后重跑 3.2/3.4 步骤；数据库迁移一般**不回退**（向下兼容）。

### 6.4 媒体（MinIO）暴露方式（二选一）

1. **前端直连 MinIO**（默认）：`MINIO_PUBLIC_URL` 留空，前端用 MinIO 内部地址 + 预签名 URL。需 MinIO 对浏览器可达且配置 CORS。
2. **Nginx 同源代理**（推荐生产）：放开 `nginx.conf` 末尾 `/media/` 段，并将 `MINIO_PUBLIC_URL=https://<域名>/files`，使预签名 URL 走同源，规避跨域与暴露内部地址。

---

## 7. 安全建议（生产必做）

- `.env` 权限 `600`，属主 `railmonitor`；**切勿提交进 Git**。
- `CORS_ORIGINS` 改为具体域名，不要 `*`。
- `SECRET_KEY` 使用足够随机的长串；`DEFAULT_ADMIN_PASSWORD` 必须修改。
- 公网 **关闭** Swagger/Redoc（`nginx.conf` 已 `deny` `/docs`、`/redoc`）。
- 启用 HTTPS，并 `return 301 https://$host$request_uri;` 强制跳转。
- `/metrics` 仅对监控网段放通（在 `nginx.conf` 该 `location` 加 `allow/deny`）。
- PostgreSQL / Redis / Mosquitto / MinIO 仅监听内网或加防火墙；Redis 务必设密码。
- 定期备份 PostgreSQL（`pg_dump`）与 MinIO 数据卷。

---

## 8. 已知坑 / FAQ

- **`/api` 前缀**：后端路由本身已带 `/api`（`APIRouter(prefix="/api")`），Nginx 的 `proxy_pass http://railmon_api;` **末尾不要加 `/`**，否则会剥离 `/api` 导致 404。
- **WebSocket**：告警推送走 `/ws/alarm`，Nginx 已配置 `Upgrade/Connection` 头与 3600s 读超时；若反向代理有多层，需逐层透传。
- **验证码**：生产保持 `CAPTCHA_ENABLED=true`；若自动化/演示需要关闭，仅临时设 `false` 并重启。
- **Mosquitto 匿名**：默认配置允许匿名接入；生产建议开启账号认证并在 `.env` 填 `MQTT_USERNAME/PASSWORD`。
- **首次启动无数据**：登录后通过各模块「新建」或运行 `scripts/seed_stress.py`（演示/压测造数，非生产必备）初始化。
- **媒体不显示**：检查 MinIO 可达性 / CORS，或改用 §6.4 的 Nginx 同源代理方案。

---

## 9. 开发机快速验证（非生产）

```bash
# 启动本地全套基础设施 + 后端 + 模拟器（依赖 Homebrew 安装的 PG/Redis/MQTT/MinIO）
bash scripts/native-services.sh start
cd /opt/rail_monitor && .venv/bin/uvicorn app.main:app --port 8000   # 需 CAPTCHA_ENABLED=false
cd web && npm run dev     # 开发热更新，:5173
```
