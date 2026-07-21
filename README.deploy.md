# 生产化部署指南（无 Docker）

本项目遵循「不引入 Docker」约定：所有组件以**原生进程**形态运行，通过 systemd 守护、nginx 反代、原生中间件（PostgreSQL / Redis / Mosquitto / MinIO）对外提供服务。本指南覆盖生产部署的完整步骤。

> 适用范围：Linux 生产服务器（systemd）。macOS 开发机仅作本地验证，部署单元文件位于 `deploy/`。

---

## 0. 前置条件

- 一台 Linux 服务器（推荐 Ubuntu 22.04+ / Rocky 9+），已装：
  - Python 3.13、Node.js 22
  - PostgreSQL 17、Redis 7、Mosquitto（MQTT）、MinIO（对象存储）
  - Nginx 1.20+
- 域名（如 `rail.example.com`）已解析到服务器公网 IP，且开放 80/443。

---

## 1. 密钥治理（务必先做）

真实 `.env` 已被 `.gitignore` 忽略，**严禁提交**。部署时：

```bash
cd /opt/rail_monitor
cp .env.example .env
# 逐项替换为强随机值，至少下列必须改：
#   SECRET_KEY        → python -c "import secrets;print(secrets.token_urlsafe(48))"
#   POSTGRES_PASSWORD / REDIS_PASSWORD / MINIO_*/ MQTT_* → 强密码
#   CORS_ORIGINS      → 改为前端正式域名，禁止 *
#   AMAP_WEB_KEY      → 填真实高德 Key（否则地图降级散点）
#   MINIO_PUBLIC_URL  → 生产经 nginx /files/ 时设为 https://<域名>/files（媒体可公网直连）
chmod 600 .env
```

前端同样：
```bash
cp web/.env.example web/.env   # 填 VITE_AMAP_KEY / VITE_AMAP_SECURITY_CODE
```

---

## 2. 后端依赖与构建

```bash
python3.13 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

cd web && npm ci && npm run build && cd ..   # 产出 web/dist
```

---

## 3. 中间件（原生服务）

分别用系统包管理器安装并启用 PostgreSQL / Redis / Mosquitto / MinIO，确保：
- PostgreSQL 建库 `rail_monitor`、用户与 `.env` 中 `POSTGRES_*` 一致；
- Redis 设置 `.env` 中 `REDIS_PASSWORD`（生产务必设密码）；
- Mosquitto 配置 `allow_anonymous true`（内网隔离）或启用账户；
- MinIO 创建 bucket `rail-monitor`（与 `MINIO_BUCKET` 一致）。

数据库迁移与种子（一次性）：
```bash
. .venv/bin/activate
alembic upgrade head
python scripts/seed_rbac.py
python scripts/seed_demo.py
```

---

## 4. 进程守护（systemd）

单元文件已提供：`deploy/rail-monitor-api.service`、`deploy/rail-monitor-simulator.service`。

```bash
sudo useradd -r -s /bin/false railmonitor
sudo chown -R railmonitor:railmonitor /opt/rail_monitor
sudo cp deploy/rail-monitor-api.service /etc/systemd/system/
sudo cp deploy/rail-monitor-simulator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rail-monitor-api
sudo systemctl enable --now rail-monitor-simulator
# 真实设备接入后，可停用模拟器：sudo systemctl disable --now rail-monitor-simulator
```

> 单元文件中路径均为 `/opt/rail_monitor`，请按实际部署目录修改。

---

## 5. HTTPS 与反向代理（nginx）

已提供 `nginx.conf`（server 片段，含 80→443 重定向、WebSocket、MinIO 同源代理、gzip、安全头、大文件上传）。

```bash
# 申请证书（Let's Encrypt，需域名已解析且 80 可达）
sudo certbot certonly --nginx -d rail.example.com
# 证书通常位于 /etc/letsencrypt/live/rail.example.com/fullchain.pem 与 privkey.pem
# 将 nginx.conf 中 ssl_certificate / ssl_certificate_key 指向实际路径

# 部署配置
sudo cp nginx.conf /etc/nginx/conf.d/rail_monitor.conf   # Linux
# 或 macOS: cp nginx.conf /opt/homebrew/etc/nginx/servers/rail_monitor.conf
sudo nginx -t && sudo systemctl reload nginx
```

> **关键约定（务必核对）**：
> - 前端 `root` 已设为 `/opt/rail_monitor/web/dist`（与 systemd 单元部署目录一致）。
> - `location /api/` 与 `location /ws/` 的 `proxy_pass` **不带尾斜杠**，以保留原始 `/api`、`/ws` 前缀转发给后端（后端 `api_router` 挂载于 `/api`、`/ws/alarm` 为 WebSocket 路由；若误加尾斜杠会剥离前缀导致 404）。
> - WebSocket 前端经**同源**连接（`ws.ts` 用 `window.location` 推导 `ws/wss` 与 host），生产由 nginx `/ws/` 反代到后端 8000，无需对外暴露 8000 端口。
> - 媒体经 nginx `/files/` 同源代理暴露（配合 `.env` 的 `MINIO_PUBLIC_URL=https://<域名>/files`），外部浏览器可直连加载，MinIO 端口不对外。
> - 证书续期：`sudo certbot renew`（建议配 cron/systemd timer）。

---

## 6. CI/CD（GitHub Actions）

`.github/workflows/ci.yml` 已配置：推送/PR 到 `main|master|develop` 时自动跑端到端门禁（起 PG/Redis service + 原生 Mosquitto/MinIO → 复用 `scripts/run_demo.sh --skip-services` 完成迁移/种子/pytest/前端 build+vitest/live 自证）。

启用步骤：
```bash
git remote add origin <your-github-repo-url>
git push -u origin main
```
此后每次 push/PR 自动触发（Actions 标签页可见）。

> 说明：CI 中 PG/Redis 用 GitHub 托管 service container 仅作测试基础设施，应用本身不容器化，符合「不引入 Docker」约定。

---

## 7. 运维速查

| 操作 | 命令 |
|------|------|
| 查看后端日志 | `sudo journalctl -u rail-monitor-api -f` |
| 查看模拟器日志 | `sudo journalctl -u rail-monitor-simulator -f` |
| 重启后端 | `sudo systemctl restart rail-monitor-api` |
| 重新迁移 | `.venv/bin/alembic upgrade head` |
| 跑端到端门禁 | `bash scripts/run_demo.sh --skip-services --port 8011` |
| 健康检查 | `curl -fsS http://127.0.0.1:8000/health` |
| 指标抓取 | 后端 `/metrics`（Prometheus 客户端）；抓取配置见 `deploy/prometheus.yml`（目标 `127.0.0.1:8000`，原生部署非 Docker） |

---

## 8. 本地验证记录（开发机）

- nginx 语法：`nginx -t`（配置见 `nginx.conf`，含 SSL/重定向/WebSocket/安全头）✅
- `.gitignore` 已忽略 `.env`/`dist`/`__pycache__` ✅
- 端到端门禁：`run_demo.sh --skip-services --port 8011` 全绿（实时/告警/轨迹/报表/导出/仪表盘/快照一致）✅
