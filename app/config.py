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
