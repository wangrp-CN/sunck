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
    # API 限流（防爆破/防刷）：基于 Redis 固定窗口，按「路径+客户端IP」分桶
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    rate_limit_default: int = 200  # 单 IP 单分钟全站请求上限
    rate_limit_login: int = 10  # 单 IP 单分钟登录尝试上限（配合账户级锁定）
    rate_limit_captcha: int = 30  # 单 IP 单分钟验证码获取上限
    # 响应级短 TTL 缓存（阶段3 收尾·查询优化）：监控大屏 / 实时看板高频只读端点，
    # 以「user_id + 路径 + 查询串」为键缓存 3s，把并发重复聚合折叠为每窗口 1 次计算。
    # 测试环境默认关闭，避免跨用例缓存命中破坏隔离。
    resp_cache_enabled: bool = True
    # 操作审计中间件：对写操作（POST/PUT/PATCH/DELETE）自动落审计日志。
    # 测试环境默认关闭，避免用例间审计行累积干扰断言。
    audit_enabled: bool = True
    # 初始超级管理员（首次播种时写入，生产环境请通过环境变量覆盖）
    default_admin_username: str = "admin"
    default_admin_password: str = "Admin@123456"

    # ---------- 智能核心 / 阈值预警 ----------
    # 项目风险指数（0-100）达到该阈值即触发预警通知（站内信），默认 60（对应风险分档"高"起点）。
    risk_alert_threshold: int = 60

    # ---------- 智能核心 / 跨设备根因关联 ----------
    # 关联聚类回溯窗口（小时）：仅聚合该窗口内的告警。
    correlation_window_hours: int = 24
    # 时间窗聚类间隔（分钟）：相邻告警间隔超过该值即拆分为新的事件组。
    correlation_gap_minutes: int = 30
    # 对比大屏关联热力：单次对比允许的最大时间窗跨度（天），防止超大窗口重算拖垮查询。
    correlation_compare_max_days: int = 180
    # 跨设备共因事件的 WebSocket 实时推送开关（Redis Pub/Sub 桥接，见 app/ws/correlation_pubsub）。
    ws_correlation_enabled: bool = True
    # 跨设备共因事件 WS 推送指纹去重 TTL（秒）：同一共因在该窗口内只推送一次，
    # 避免每日重算反复轰炸。可据业务节奏调小（更灵敏）或调大（更稳）。默认 7 天。
    correlation_fp_ttl_seconds: int = 7 * 86400
    # 关联指纹去重总开关：关闭后每次重算均推送（仅用于调试/重放）。默认开启。
    correlation_dedup_enabled: bool = True
    # 告警风暴抑制窗口（秒）：同一 (设备, 类型, 围栏, 状态) 在该窗口内只产生 1 条告警，
    # 后续重复被合并并计入 anchor 的 suppressed_count（见 app/service/alarm_service）。
    alarm_suppress_window_seconds: int = 300

    # ---------- 智能核心 / 视频 AI 异常识别（接口预留，待能力接入） ----------
    # 平台自身不做推理，异常识别由外部 AI 盒子/推理服务完成并经 /videos/events/ingest
    # 回推。video_ai_enabled 仅作为"能力就绪"开关；能力接入前 /videos/ai/analyze 返回
    # pending_capability 占位，便于前端/编排层提前对接接口契约。
    video_ai_enabled: bool = False
    # 外部推理服务地址（深化⑧）：配置后 /videos/ai/analyze 将转发分析请求并返回真实识别结果；
    # 为空则能力启用但保持 not_implemented 占位。建议使用内网/服务账号鉴权的 AI 盒子地址。
    video_ai_endpoint: str | None = None
    # 推理服务调用超时（秒）：超时即优雅降级为占位，不阻塞主流程。
    video_ai_timeout_seconds: float = 5.0

    # 视频 AI 事件自动升级为平台告警（深化⑧）：外部推理回推的高危/高置信事件在
    # ingest 时自动建一条平台告警并回填 video_event.alarm_id，闭合「监测→异常→告警」
    # 链路。手动「升级为告警」不受此开关限制，独立于自动升级始终可用。
    video_auto_escalate_enabled: bool = False
    video_auto_escalate_threshold: float = 0.8

    # ---------- 短信 / 语音网关（P2① · 模拟真实数据，可切换真实网关） ----------
    # mode: simulate(默认，模拟真实回执，无需任何第三方凭据) | real(需配置 provider 凭据)
    # 真实模式仅当对应 *_api_key 配置后才发起真实调用；凭据缺失回执 status=not_configured。
    # provider: mock(默认) | aliyun | tencent（real 模式下生效；双厂商抽象见 app/core/gateways.py）。
    sms_mode: str = "simulate"
    sms_provider: str = "mock"
    sms_api_key: str | None = None  # 阿里云 AccessKeyId / 腾讯云 SecretId
    sms_api_secret: str | None = None  # 阿里云 AccessKeySecret / 腾讯云 SecretKey
    sms_sign_name: str = "涉铁安全监控"  # 阿里云/腾讯云 短信签名
    sms_template_code: str | None = None  # 阿里云短信模板 CODE
    sms_app_id: str | None = None  # 腾讯云短信 SmsSdkAppId
    sms_template_id: str | None = None  # 腾讯云短信 TemplateId
    tencent_region: str = "ap-guangzhou"  # 腾讯云地域（短信/语音共用）
    voice_mode: str = "simulate"
    voice_provider: str = "mock"
    voice_api_key: str | None = None
    voice_api_secret: str | None = None
    voice_template_code: str | None = None  # 阿里云语音 TtsCode
    voice_app_id: str | None = None  # 腾讯云语音 VoiceSdkAppid
    voice_template_id: str | None = None  # 腾讯云语音 TemplateId
    voice_called_show_number: str | None = None  # 阿里云语音显号（主叫号码）

    # ---------- 设备指令下发闭环（状态追踪 + 回执 + 重试） ----------
    # 平台向设备下发指令后等待回执的超时（秒）：超过该时长仍未回执视为可重试。
    command_ack_timeout_seconds: int = 60
    # 单条指令的最大自动重试次数（达到后状态置为 failed，不再自动重试）。
    command_max_retries: int = 3

    # ---------- 智能核心 / 趋势异常检测（统计基线法） ----------
    # z-score 阈值：单点偏离其之前滚动基线超过 k 个标准差即判异常（k 越大越严格）。
    anomaly_k: float = 2.0
    # 滚动基线窗口（不含当前点，单位：周期）。
    anomaly_window: int = 7
    # 单点判异常所需的最少历史样本数（历史不足则跳过该点，防误报）。
    anomaly_min_trailing: int = 3
    # 序列最短长度，低于此整条不判异常（防 2~3 点的误报）。
    anomaly_min_points: int = 5
    # 定时检测回看窗口（天）：每日定时对近 N 天的日序列做异常检测（须 > window+min_points）。
    anomaly_lookback_days: int = 30

    # ---------- 智能核心 / 风险预测（Phase 5 预测基座） ----------
    # 预测跨度（天）：对快照序列外推未来 N 天。
    forecast_horizon_days: int = 7
    # 拟合回看窗口（天）：取近 N 天快照序列做 OLS 拟合。
    forecast_history_days: int = 30
    # 最少样本数：序列点数低于此不出预测（防 1~2 点直线误导）。
    forecast_min_points: int = 3
    # 回测窗口（天）：walk-forward 回测使用的历史锚点范围。
    forecast_backtest_days: int = 90
    # 上线默认预测模型版本：ols_v1(原 OLS) | hw_v1(Holt-Winters 季节趋势)。
    # hw_v1 经 A/B 命中率报表验证后已于 2026-07-31 正式设为默认；如需回退可设
    # 环境变量 FORECAST_PRIMARY_MODEL=ols_v1 或 POST /v1/forecasts/model/default 一键切换。
    forecast_primary_model: str = "hw_v1"

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
    # 默认 12（阶段④压测甜点：千台@2s≈497msg/s 下，配合 Mosquitto max_queued_messages=100000，
    # 端到端落库率 ≈100% 且读延迟显著低于 workers=16 配置；详见 STRESS_TEST_REPORT.md §7.5/§7.6）。
    ingest_db_pool_size: int = 12
    ingest_db_max_overflow: int = 8
    # 读/看板独立连接池（基础设施审计·③）：dashboard 大屏聚合 + realtime 实时只读端点
    # 走独立池，与 API 写事务池（engine）隔离，避免重查询在高并发下挤占写连接。
    # 同一 PostgreSQL 实例、同步复制，读池立即可见已提交写，无复制滞后。
    read_db_pool_size: int = 10
    read_db_max_overflow: int = 10
    read_db_pool_timeout: int = 10
    read_db_pool_recycle: int = 1800

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
    # 默认 8：千台@2s 洪泛下 ≈62 msg/s/worker 远超峰值需求，落库率≈100% 且读延迟(中位70ms)
    # 优于 16 worker(110ms)；仅在上行翻倍(数千设备/更短间隔)追不上时才需上调（§7.5/§7.6）。
    ingest_workers: int = 8
    # 有界队列上限；超过即回退同步处理（背压），避免内存无限增长
    ingest_queue_max: int = 20000
    # 落库批处理（基础设施审计 · ④）：工作线程攒批，单会话一次性 commit，
    # 显著降低千台洪泛下的 WAL/commit 开销。凑满 batch_size 或等待 max_wait 秒即 flush。
    # 批失败整体回退逐条处理（保活，不丢数据）。0 表示关闭批处理（退化为逐条）。
    ingest_batch_size: int = 200
    ingest_batch_max_wait: float = 0.5

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


def assert_production_safe() -> None:
    """生产环境安全护栏：存在不安全默认值时**拒绝启动**（fail-closed）。

    仅当 app_env == "production" 时生效，避免误伤开发/测试环境。
    校验项：
      - secret_key 不得为默认占位值（否则 JWT 可被伪造）
      - CORS_ORIGINS 不得为通配 '*'（否则任何站点可携带用户凭据跨域调用）
      - debug 不得为 True
    轮换 secret_key 的取舍：当前 JWT 无吊销列表，轮换会使全部存量令牌立即失效
    （全体用户需重新登录），属可接受的安全实践；请在低峰期操作并提前通知。
    """
    if settings.app_env != "production":
        return
    errors: list[str] = []
    if settings.secret_key in ("change-me-to-a-long-random-string", ""):
        errors.append("secret_key 仍为默认占位值，请设置强随机值（如 `openssl rand -hex 32`）")
    if settings.cors_origins in ("*", ""):
        errors.append("生产环境 CORS_ORIGINS 不能为通配 '*'，请指定可信前端域名（逗号分隔）")
    if settings.debug:
        errors.append("生产环境 debug 应为 False")
    if errors:
        raise RuntimeError("生产环境配置不安全，拒绝启动：\n- " + "\n- ".join(errors))


settings = Settings()
