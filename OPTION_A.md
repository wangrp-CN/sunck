# 方案A：原生服务架构基线（本项目绑定架构）

> 状态：**本项目唯一绑定的基础设施架构**。所有模块实现、配置、部署均严格遵循本文件。
> 不引入 Docker 容器、不混入 mock / 内存替身、不使用方案A范围外的任何中间件。

## 一、技术选型范围（仅限以下原生组件）

| 能力 | 原生组件 | 应用侧官方客户端 | 默认端口 | 认证 |
|---|---|---|---|---|
| 关系型数据库 | PostgreSQL（homebrew `postgresql@17`） | SQLAlchemy + psycopg2 | 5432 | 角色 `dev` / `dev123`，库 `rail_monitor` |
| 缓存 / 消息 broker 后端 | Redis（homebrew `redis`，已设密码） | redis-py | 6379 | 密码 `dev_local_redis` |
| MQTT 消息 | Mosquitto（homebrew `mosquitto`，匿名） | paho-mqtt | 1883（TCP）/ 9001（WebSocket） | 匿名 |
| 对象存储 | MinIO（官方二进制） | minio SDK | 9000（API）/ 9002（控制台） | `minioadmin` / `minioadmin`，数据 `/tmp/minio_data` |

**明确排除（方案A范围外，禁止用于本项目的开发/部署）：**
- Docker / Docker Compose（见 `docker-compose.yml`，仅作可选容器化参考，非默认路径，且其内含的 EMQX / RabbitMQ / TimescaleDB 不在本架构内）
- EMQX、RabbitMQ、TimescaleDB 等额外消息/时序中间件
- SQLite、`fakeredis`、内存 MQTT 等 mock / 替身（仅允许在纯离线单测中临时使用，不得进入业务代码路径）

## 二、核心约束

1. **直接依赖原生接口**：业务代码通过上面列出的官方客户端**直接**调用原生服务，不封装可切换后端的抽象层（如"可换 PG/SQLite 的 repository 抽象"）。
2. **单一真源配置**：连接参数以 `.env`（由 `.env.example` 复制）为准；`.env.example` 已对齐原生服务的真实端口与凭据（Redis 密码、Mosquitto 匿名、MinIO minioadmin）。
3. **部署即原生**：见 `scripts/native-services.sh`（`start|stop|status`）。MinIO 通过 `~/Library/LaunchAgents/com.railmonitor.minio.plist` 以 launchd 守护常驻；PG/Redis/Mosquitto 经 `brew services` 管理。
4. **MQTT 即 Mosquitto**：应用连接 `127.0.0.1:1883`（匿名）。不要编写依赖 EMQX 专有特性的逻辑。

## 三、环境就绪自检

```bash
cd rail_monitor
source .env/bin/activate            # 注意：venv 实际在 .venv
python scripts/verify_env.py        # 应 OK=29 左右，无 FAIL
./scripts/native-services.sh status # 查看原生服务状态
```

## 四、首次初始化（一次性）

```bash
# PostgreSQL：建 dev 角色与 rail_monitor 库
createuser -s dev 2>/dev/null || true
psql -c "ALTER ROLE dev WITH PASSWORD 'dev123';" 2>/dev/null || true
createdb -O dev rail_monitor 2>/dev/null || true
```

> 注：本机已执行过上述初始化；如库/角色丢失，重跑即可。
