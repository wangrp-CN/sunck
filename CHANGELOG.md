# CHANGELOG · 涉铁工程智能监控平台（rail_monitor）

记录各阶段交付与关键变更。告警可视化方向以「趋势 → 导出 → 快照 → 大屏联动」闭环为主线。

---

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
