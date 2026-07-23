# CHANGELOG · 涉铁工程智能监控平台（rail_monitor）

记录各阶段交付与关键变更。告警可视化方向以「趋势 → 导出 → 快照 → 大屏联动」闭环为主线。

---

## [2026-07-23] 基础设施加固（告警复合索引 + DB 连接池指标）

> 基础设施四维审计后的首个小包（① 查询索引缺口 + ② 连接池监控盲区）。补齐告警时序/状态查询索引，并首次把 DB 连接池饱和度纳入 Prometheus 可观测，为后续「read/看板独立池」决策提供数据支撑。

### 1) 告警复合索引（缓解趋势/近期/看板慢查询）
- 手写迁移 `alembic/versions/k5l6m7n8o9p0_add_alarm_indexes.py`（`down_revision=j4k5l6m7n8o9`）：
  - `ix_alarm_alarm_time(alarm_time)`：`alarm_time` 是 range 过滤/order_by/trend group_by 核心列，原无索引。
  - `ix_alarm_handle_status_time(handle_status, alarm_time)`：看板「待处理计数」与「按状态取近期」复合过滤。
- `app/model/alarm.py`：补 `__table_args__` 索引定义，使 ORM metadata 与迁移一致。

### 2) DB 连接池 Prometheus 指标（池监控盲区补齐）
- `app/core/metrics.py`：新增 `db_pool_checkedout / checkedin / size / overflow / capacity`(Gauge) + `db_pool_checkout_total`(Counter) + `db_pool_connect_latency_seconds`(Histogram)，均带 `pool=api|ingest` 标签；`update_pool_metrics()` 在抓取时从 `engine.pool` 实时写 Gauge。
- `app/core/database.py`：双引擎（API 池 + 独立 ingest 池）注册 PoolEvents —— `checkout` 计次、`do_connect/connect` 配对测物理连接建立时延。
- `app/main.py`：`/metrics` 端点抓取前调用 `update_pool_metrics()`。
- 饱和度主信号：`db_pool_checkedout` 接近 `db_pool_capacity`(=pool_size+max_overflow) 即池将耗尽（api=30 / ingest=16）。

### 3) 测试与门禁
- 新增 `tests/test_db_pool_metrics.py`：指标注册+实时写入（容量断言 api=30/ingest=16）、alarm 两索引存在性、`/metrics` 端点暴露 `db_pool_*`。
- ruff / ruff-format 通过；DB 重测试 37 项全绿（告警生命周期/分页/看板聚合/实时等）；`alembic upgrade head` 干净。

---

## [2026-07-22] 业务闭环收口（告警→隐患一键转工单 + 站内信通知中心）

> 在「隐患治理闭环」模块基础上，打通**监测→治理**全链路：告警一键转为隐患工单（双向溯源），新告警触发站内信通知，前端「告警管理」内嵌转隐患弹窗、全局铃铛抽屉实时查看与已读。SMS / 语音通道预留适配器，待第三方凭据就绪即可启用。

### 1) 告警→隐患一键转工单（双向溯源）
- `app/model/hazard.py`：新增 `source_alarm_id`(FK→alarm, SET NULL, 索引)，记录隐患来源告警。
- `app/model/alarm.py`：新增 `hazard_id`(FK→hazard, 索引)，标记该告警已转出的隐患工单。
- 手写迁移 `alembic/versions/i3j4k5l6m7n8_add_alarm_hazard_link.py`（`down_revision=h2i3j4k5l6`）：双向 FK + 索引。
- `app/core/constants.py`：新增 `ALARM_LEVEL_TO_HAZARD_LEVEL`(严重→重大/警告→较大/提示→一般)。
- `app/schema/hazard.py`：`HazardOut` 暴露 `source_alarm_id`。
- `app/service/hazard_service.py`：`convert_alarm_to_hazard()`（重复转换报业务码 400）、`to_hazard_out` 回填来源。
- `app/service/alarm_service.py`：`to_alarm_out` 暴露 `hazard_id`；`create_alarm` 落库后触发通知。
- `app/api/v1/alarms.py`：新增 `POST /{alarm_id}/convert-to-hazard`（`alarm:handle` + 数据范围校验）。
- `tests/test_alarm_to_hazard.py`(2 用例)：默认转换 + 覆盖字段；已转不可重复（硬删 fixture）。

### 2) 站内信通知中心（自解释，无部门隔离）
- `app/model/notification.py`（新）：`Notification`(user_id CASCADE、channel in_app/sms/voice、category、title/content/link/is_read)。
- 迁移 `alembic/versions/j4k5l6m7n8o9_add_notification.py`（`down_revision=i3j4k5l6m7n8`）：user_id/channel/category/is_read 索引。
- `app/core/notify.py`（新）：`InAppNotifier`（写库）、`SmsNotifier`/`VoiceNotifier`（预留桩：记日志+写库，待第三方凭据）；`notify_alarm_raised()` 向全部在职用户广播「新告警」站内信（MVP 广播，后续按项目/角色收窄）。
- `app/schema/notification.py`（新）：`NotificationOut`(北京墙钟序列化) + `NotificationPage`(total/unread/items)。
- `app/api/v1/notifications.py`（新）：`GET /`(列表+未读数)、`GET /unread-count`、`POST /{id}/read`、`POST /read-all`，均按当前用户自过滤、仅需登录。
- `app/api/router.py`：挂载 `prefix="/v1/notifications"`（插在 hazards 后）。
- `tests/test_notification.py`(2 用例)：列表/已读、告警创建触发通知；autouse 清空 fixture。

### 3) 前端（Vue3 + ElementPlus）
- `web/src/api/notification.ts`（新）：通知中心 API 封装 + 类型。
- `web/src/api/alarm.ts`：新增 `convertAlarmToHazard` + `AlarmToHazardRequest`。
- `web/src/types/index.ts` & `web/src/api/realtime.ts`：`Alarm`/`AlarmItem` 补 `hazard_id`（来源溯源/「已转隐患」标签）。
- `web/src/views/AlarmView.vue`：操作列加「转隐患」按钮 + 「已转隐患」标签；转隐患弹窗（标题/等级/类别/项目/责任人/期限/位置/描述，预填告警派生值，提交后跳转隐患治理页）。
- `web/src/layouts/DefaultLayout.vue`：顶栏铃铛 + 未读角标 + 通知抽屉（全部/未读切换、单条/全部已读、点击有 link 则跳转），挂载后每 30s 轮询未读数。

### 4) 测试护栏（全绿）
- 后端：`test_alarm_to_hazard.py` + `test_notification.py` 共 4 用例全绿（分批运行 pytest 全绿，1 skip）。
- 前端：`AlarmView.spec.ts` 补 `@/api/person`、`convertAlarmToHazard` mock 与 `vue-router` 桩；`vitest run` 84 用例全绿，`vue-tsc` 类型检查无错，`npm run build` 通过。

---

## [2026-07-22] 隐患治理闭环（新业务模块 · C 轨道「按需新业务模块」）

> 端到端落地「隐患治理闭环」模块，与既有「告警（系统自动触发）」互补：隐患由人工/巡检发现，走「待整改→整改中→待复核→已销号」状态机，含驳回/重开分支，并支持超期预警与多维统计。

### 1) 数据模型与迁移
- 新增 `app/model/hazard.py`：`Hazard` ORM（混用 `TimestampMixin`/`CreatorMixin`/`SoftDeleteMixin`），含 `project_id`(FK→project, VIA_PROJECT)、`level`/`category`/`source`/`status`、`lng`/`lat`(WGS-84)、`discovered_by_name`/`discovered_at`、`assignee_id`(FK→person)、`due_at`、`rectify_*`/`verify_*`/`closed_at` 留痕字段。
- 手写 Alembic 迁移 `alembic/versions/h2i3j4k5l6_add_hazard_table.py`（`down_revision=g1h2i3j4k5l6`），仅含 hazard 表（25 列 + 6 索引），已 `alembic upgrade head` 应用。

### 2) 枚举 / 状态机
- `app/core/constants.py`：新增 `HAZARD_LEVELS`(重大/较大/一般/低)、`HAZARD_CATEGORIES`、`HAZARD_SOURCES`(人工/巡检/系统)、`HAZARD_STATUSES` 及 `HAZARD_TRANSITIONS`（`start_rectify`/`submit_rectify`/`verify_pass`/`verify_reject`/`reject`/`reopen`）、`HAZARD_TERMINAL_STATUSES={已销号}`。
- `app/service/hazard_service.py`：`transition_hazard` 按状态机校验合法性，按动作写入 rectify/verify/closed 留痕；`_is_overdue`=非终态且 `due_at` 早于当前 UTC。

### 3) 接口与权限（部门数据隔离沿用四级 DataScope / VIA_PROJECT）
- `app/api/v1/hazards.py`：`GET /ping`、`GET /options`(枚举)、`GET /stats`、`GET /`(筛选+分页)、`POST /`(创建)、`GET /{id}`、`PUT /{id}`、`DELETE /{id}`(软删)、`POST /{id}/transition`；权限 `hazard:list/create/update/delete/handle`（超管自动通过）。
- `app/api/router.py`：挂载 `prefix="/v1/hazards"`，插在 alarms 路由后。
- 时间字段对外统一「北京时间墙钟」ISO 序列化（复用 job 写法）。

### 4) 前端（Vue3 + ElementPlus + MapPanel）
- `web/src/api/hazard.ts`：`fetchHazards/createHazard/updateHazard/deleteHazard/transitionHazard/fetchHazardStats/fetchHazardOptions` 及类型。
- `web/src/views/HazardView.vue`：列表 + 筛选(项目/等级/状态/关键词/仅看超期) + 统计卡片 + 权限门控按钮 + 创建/编辑对话框(MapPanel 打点 + 双日期选择) + 状态流转对话框(按当前状态给可选动作) + 等级/状态标签；列表默认按 id 倒序（最新在前）。
- `web/src/router/index.ts` + `web/src/layouts/DefaultLayout.vue`：新增「隐患治理」路由与菜单项（Bell 图标）。

### 5) 测试护栏（全绿）
- `tests/test_hazard.py`(5 用例)：CRUD + 状态机闭环(含非法流转业务码 400) + 驳回/重开 + 超期/统计 + 软删隔离 + 等级筛选；autouse fixture 硬删测试数据，避免污染 dev DB。
- `web/src/views/HazardView.spec.ts`(6 用例)：挂载加载、筛选回第 1 页、新增/流转/删除调用、权限门控。
- 门禁：后端 `pytest -q` 全绿（含 1 skip），前端 `vitest run` 84 用例全绿，`npm run build` + `vue-tsc` 类型检查通过。

---

## [2026-07-22] 可观测性面板 + 部署文档增强（B 轨道收尾）

> 在 `/metrics` 已就绪的基础上，补齐可直接导入的 Grafana 面板与本地演练文档，令生产化验证（B 轨道）闭环。

### 1) Grafana 监控面板（`deploy/grafana-dashboard.json`）
- 基于后端真实业务指标定制 11 个面板 / 18 条 PromQL，参数化 `${datasource}`，Grafana 一键 Import。
- 四组：**服务概览**（WS 连接 / QPS / 5xx 错误率 / 队列积压）、**HTTP 流量与时延**（速率按状态码 + P50/P95/P99）、**业务指标**（`alarms_created_total` 按类型 / `mqtt_messages_total` 按设备类型）、**异步 Ingestion 管线**（`ingest_*` 吞吐/背压/处理时延/`ingest_queue_size` 积压）。

### 2) 部署文档（`README.deploy.md`）
- 新增「7. 可观测性（Prometheus + Grafana）」：完整指标清单表 + Prometheus 抓取 + Grafana 导入步骤。
- 新增「9. 本地验证记录（macOS 无 systemd）」：固化 nginx 等效真起演练命令（高端口 + 临时 prefix，反代/WS 升级/MinIO 同源代理/安全头探针全绿）。

---

## [2026-07-22] 功能模块优化（告警批量处置 / 列车接近专项 / 作业计划校验联动）

> 按用户「下一步开始功能模块优化」推进，覆盖四项：告警批量处置、告警自动结束防堆积、列车接近专项告警、作业计划校验/联动深化。

### 1) 告警批量处置（后端 + 前端）
- 新增 `POST /api/v1/alarms/batch-handle`（`alarm:handle` 权限）：按 `apply_data_scope` 过滤当前用户数据范围内的告警，循环 `handle_alarm` 处置；范围内置「已消警」的告警下发 MQTT 消警指令；范围外 id 自动跳过。返回 `{handled, skipped, results}`。
- 前端 `AlarmView.vue`：表格增加 `type="selection"` 勾选列（跨页 `reserve-selection`，`row-key="id"`）+ 批量工具条（已选计数 + 处置状态选择 + 「批量处置」/「清空选择」）；新增 `web/src/api/alarm.ts` 的 `batchHandleAlarms`。

### 2) 告警自动结束防堆积（验证 + 回归测试）
- 机制由前置工作 `pipeline.reconcile_active_alarms`（Redis `rule2:active:{device_no}` 配对打开/结束告警）实现，本轮补充回归测试 `test_alarm_auto_end_on_violation_cleared` 实证「违规解除 → 告警自动置『告警结束/已消警』」。

### 3) 列车接近专项告警
- 新增告警类型 `train_approach`（常量 `ALARM_TYPE_TRAIN`，级别「严重」，标签「列车接近预警」）。
- `rule_engine_v2.build_alarm_candidates_v2` 新增 `DEVICE_TYPE_TRAIN_APPROACH` 分支：计划 `trigger_conditions` 含 `train_approach` 时产出专项告警（区别于通用 `device_alarm` 兜底）；受 `ALARM_TYPE_TRAIN in triggers` 门控。

### 4) 作业计划校验 / 联动深化
- **跨项目绑定校验**：`jobs.create_job`/`update_job` 调用新增 `_validate_bindings_project`，校验绑定的人员/机械/围栏归属本计划项目，越界抛 `BusinessError(code=400)`（如「以下人员不属于本项目」）。
- **甘特实际时间回填**：`WorkPlan` 新增 `actual_start`/`actual_end`（timestamptz，Alembic `g1h2i3j4k5l6`）；`start_job` 回填 `actual_start`(启动时刻)、`complete_job` 回填 `actual_end`(完成时刻)，`_to_out` 序列化输出，供甘特进度联动。
- **monitor_target 门控**：`_location_triggers_enabled` 对围栏/间距触发做设备类别约束——仅当 `monitor_target` 为结构化单一取值（`person`/`machine`/`train`）且设备类别一致时启用；自由文本/组合历史值（如「人员/设备」）回落「不受限」，保持历史行为一致、不误伤既有数据。

### 回归验证
- 新增 `tests/test_functional_modules.py` 覆盖上述 6 项（批量处置 / 列车接近专项 / monitor_target 门控纯函数 / 跨项目绑定 / 甘特实际时间 / 告警自动结束）。
- 全量后端 gate 复跑通过；`ruff` 通过；前端 `vue-tsc` + `vitest`(78) + `build` 全绿。

---

## [2026-07-22] 维度⑥ 收尾 · Locust 千台压测实证（优化后真实端点 0% 失败 / 中位 35ms）

> 同口径复跑阶段3「1000 设备@2s(≈495 msg/s) + 100 查看者」全并发组合，闭环维度⑥。完整数据见 `STRESS_TEST_REPORT.md`。

- **HTTP 查看者负载（Locust 120s/100 并发）**：真实端点 **0% 失败**，聚合中位 **35ms**（dashboard/stats 24ms、realtime/locations 31ms、alarms 38ms），吞吐 **47.97 req/s**。
  - 对比优化前：场景 A 64.96% 返回 500 / 中位 32s；场景 D(仅池调优) 中位仍 9.1s / 吞吐 8.16 req/s → **中位时延降约 260×~900×、吞吐升 5.9×**。
- **千台设备上行（mqtt_flood 153s）**：发布 **76,000 条 @ 495.4 msg/s，发布端 0 错误**；应用层 ingestion **0 异常**（有界队列+同步回退背压，零丢失），落库 66,443 行。
- **端到端落库率 87.4%**（66,443/76,000）：缺口 ~9,557 条发生在 **Mosquitto broker 侧**——默认 `max_queued_messages=1000` 在「100 查看者 + 1000 设备@495/s」并发挤占 PG 共享容量、ingest 工作线程变慢时溢出丢弃（应用层已收到并存入的 66,443 行在洪泛停止后冻结不再增长，证明 0 在途积压）。**非应用层数据丢失**，为 broker/PG 容量调优项。
- **调优建议（非阻塞，已写入报告 §6）**：① 调大 Mosquitto `max_queued_messages`；② 提高 `INGEST_WORKERS`(默认4)/`INGEST_DB_POOL_SIZE`(默认8) 以追上峰值；③ ingestion 走独立 PG 实例/副本；④ `device_location` 时间分区。
- **复现**：`scripts/seed_stress.py` → 后台 `mqtt_flood.py --devices 1000 --interval 2 --duration 150` → `locust -f scripts/locustfile.py ViewerUser --headless -u 100 -r 20 -t 120s` → `seed_stress.py clean`。
- 路线图维度⑥ 状态更新为 ✅ 已收尾。

---

## [2026-07-22] 查询性能优化（消残余 ~9s 中位时延）：latest_locations 重写 + 重端点 3s TTL 响应缓存

> 阶段3 压测报告（场景 D·池调优后）仍测得 dashboard/stats、realtime/* 等高频只读端点 **~9.1s 中位延迟**。本条目消除该残余时延。

- **诊断（实证推翻「缺索引」假设）**：50 万行下四个主查询（dashboard stats / online-status / latest_locations / 窗口活跃设备）均已走索引（单条 87–570ms），尝试补的 `(report_time, device_no)` 是冗余索引（admin 路径已被现有 `(device_no,report_time)` 的 Index Only Scan 覆盖）。
  - 决定性并发实测（50 万行、单 worker 30 连接池）：单请求 `/stats` 1374ms、50 并发中位 **12602ms** / P95 14969ms / 吞吐 **3.3 req/s** —— 与压测报告 ~9s 吻合；主因是并发下大量重复聚合计算 + 连接池争用，非索引缺失。
- **优化①：`app/service/location_service.py` 的 `latest_locations` 重写**。
  - 原 `DISTINCT ON (device_no) ORDER BY device_no, id DESC` 在 9.9 万行上触发全表 Seq Scan + 排序溢写 36MB 磁盘。
  - 改为 `GROUP BY device_no` 取 `max(id)` 子查询 + 主键回表（`SELECT ... JOIN subq ON id = max_id`），避免排序，走现有 `(device_no,id)` 索引；保留 `project_id` / `device_type` 过滤。
- **优化②：新增 `app/core/cache.py` 轻量 HTTP 响应缓存（Redis 支撑）**。
  - 监控大屏 / 实时看板类高频只读端点，以「`user_id` + 路径 + 查询串」为键做 **3s TTL** 缓存，把 N 个并发请求折叠为每窗口 1 次真实计算。
  - 键含 `user_id` → 部门数据隔离天然生效；TTL 短 → 监控数据允许秒级陈旧；任何异常（Redis 不可用）静默降级为「不缓存、直接放行」。
  - 接入端点：`/api/v1/dashboard/stats`、`/api/v1/realtime/locations`、`/api/v1/realtime/online-status`（均加 `Request` / `current_user` 依赖 + 缓存读写）。
  - 开关 `RESP_CACHE_ENABLED`（默认 true，`.env.example` 同步），`tests/conftest.py` 关闭以避免跨用例缓存命中破坏隔离。
- **回归修复（关键）**：`Request` 须以 `request: Request` 平铺声明，**不可**写成 `request: Request = Depends()`（后者被 FastAPI 误判为 body 模型，导致 `GET` 端点 422「body required」）；且非默认参数须排在带默认参数之前。
- **实证复测（同口径 50 万行）**：单请求 `/stats` **10.9ms**、50 并发中位 **117ms** / P95 **156ms** / 吞吐 **285.8 req/s** —— 时延降 **~108×**、吞吐升 **~86×**，残余 ~9s 已实证消除。
- **验证**：全量后端 gate 复跑通过（修复缓存隔离 + Request 声明后无回归）；`ruff` 通过。
- 备注：压测遗留 50 万行（project_id=99001）将于本轮收尾清理。

## [2026-07-22] 千台压测落库率实证（维度⑥ 收口：0.7% → 100%）

> 重启加载新代码的后端，跑 `scripts/mqtt_flood.py` 实证阶段3 暴露的「千台设备 0.7% 落库率」瓶颈是否已收敛。

- 环境：PG / Redis / MQTT 原生服务 running；后端 `uvicorn app.main:app --port 8000`（`CAPTCHA_ENABLED=false`），新代码 ingestion 工作池 `workers=4 queue_max=20000` 已激活，MQTT 已订阅 `device/+/up`。
- 负载：`scripts/seed_stress.py` 登记 1000 台 `LOC-S#####` 设备（无激活计划，仅落库 `DeviceLocation`，隔离 ingestion 压力）；`mqtt_flood --devices 1000 --interval 2 --duration 90` 发布 **45,750** 条（0 发布错误，~491 msg/s）。
- 结果（队列完全排空后）：`ingest_enqueued=45750` / `ingest_processed=45750`（=100%）/ `ingest_errors=0` / `ingest_inline_total=0`（队列从未溢出回退）/ `ingest_queue_size=0`；`DeviceLocation` 实际行数 **45,750**（与发布量精确相等），**1000/1000 设备全部落库**。
- 结论：相对阶段3 基线 **0.7% 落库率 → 100%**，维度⑥ 性能稳定根因项已实证收敛。瓶颈（paho 单线程串行 + 连接池争用）由异步调度层 + 独立落库池消除。
- 验证后已 `scripts/seed_stress.py clean` 清理压测数据；新代码后端保留运行（PID 78152）。

## [2026-07-22] 上行 ingestion 异步调度层（维度⑥ 收尾：收敛阶段3 待办）

> 四轨道 A/B/C/D 已于本日早些时候收官（见下条）。本条目为路线图维度⑥性能稳定的进一步加固：把「接收」与「落库」解耦，从根本上消除千台设备洪泛时的单线程串行 + 连接池争用瓶颈（阶段3 压测根因侧修复，非仅池扩容）。

- 新增 `app/core/ingest.py`：有界队列 + 工作线程池。`on_message` 仅做解析 + 入队（极快、立即 ack），由 N 个工作线程并行调用既有 `pipeline.handle_upstream`；落库 / 规则引擎 / 告警去重 / 跨线程 WS 推送逻辑**零改动**。
- 安全保障（不丢数据）：队列满自动回退同步处理（背压，仅退化吞吐）；未启用（`INGEST_ENABLED=false`）或未 start 时 `enqueue` 直接同步（等价于历史行为）；关闭时先排空在途报文再停线程池。
- `app/main.py` lifespan 接入 `ingest_start()/ingest_stop()`（均 try/except 不阻断启动/关闭）；`app/mqtt/handlers.py` 由直接 `handle_upstream` 改调 `ingest.enqueue`。
- 配置项：`INGEST_ENABLED`(默认 true) / `INGEST_WORKERS`(默认 4) / `INGEST_QUEUE_MAX`(默认 20000)，已写入 `.env.example`。
- 指标：新增 `ingest_enqueued_total` / `ingest_processed_total` / `ingest_errors_total` / `ingest_inline_total`(背压回退) / `ingest_queue_size`(Gauge) / `ingest_process_duration_seconds`，由 `deploy/prometheus.yml` 已配置的 `/metrics` 抓取。
- 测试：`tests/test_ingest.py`（3 用例，mock 处理器，无需 PG/Redis）：验证异步工作线程路径、队列满回退同步、stop 排空在途、未启用同步回退；`ruff` 通过。
- 待办（非阻塞，可后续增强）：ingestion 独立连接池以隔离 API 流量、查询索引/缓存消残余 ~9s 中位时延。

## [2026-07-22] ingestion 独立连接池（维度⑥ 收尾：收敛阶段3 待办②）

> 接续上条异步调度层，进一步把上行落库与 HTTP API 流量在连接层隔离，避免千台设备洪泛时互相争用 PG 连接。

- `app/core/database.py` 新增独立引擎 `ingest_engine` + `IngestSessionLocal`（池 `INGEST_DB_POOL_SIZE=8` / `INGEST_DB_MAX_OVERFLOW=8`，复用 `db_pool_timeout/recycle`）。
- `app/service/pipeline.py` 的 `handle_upstream` 新增可选 `sessionmaker_factory` 形参（默认 `SessionLocal`，向后兼容）；由 ingestion 工作线程调用时传入 `IngestSessionLocal`。
- `app/core/ingest.py` 默认处理器经包装把上行交给 `handle_upstream(..., sessionmaker_factory=IngestSessionLocal)`，落库走独立池。
- 连接估算：N 个 API worker ×(10+20) + 1 个 ingest 池(8+8) ≤ PG `max_connections=100` 留余量。
- 测试：`tests/test_ingest.py` 增至 4 用例（新增 `test_default_processor_uses_ingest_pool`，monkeypatch 真实处理器验证传入 `IngestSessionLocal`，免 PG）；`ruff` 通过。
- 验证：全量后端 gate 复跑 `135 passed / 1 skipped`（无回归）。
- 剩余待办（非阻塞）：查询索引/缓存消残余 ~9s 中位时延；建议以 `RUN_E2E=1` + `scripts/mqtt_flood.py` 复测千台落库率做实证收口。



## [2026-07-22] 四轨道计划（A/B/C/D）收官：质量加固 + 生产化 + 压测 + 文档治理

> 阶段0~3 对应四轨道计划 #195–#203（2026-07-21 起全选推进）。本条目为各阶段交付与结论总览，路线图见文末「阶段基线」。

### 阶段0 依赖审计（A/D 前置）
- 前端 `npm audit --omit=dev` 0 漏洞；后端 `pip-audit` 仅 dev 工具 `black 24.8.0` 报 2 项中危（fix≥26.3.0），运行时依赖 0 漏洞。沙箱 ensurepip 崩溃致 `-r` 建 venv 不可用，改用「临时装 pip-audit 进 .venv → 直扫环境 → 卸载还原」。
- 提交 `16a7d89`。

### 阶段1 质量加固（A）
- 前端补全 6 个核心视图 Vitest 单测（DashboardView / AlarmView / FenceView / TrackView / RealtimeView / DeviceOnlineView）。提交 `d0ee680`。
- 后端补全 5 个 router 集成测（在线状态 / 甘特 / WS 推送等）。提交 `6981fda`。
- 沿用既有护栏：后端 pytest 116+ 用例、前端 Vitest 55+ 用例全绿；`npm run type-check`（vue-tsc）无错。

### 阶段2 生产化验证（B）
- 修复生产形态硬伤：`nginx.conf` 的 `proxy_pass` 去尾斜杠（原尾斜杠剥离 `/api`、`/ws` 前缀致全 404）；`web/src/utils/ws.ts` 改从 `window.location` 推导 `ws/wss`+host（去硬编码 `:8000`）；前端 `root` 由开发机路径改 `/opt/rail_monitor/web/dist`；新增 `MINIO_PUBLIC_URL` 让 presigned 走 `/files` 基址（闭环媒体匿名缺口）；`prometheus.yml` 由 `host.docker.internal` 改 `127.0.0.1:8000`；`.env`/`.env.example` 移除未用 `CELERY_*`。
- 本地校验：`nginx -t` 通过、pytest 136+1skip、`type-check` 零错。
- 提交 `0bf9411`；`README.deploy.md` / `.env.example` 同步生产说明。

### 阶段3 功能演进 · 千台设备压测（C）
- 新增 `scripts/seed_stress.py`（登记 1000 台 `LOC-S` 设备 + `clean` 清理）、`scripts/mqtt_flood.py`（线程池 MQTT 上行洪泛，规避 Locust gevent/paho 冲突）、`scripts/locustfile.py`（`ViewerUser` HTTP 负载，admin 同源令牌绕过验证码）。
- 报告：`STRESS_TEST_REPORT.md`。
- **根因（重负载 65% HTTP 500）**：SQLAlchemy 默认连接池 5+10=15，叠加同步 per-message ingestion（每条上行开会话/commit）抢光池，`pool_timeout=30s` 后 500；61k 上行仅 456 落库（0.7%）。
- **修复并验证**：`app/config.py` 新增 `db_pool_size=10/max_overflow=20/pool_timeout=10/pool_recycle=1800`（单 worker 30 连接，2-worker 聚合 60 < PG `max_connections=100` 留余量）；`app/core/database.py` 接入引擎。端口 8011 验证：真实端点 0% 失败、吞吐 1.82→8.16 req/s（4.5×）。
- **待办（非阻塞）**：ingestion 异步/批处理（根本解法，解决 0.7% 落库）、查询索引/缓存（残余 ~9s 中位延迟）、ingestion 独立连接池、pool 饱和度监控。
- 提交 `dbf042f`（6 文件 +438 行）。压测后 `seed_stress.py clean` 清理、停临时 8011 后端；8000 开发后端不受影响。

### 阶段4 文档治理（D）
- 路线图（CHANGELOG「阶段基线」）标注 A/B/C/D 四轨道全部 ✅。
- CHANGELOG 补齐阶段0~4 交付与结论（本条目）。
- 记忆归档：`.workbuddy/memory/` 更新四轨道收官状态（项目内部数据，不入库）。

### 交付与 CI
- 提交链：`16a7d89`(阶段0) → `d0ee680`(阶段1 前端) → `6981fda`(阶段1 后端) → `0bf9411`(阶段2) → `dbf042f`(阶段3)。
- 推送 `dbf042f` 至 `origin/main`：`0bf9411..dbf042f`（触发 CI，一次性 PAT 推送后已还原 remote + 擦除钥匙串）。

---

## [2026-07-21] 安全增强 + 时区治理 + 测试护栏 + 收尾闭环

### 媒体 presigned 化（#10 关闭匿名公开缺口）
- 新增 `GET /api/v1/media/access`：认证 + 部门隔离 → 返回预签名直连 URL；前端 `<img>/<video>` 直连，无需 Authorization 头。
- `/presigned` 与代理预览 `/{key:path}` 均加认证与 `_media_visible` 校验（越权/不存在一律 404，不泄露存在性）。
- 前端 `AttachmentManager` / `MediaUpload` / `AlarmView` 改走 presigned 批量解析 + 判空兜底。

### WorkPlan 时区列迁移（#11 深化）
- `work_plan.plan_start/plan_end` 由 naive `DateTime` 转 `timestamptz`（Alembic 迁移，naive 值视作北京解释，避免 UTC 漂移 8h）。
- engine 固定会话时区 `Asia/Shanghai`；`WorkPlanOut` 输出北京墙钟字符串；`ensure_aware_local` 兼容 None。

### 轻量收尾
- W293 docstring 尾随空白：经 `ruff --select W291,W293` 复核仓库已零残留（ruff-format pre-commit 已 strip），无需改动。
- #152 端口冲突验收：`run_demo.sh` 端口占用检测改用 venv python `socket.connect_ex` 可移植探测（不依赖 lsof），冲突即友好退出、绝不自动 kill 外部进程。

### 测试护栏
- 前端 Vitest 补全 3 个 spec（`utils/media` / `AttachmentManager` / `MediaUpload`），守护 #10 媒体 presigned 链路。
- **后端 pytest 116 用例 + 前端 Vitest 55 用例（11 文件）全绿**；`npm run type-check`（vue-tsc）无错。

### 交付与 CI
- 提交：`0f94371`(安全+时区) / `9888a7e`(#152) / `a1eecc4`(前端测试)。
- CI 运行 `29807600876`（head=a1eecc4c）**completed success**，全量门禁（migrate/seed/pytest/build/vitest/live）通过。
- GitHub 默认分支由 `master` 切到 `main`（`main` 为项目主线，`master` 保留为无关历史，未删）。

## [2026-07-17] 告警可视化闭环收尾：四端图表一致 + 测试护栏 + 打包优化

### 告警可视化 · 四端图表一致性
PDF 趋势图、Excel 概览图、前端 DashboardView 迷你趋势图、AlarmView 报表弹窗趋势区，四端统一：

| 维度 | 统一口径 |
|------|----------|
| 分桶来源 | 同源 `_compute_snapshot` / `build_snapshot_payload` / `SnapshotPreviewResult`，与 `/alarms/report`、`/dashboard/stats` 共用 `_period_key`（day/week/month） |
| 图表形态 | **按类型分色堆叠**（同一周期三类告警纵向叠加，便于看总量与构成） |
| 配色 | 红 `#C00000` = 围栏侵入(fence_intrusion) ／ 橙 `#ED7D31` = 间距过近(distance_too_close) ／ 蓝 `#2E75B6` = 设备自报(device_alarm) |
| 图例 | 三端均带类型图例，语义一致 |

- PDF：reportlab `VerticalBarChart`（`categoryAxis.style="stacked"`）+ 三层系列 + 顶部 `Legend`。
- Excel：openpyxl `BarChart`（`grouping="stacked"` + `overlap=100`）+ 三色系列 + 底部图例。
- 前端：DashboardView / AlarmView 的堆叠迷你图结构一致（`.bar-track.stack` + 3×`.bar-seg` 分色 + `.mini-legend`），由 `web/src/utils/snapshot.ts` 的 `snapTrendMaxOf` 统一取最大值。

> 更早的四端（趋势图 / 报表 / 导出 / 仪表盘）数据口径一致性由 `app/service/alarm_service.py` 的 `_period_key` 保证，详见 README「告警可视化与历史快照」。

### 其它平台模块 · 作业计划甘特视图
- 新增 `web/src/components/WorkPlanGantt.vue`：按 `plan_start~plan_end` 渲染分色横条（红=监控中 / 橙=执行中 / 绿=已完成 / 灰=草稿），含设备数徽标、时间轴刻度、当前时间竖线；与 rule_engine_v2 计划门控（仅激活计划产生告警）打通。
- `JobView.vue` 集成甘特卡片（全量加载跟随项目筛选，点击条 `openDetail`）。

### 测试护栏
- 前端测试纳入 `run_demo.sh` [3.7/6] 门禁：依赖 → 构建 → Vitest 单测，任一失败即终止联调；新增 `SKIP_FE_BUILD=1` 仅跑单测以加速纯回归。

### 前端打包优化
- `manualChunks` 拆分 vendor：`vendor-vue`(vue/router/pinia) / `vendor-axios` / `vendor-element-icons` / `vendor-ep-core` / `vendor-ep-c0..c2`（组件按名哈希分 3 桶）；Element Plus 改为按需引入(tree-shaking)，消除 >500KB chunk 警告。
- 新增 `web/vite.ep.ts` 共享插件模块，vite 与 vitest 配置复用，保证构建/测试环境一致。

### 测试覆盖
- **后端回归**（run_demo.sh [3.6/6] 门禁，7 个文件）：`test_media`(5) / `test_attachments`(6) / `test_realtime`(6) / `test_dashboard_scope`(4) / `test_job_alarm`(6) / `test_alarm_report`(22) / `test_snapshot_preview`(4) → 共 **53** 个用例全绿。
- **前端**（Vitest，8 个 spec）：`DailyTrendChart`(5) / `MapPanel`(2) / `WorkPlanGantt`(5) / `geo`(7) / `period`(5) / `snapshot`(7) / `AlarmView`(5) / `DashboardView`(4) → 共 **40** 个用例全绿。

### 一键联调验证（全绿）
`bash scripts/run_demo.sh --skip-services` 末端自动实证：实时位置 3 条 / 告警列表（v2 溯源带 work_plan_id）/ 轨迹回放 / 报表汇总 / 仪表盘周期联动自洽 / 历史快照多表导出 / 快照预览↔导出逐桶一致，全部通过。

---

## [2026-07-15] 规则引擎 v2（计划感知告警）

- 告警判定改为**计划感知**：仅 `is_start=True 且 status='执行中' 且处于 plan_start/plan_end 时间窗内 且覆盖该设备` 的作业计划才产生告警。
- 新增 `app/core/rule_engine_v2.py`；`pipeline.handle_upstream` 切换至 v2；告警 `alarm.work_plan_id` 溯源。
- 作业计划 API 增强：`POST /{id}/start`、`POST /{id}/complete`、`GET /active`；Schema `WorkPlanRule` 结构化 `trigger_conditions/dwell_time/monitor_target`。

## [2026-07-10] 原生服务绑定架构（方案 A）

- 绑定 PostgreSQL / Redis / MQTT(Mosquitto) / MinIO 原生服务，不引入 Docker / mock。
- RBAC + 部门数据隔离（四级 DataScope）落地；统一 `ApiResponse[T]`。

## 阶段基线
- 阶段0（骨架 / RBAC / 部门隔离 / 验证码 / 前端骨架 / pre-commit 门禁）：✅
- 阶段1（实时链路：MQTT 上报 → 落库 → 规则引擎判定 → WebSocket 推送）：✅
- 阶段2~5（主数据 / 作业计划 / 告警 / 大屏）：✅ 告警可视化闭环已交付
- 四轨道计划 A/B/C/D（2026-07-21 起，#195–#203）：✅ 全部收官
  - A 质量加固（前端 6 视图单测 + 后端 5 router 集成测）：✅
  - B 生产化验证（nginx/systemd 真起生产形态演练 + 部署文档）：✅
  - C 功能演进（Locust 千台设备压测 + 连接池调优）：✅
  - D 文档治理（路线图标注 + CHANGELOG 补齐 + 记忆归档）：✅
