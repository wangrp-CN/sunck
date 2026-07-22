"""应用配置：从 .env 读取（含默认值，便于本地无配置启动）。

遵循《开发计划》基础设施层约定。所有外部依赖的连接串均可在 .env 中覆盖；
未提供时按本机默认（原生 PG/Redis/MQTT/MinIO）拼装，保证 `python app/main.py`
在无外部服务时也能启动（仅对应接口在调用时才报错）。
"""

from typing import Optional

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ---------- 应用 ----------
    app_name: str = "涉铁工程智能监控平台"
    app_env: str = "development"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    # CORS：逗号分隔的源，默认 "*"
    cors_origins: str = "*"

    # ---------- 安全 / 认证 ----------
    secret_key: str = "change-me-to-a-long-random-string"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440
    refresh_token_expire_days: int = 30
    # 登录失败重试限制
    max_login_attempts: int = 5
    account_lock_minutes: int = 15
    # 密码强度策略（注册/改密时校验）
    password_min_length: int = 8
    password_require_upper: bool = True
    password_require_lower: bool = True
    password_require_digit: bool = True
    password_require_special: bool = False
    # 登录验证码（需求 §2.2.1 必填；测试环境可关闭）
    captcha_enabled: bool = True
    captcha_ttl_seconds: int = 300
    captcha_length: int = 4
    # 响应级短 TTL 缓存（阶段3 收尾·查询优化）：监控大屏 / 实时看板高频只读端点，
    # 以「user_id + 路径 + 查询串」为键缓存 3s，把并发重复聚合折叠为每窗口 1 次计算。
    # 测试环境默认关闭，避免跨用例缓存命中破坏隔离。
    resp_cache_enabled: bool = True
    # 初始超级管理员（首次播种时写入，生产环境请通过环境变量覆盖）
    default_admin_username: str = "admin"
    default_admin_password: str = "Admin@123456"

    # ---------- PostgreSQL ----------
    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5432
    postgres_db: str = "rail_monitor"
    postgres_user: str = "dev"
    postgres_password: str = "dev123"
    database_url: Optional[str] = None
    # 连接池调优（阶段3 压测发现：默认 5+溢出10=15 连接在高并发 API +
    # 同步 per-message ingestion 下被耗尽，导致 30s pool_timeout 后 500）。
    # 调大池并缩短超时，使并发更稳、失败更快（fail-fast 而非挂起）。
    # 注意：PG 默认 max_connections=100；本服务多为多 worker 部署，
    # 取值按「单 worker 30 连接」设定（如 2 worker 共 60，留足余量）。
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 10
    db_pool_recycle: int = 1800
    # ingestion 独立连接池（阶段3 待办收敛）：上行落库走独立池，与 HTTP API 流量隔离，
    # 避免千台设备洪泛时 ingestion 抢占 API 连接（维度⑥）。
    ingest_db_pool_size: int = 8
    ingest_db_max_overflow: int = 8

    # ---------- Redis ----------
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = ""
    redis_url: Optional[str] = None

    # ---------- MQTT（Mosquitto 原生，匿名可连） ----------
    mqtt_broker: str = "127.0.0.1"
    mqtt_port: int = 1883
    mqtt_username: str = ""
    mqtt_password: str = ""

    # ---------- 实时链路 ----------
    # 设备「在线」判定阈值（秒）：最近一次上报距当前不超过该值视为在线
    online_threshold_seconds: int = 300

    # ---------- 上行 ingestion 异步调度（阶段3 待办收敛：解耦接收与落库） ----------
    # 关闭则 on_message 直接同步处理（与历史行为一致）；开启后入队由工作线程池并行落库，
    # 队列满自动回退同步处理（不丢数据，仅退化吞吐）。
    ingest_enabled: bool = True
    ingest_workers: int = 4
    # 有界队列上限；超过即回退同步处理（背压），避免内存无限增长
    ingest_queue_max: int = 20000

    # ---------- MinIO 对象存储 ----------
    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "rail-monitor"
    minio_secure: bool = False

    # ---------- 高德地图 Web 服务 ----------
    amap_web_key: str = ""

    # ---------- MinIO 公网基址（部署相关） ----------
    # 留空则使用内部端点（开发机直连）；生产经 nginx /files/ 同源代理时
    # 设为 https://<域名>/files，presigned URL 会替换为主机部分以便浏览器直连。
    minio_public_url: str = ""

    @model_validator(mode="after")
    def assemble_urls(self) -> "Settings":
        if not self.database_url:
            self.database_url = (
                f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
            )
        if not self.redis_url:
            auth = f":{self.redis_password}@" if self.redis_password else ""
            self.redis_url = f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"
        # MinIO 公网基址缺省回退到内部端点（开发机直连）
        if not self.minio_public_url:
            scheme = "https" if self.minio_secure else "http"
            self.minio_public_url = f"{scheme}://{self.minio_endpoint}"
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins in ("*", ""):
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
