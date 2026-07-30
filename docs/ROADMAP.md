# 涉铁工程智能监控平台 · 功能开发 Roadmap

> 维护对象：`rail_monitor`（FastAPI + Vue3 + PostgreSQL + Redis + MQTT）
> 最后更新：2026-07-29
> 说明：本文档汇总平台「核心闭环之外」的功能模块规划与现状，作为后续迭代的排期基线。

---

## 1. 平台现状（已完成，闭环可用）

- **业务闭环**：监测（告警）→ 治理（隐患）→ 通知（站内信）端到端打通；告警↔隐患双向 FK 溯源 + 一键转隐患。
- **基础设施**：三套 DB 连接池（API / 上行落库 / 看板只读）、ingestion 批处理落库、WebSocket 实时通道（含裸 HTTP 兜底 426）、千台压测调优（端到端落库率 **100%**，`INGEST_WORKERS=8` + `INGEST_DB_POOL_SIZE=12` + Mosquitto `max_queued_messages=100000`）。
- **规模**：15 个后端路由 + 16 个前端页面，覆盖项目 / 设备 / 人员 / 机械 / 围栏 / 作业计划 / 告警 / 隐患 / 通知 / 大屏等域。
- **合规**：RBAC + 部门数据隔离（`app.core.data_scope`）已应用于全部业务查询。
- **部署闭环（✅ 2026-07-24）**：`deploy/` 已补齐 `nginx.conf`（反代 `/api`、WebSocket `/ws`、静态托管、`/health`/`/metrics` 透传、公网拦截 Swagger）+ `README.deploy.md`（前置依赖 / 后端迁移 / `.env` 模板 / systemd 启用 / 前端构建 / 验证 / 安全建议）+ `smoke_drill.sh`（全栈真起冒烟脚本）。
- **目标机真起演练（✅ 2026-07-24 已执行）**：单一网络命名空间内拉起 PG/Redis/MQTT/MinIO + uvicorn，走**生产态验证码登录**（答案取自 Redis）拿到 JWT → P3 新端点（`devices/health`、`dashboard/project-compare`、`inspections/stats`、`videos/channels`、`dicts`、`jobs?is_template`）全部 200 → 写操作（建+删数据字典）成功 → Nginx(:8088) 反代透传 `/api` + SPA 首页 + history 回退全部 200 → 优雅关停（ingest 工作池正常停止）。**结论：部署闭环端到端可用。** 注意：`devices/health` 在线数依赖实时遥测；演练未跑模拟器时全部设备离线属预期。

---

## 2. 模块清单与状态

| # | 模块 | 性质 | 优先级 | 状态 | 依赖 / 备注 |
|---|------|------|--------|------|-------------|
| ③ | **消息中心独立管理页** | 纯前端 | P1 | ✅ 已完成 | API 已就绪；列表/未读/已读/跳转 + 菜单入口 |
| ④ | **设备指令下发 UI** | 纯前端 | P1 | ✅ 已完成 | 接 `POST /v1/realtime/command`，按设备类型动态动作 |
| ② | **通知定向收敛（按项目/角色）** | 后端 | P2 | ✅ 已完成 | 复用 `data_scope`，修复广播与数据隔离冲突 |
| ⑤ | **操作审计日志** | 全栈 | P2 | ✅ 已完成 | 中间件自动落库 + 受数据范围约束的查阅页 |
| ① | **短信 / 语音网关（模拟真实数据）** | 后端 | P2 | ✅ 已完成(模拟) | 网关适配层 `app/core/gateways.py`：simulate 模式生成阿里云风格真实形态回执并落 `notification_delivery` 触达表；real 模式凭据门控留接口，配 `SMS_MODE=real`+凭据即切换，业务调用不变 |
| ⑥ | **报表导出对称化** | 后端 | P2 | ✅ 已完成 | 隐患/设备 Excel·PDF 导出补齐 |
| ⑦ | **数据字典 / 枚举中心** | 全栈 | P3 | ✅ 已完成 | 设备类型、告警类型等枚举可视化维护 |
| ⑧ | **视频 AI 分析** | 重 | P3 | ✅ 已完成(闭环) | 通道/事件模型·接口·回推端点；前端实时拉流播放(HLS/MP4)；`/ai/analyze` 接外部推理端点(超时容错)+能力清单对齐；**可运行参考推理服务 `services/video-ai`（FastAPI+像素级 ReferenceDetector，可插拔真实 YOLO）+ systemd/nginx/Docker 部署接入，端到端验证 `status=done`** |
| ⑨ | **巡检 / 打卡 / 履职** | 全栈 | P3 | ✅ 已完成 | 任务/打卡/异常转隐患，与人员定位联动 |
| ⑩ | **作业计划模板 / 克隆** | 后端 | P3 | ✅ 已完成 | WorkPlan 加 is_template + 克隆/存模板接口 |
| ⑪ | **多项目对比大屏** | 全栈 | P3 | ✅ 已完成 | `GET /v1/dashboard/project-compare` 风险分降序 |
| ⑫ | **设备健康 / 运维** | 全栈 | P3 | ✅ 已完成 | `GET /v1/devices/health` 在线率/健康分 |
| ⑬ | **闭环效能度量** | 全栈 | P3 | ✅ 已完成 | 大屏「闭环效能度量」卡：风暴抑制率/告警MTTR/派单SLA/隐患闭环率/异常引擎贡献占比（窗口可调）；`GET /v1/dashboard/effectiveness` + `effectiveness_service` |
| ⑭ | **🅱 告警治理与值班体系** | 全栈 | P4 | ✅ 全部交付(M1-M5) | 值班排班模型+CRUD接口+权限(M1)；派单自动兜底当班人(M3，后端+前端预填)；前端值班页+菜单(M2)；**M4 告警收敛/抑制/升级策略**(AlarmPolicy)；**M5 处置预案/知识库联动**(Playbook，6 类 mock 预案+告警处置推荐面板闭环) |

图例：✅ 已完成 · 🟡 进行中 · 🔲 尚未启动

> **进度补记（2026-07-29）**：本表停留在 2026-07-24，期间已额外交付「智能核心 v2」整条链路（风险/健康快照 → 阈值预警 → 跨设备共因关联 → 趋势异常检测 → 异常进告警流 → 一键派单闭环），以及本轮「闭环效能度量」。上述能力均已在 `CHANGELOG` 与 `deploy/README.deploy.md` §13 记录，本表仅补充 ⑬ 与刷新日期。另：③移动端适配（响应式布局 / 侧栏抽屉化 / ResponsiveTable 横向滚动）、④视频AI深化（`VideoPlayer` 实时拉流、外部推理端点接入就绪 + 超时降级、能力清单对齐、前端 AI 分析对话框）已交付。**⑧ 视频AI 真实推理服务已部署闭环**：新增可运行参考推理服务 `services/video-ai`（FastAPI + 像素级 `ReferenceDetector`，可插拔真实 YOLO），配套 systemd/nginx(`/ai/`)反代/Docker 接入，端到端验证平台 `/v1/videos/ai/analyze` 经 `VIDEO_AI_ENDPOINT` 返回 `status=done` + 真实 `findings`。**① 短信/语音网关已按「模拟真实数据」模式交付**（触达记录落库 + 真实形态回执，真实厂商仅差凭据+SDK 调用一处），路线图全部条目闭环。

---

## 3. 分阶段计划

### P1 · 前端补齐（API 已就绪，零后端改动）— 已完成
目标：把"后端已提供但前端无入口"的能力补齐，见效快、风险低。
- ③ 消息中心独立页（2026-07-23 前完成）
- ④ 设备指令下发 UI（2026-07-23 前完成）

### P2 · 后端正确性 / 合规 — 已完成（2026-07-29）
目标：消除与数据隔离/监管要求的冲突，补齐强需求模块。
- **② 通知定向收敛（✅ 2026-07-23）**
  - 问题：原 `notify_alarm_raised` 向**全部活跃用户广播**站内信，与部门数据隔离冲突（跨项目信息扩散）。
  - 方案：`app/core/notify.py` 新增 `resolve_recipients_for_project`，复用 `resolve_data_scope`；仅项目数据范围内的用户（含超级管理员）接收。告警、隐患创建通知同源收敛。
  - 测试：`tests/test_notify_scope.py`（接收人收敛 + 无项目仅超管）。
- **⑤ 操作审计日志（✅ 2026-07-23）**
  - 方案：`AuditMiddleware` 对写请求（POST/PUT/PATCH/DELETE）自动落 `audit_log`（快照 user_id/username/dept_id）；查阅接口 `/v1/audit-logs` 受数据范围约束（本部门及以下可见）。
  - 模型/迁移/服务/接口/前端页齐备；`settings.audit_enabled` 总开关（测试默认关）。
  - 测试：`tests/test_audit_log.py`（服务层范围 + 中间件落库）。
- **① 短信/语音网关（✅ 2026-07-29，模拟真实数据）**
  - 方案：新增网关适配层 `app/core/gateways.py`（`SimulatedSms/VoiceGateway` 生成阿里云风格回执 `Code/BizId/RequestId`，`RealSms/VoiceGateway` 凭据门控留接口）；`SmsNotifier/VoiceNotifier` 经 `send_via_gateway` 下发并落 `notification_delivery` 触达表（含 provider/biz_id/status/raw 原始回执）。
  - 接口：`GET /v1/notifications/deliveries` 触达记录查询、`POST /v1/notifications/test-send` 链路验证（均 `dashboard:view` 鉴权）。
  - 切换真实网关：`.env` 配 `SMS_MODE=real` + `SMS_API_KEY/SECRET`（voice 同理），在 `RealXxxGateway._call_provider` 内补厂商 SDK 调用即可，业务零改动；缺凭据自动 `not_configured`，异常兜底 `error` 不中断业务。
  - 测试：`tests/test_notifications_gateway.py`（回执形态/落库/no_phone/双通道 fanout/凭据门控/两接口，8 用例）。
- ⑥ 报表导出对称化（✅）：隐患、设备等列表 Excel/PDF 导出已补齐。

### P3 · 业务扩展 — 已完成（2026-07-24）
目标：补齐监管与现场高频业务能力；⑧⑨⑪⑫ 以最小 PoC 形态落地，可随真实视频流/推理接入逐步深化。
- **⑦ 数据字典（✅）**：`dict_type/dict_item` 模型+迁移+服务+接口+前端双栏页+菜单，系统字典只读保护。
- **⑧ 视频 AI（✅ PoC → 深化）**：`video_channel/video_event` 模型+迁移+接口；`POST /v1/videos/events/ingest` 供外部推理回推；前端通道管理+事件流。深化（2026-07-29）：前端 `VideoPlayer` 实时拉流播放（HLS via hls.js / MP4 原生 / RTSP·RTMP 提示）；`POST /v1/videos/ai/analyze` 支持转发外部推理端点并返回结构化 `findings`（超时/失败优雅降级为占位，不阻断主流程）；`GET /v1/videos/ai/capabilities` 暴露与回推事件类型对齐的能力清单；能力常量统一收口到 `app.schema.video.VIDEO_AI_CAPABILITIES`。
- **⑨ 巡检打卡（✅）**：`inspection_task/inspection_record` 模型+迁移+服务+接口；打卡异常一键转隐患（巡检→治理闭环）；前端统计+列表+打卡+转隐患。
- **⑩ 计划模板/克隆（✅）**：`WorkPlan.is_template` 列+迁移；`clone`/`save-as-template` 深拷贝绑定、执行态清零；前端模板库开关+克隆/存模板按钮。
- **⑪ 对比大屏（✅）**：`GET /v1/dashboard/project-compare` 按项目聚合设备/人/机/栏/计划/告警/隐患，风险分降序；前端对比表。
- **⑫ 设备健康（✅）**：`GET /v1/devices/health` 在线判定与实时看板同源，健康分=在线60+活跃20+无告警20；前端健康看板。
- ⑥ 报表导出对称化（✅）：隐患/设备 Excel·PDF 导出。
- 全量后端 pytest 178 passed / 1 skipped；前端 `vue-tsc --noEmit` 通过 + 生产构建通过。

### P4 · 告警治理与值班体系 — 进行中（2026-07-29 启动）
目标：把"值班→派单→处置→闭环"串成可运营的值班体系，消除告警无主/无兜底的状态。
- **⑭ 值班排班与自动派单（M1-M3 ✅ 2026-07-29）**
  - M1 值班模型：`DutyRoster`（project_id/user_id/shift/duty_role/起止时间窗）模型 + 迁移 `aa1b2c3d4e5f` + 注册 `_MODEL_DEPT_LINK`(VIA_PROJECT) 数据隔离。
  - M2 后端 CRUD：7 个端点（`/`列表、`/on-duty`当前值班、`/meta`班次枚举、`/{id}`详情、`POST`/`PUT`/`DELETE`）+ 权限 `duty:list`/`duty:manage`（已入 `rbac_seed` device 子树 + monitor/project_manager 角色）+ 前端 `DutyRosterView.vue` 值班页 + 菜单/路由。
  - M3 自动派单兜底：`dispatch_service.create_order` 未指定 `assignee_id` 时调 `resolve_on_duty(db, project_id)` 取当前在班人；前端 `DispatchCreateDialog` 选归属项目后自动预填当班人为处理人（可手动覆盖）。**无排班时保持「待派」，不报错。**
  - 测试：`tests/test_duty.py`（5 用例绿），覆盖建/列/在班解析/自动派单兜底/无排班不指派。
  - 顺带修复：`app/api/v1/dispatch.py` 3 处误用不存在的 `ApiResponse.error` → 改 `ApiResponse.fail(code=404,...)`，与项目"业务失败 HTTP200+非0 code"约定一致。
- **M4 告警收敛/抑制/升级策略（✅ 2026-07-30）**：`AlarmPolicy` 模型（按项目/类型通配 + 启用状态配置）驱动三类治理：
  - **收敛**：`resolve_policy(project_id, alarm_type)` 按「项目+类型 > 项目通配 > 全局+类型 > 全局通配」取最新命中；命中策略的 `suppress_window_seconds` 覆盖全局风暴合并窗口（`alarm_service.create_alarm` 用其替代 `ALARM_DEDUP_TTL`）。
  - **抑制（静默免打扰）**：`in_silence(policy)` 按北京时间 `silence_start~silence_end`（支持跨天）判定；静默时段内告警仍落库但跳过站内信通知（不丢数据）。
  - **升级**：`run_escalations(db)` 扫描「待处理 + 超时 + 未升级过（`escalated_at` 留痕幂等）」的告警，按策略升级 `alarm_level` 并依 `escalate_channels` 重通知（含 `resolve_on_duty` 当班人姓名）；由 `scripts/report_subscription_job.py` 周期任务串联，另提供 `POST /v1/alarm-policies/run-escalations` 手动触发端点。
  - 交付：`AlarmPolicy` 模型 + 迁移 `dd4e5f6a7b8c`（含 `alarm.escalated_at` 列）+ `app/service/alarm_policy_service.py`（CRUD/匹配/静默/升级）+ `app/api/v1/alarm_policies.py`（列表/`/meta`/手动升级/详情/增删改）+ 路由挂载 + 权限 `alarm_policy:list`/`alarm_policy:manage`（入 `rbac_seed` 的 alarm 子树，授 monitor/project_manager/超管）；前端 `api/alarm-policy.ts` + `AlarmPolicyView.vue`（列表/新增编辑/静默与升级配置/`立即扫描升级`）+ 路由菜单。测试 `tests/test_alarm_policy.py` 8 用例全绿，数据库无回归（317 passed / 1 skipped）；前端 173 测全过 + vue-tsc 0 错。
- **M5 处置预案/知识库联动（✅ 2026-07-30）**：`Playbook` 模型 + 按告警自动推荐处置预案 + 前端联动，闭环处置指导（mock 预置 6 类预案，可一键替换真实数据）。
  - `Playbook` 模型（含 `steps` 处置步骤 JSON、`references` 知识库链接 JSON：title+url、`alarm_type`/`alarm_level` 关联维度、`project_id` 项目维度、`summary`/`trigger_condition`/`tags`/`owner_role`/`est_minutes`）+ 迁移 `ee5f6a7b8c9d`（接 `dd4e5f6a7b8c`；时间戳带 `server_default=now()`）。
  - `playbook_service`：`resolve_playbooks(db, scope, project_id, alarm_type, alarm_level, limit)` 按「项目+类型+级别 > 项目+类型 > 项目通配 > 全局+类型+级别 > 全局+类型 > 全局通配」特异性取最新启用预案；`recommend_for_alarm(db, alarm_id)` 按告警自身维度推荐；CRUD（含数据范围过滤 + 逻辑删）。
  - `app/api/v1/playbooks.py`：`GET /`(过滤)/`/meta`(告警类型/级别字典，对接 `predictive_alert`)/`/recommend`(按维度)/`/recommend-by-alarm/{id}`(按告警)/详情/`POST`/`PUT`/`DELETE` + `rbac_seed` 权限 `playbook:list`/`playbook:manage`（入 alarm 子树，授 monitor/project_manager/超管）。
  - 数据播种：`app/core/playbook_seed.py` 幂等预置 6 类告警处置预案（围栏越界/位移超限/设备离线/列车接近/异常检测/预测性预警），经 `scripts/seed_playbooks.py` 与 `scripts/seed_rbac.py` 串联执行。
  - 前端：`api/playbook.ts` + `PlaybookView.vue`（列表/新增编辑/步骤与知识库链接可视化编辑/meta 联动/一键扫描推荐预览）+ 路由菜单「处置预案」；`AlarmView.vue` 处置对话框新增「相关处置预案」面板——打开处置时按 `alarm_type/alarm_level/project_id` 拉取推荐预案并展开步骤，处置指导闭环。
  - 测试：`tests/test_playbook.py` 4 用例（CRUD/匹配优先级/JSON 编解码/推荐端点/预置预案存在性）全绿，全量 **321 passed / 1 skipped / 0 failed**；前端 `PlaybookView.spec.ts` 4 用例，全量 **177 passed** + vue-tsc 0 错。
- **🅰 双厂商抽象代码（✅ 2026-07-29）**：`RealSms/VoiceGateway` 已实现**双厂商（阿里云/腾讯云）SDK 适配**——按 `sms_provider`/`voice_provider`(`aliyun|tencent`) 分派 `_aliyun_*`/`_tencent_*` 真实调用，回执映射为统一 `GatewayResult`；厂商 SDK **懒加载导入**（模块导入期不依赖任何第三方库，无 SDK 也能启动，仅真实下发不可用，返回 `SDK_MISSING`）；凭据缺失/厂商未配→`not_configured`，调用异常→`error`，绝不中断业务。配置新增 `sms_app_id/sms_template_id/tencent_region/voice_template_code/voice_app_id/voice_template_id/voice_called_show_number` 及 `.env.example` 双厂商段；`tests/test_notifications_gateway.py` 增 4 用例（SDK 缺失优雅降级/厂商未配/BAD_PROVIDER/缺模板）共 12 绿。切真实网关=配 `SMS_MODE=real`+凭据+`pip install` 对应 SDK，业务零改动。
- **Phase 5 · 智能化预测（✅ 全部交付，M1-M4）**：从"阈值告警"升级到"预测性预警"。
  - **M1 预测基座（✅ 2026-07-29）**：`Forecast` 模型（唯一键 scope_type+ref_id+metric+horizon_days，upsert 只留最新；VIA_PROJECT 数据隔离）+ 迁移 `bb2c3d4e5f6a`；`forecast_service` 纯 Python OLS 对 `risk_index` 日序列外推（`forecast_horizon_days=7`/`forecast_history_days=30`/`forecast_min_points=3` 均入 config），预测值截断 0-100 并按 scoring 阈值给"高/中/低"预测级别；`GET /v1/forecasts` + `POST /v1/forecasts/recompute`（forecast:view，已入 rbac_seed 并授 project_manager/monitor）；`snapshot_job` 在异常检测后串联 `run_forecasts`；`tests/test_forecast.py` 6 用例（OLS 纯函数/上升序列/幂等 upsert/样本不足降级/端点）。样本 < 3 点自动跳过，每日快照跑满 3 天后自动出预测。
  - **M2 预测增强（✅ 2026-07-29）**：多指标——设备 `health_score` 预测（分档用健康阈值优/良/中/差，`compute_device_forecast`，`run_forecasts` 批量加载防 N+1 同时覆盖项目+设备）；残差 95% 置信带（`std_resid`/`forecast_lower`/`forecast_upper`，迁移 `cc3d4e5f6a7b`；n≤2 时带宽 0）；`GET /v1/forecasts/preview`（历史点+拟合+预测点+置信带，样本不足时 forecast=null 序列照返，带项目可见性校验）；列表加 scope_type/metric 过滤。测试扩到 10 用例。
  - **M3 预测性预警回灌（✅ 2026-07-29）**：`constants.ALARM_TYPE_FORECAST="predictive_alert"` + `forecast_service.run_predictive_alerts` 遍历 `forecast` 表，对越阈预测（`risk_index` 级别「高」→警告；`health_score`「中」→警告、「差」→严重）生成 `predictive_alert` 告警；以 `device_no=predictive:{metric}:{ref_id}:{horizon_days}` 编码做幂等（同键已存在则跳过，跨 Redis-TTL 仍生效），经 `alarm_service.create_alarm` 复用既有告警流（站内信通知 + 告警管理页一键派单闭环）；`snapshot_job` 在 `run_forecasts` 后串联并统一 `db.commit()`。前端 `AlarmView.vue` 补 `predictive_alert: "预测预警"` 标签 + 过滤项。测试扩到 14 用例（含越阈生成/健康中/幂等/未越阈跳过）。
  - **M4 驾驶舱预测卡（✅ 2026-07-30）**：前端 `api/forecast.ts`（列表/preview/recompute 类型化封装）+ `ForecastChart.vue`（纯内联 SVG：历史实线 + 预测虚线延伸 + 预测菱形点 + 95% 置信带扇形 + 阈值虚线 60 + 上下界/日期标注，x 轴按真实时间戳比例布点）+ `DashboardForecastCard.vue`（大屏"智能预测·趋势外推"卡：项目风险/设备健康双视角切换，TOP5 列表——risk 降序 / health 升序最差在前，行点击联动 preview 图，趋势箭头恶化红/改善绿，60s 自动刷新，窄屏单列）；挂载 `DashboardView` 关联对比卡之后。空态："暂无预测数据（日快照积累≥3天后自动生成）" / "数据积累中"。前端测试 +7（ForecastChart 3 + DashboardForecastCard 4），全量 169/169 绿，vue-tsc 0 错（顺手修 DutyRosterView 未使用导入 DutyMeta）。

> 执行顺序（用户确认）：先 🅱 告警治理与值班体系 → 再 🅰 双厂商抽象代码 → 最后 Phase 5 智能化预测。

---

## 4. 本次交付明细（2026-07-23）

**后端**
- `app/core/notify.py`：新增 `resolve_recipients_for_project` / `notify_for_project` / `notify_hazard_created`，告警与隐患通知按项目数据范围收敛。
- `app/service/hazard_service.py`：隐患创建后按范围推送站内信。
- `app/model/audit.py` + `alembic/versions/l6m7n8o9p0q1_add_audit_log.py`：审计表 + 迁移。
- `app/schema/audit.py` / `app/service/audit_service.py` / `app/api/v1/audit_logs.py`：审计列表（数据范围约束）+ 元数据接口。
- `app/core/audit.py` + `app/main.py`：审计中间件注册。
- `app/config.py`：新增 `audit_enabled` 开关；`tests/conftest.py` 关闭审计与缓存以保证测试隔离。
- `tests/test_notify_scope.py` / `tests/test_audit_log.py`：新增回归测试。
- `tests/test_db_pool_metrics.py`：同步 `ingest_db_pool_size` 新默认值（12）。

**前端**
- `web/src/api/audit.ts`、`web/src/views/AuditLogView.vue`、`web/src/router/index.ts`、`web/src/layouts/DefaultLayout.vue`：操作审计页 + 菜单 + 路由。

---

## 5. 风险与建议

- **通知收敛**：若某业务通知无归属项目（project_id 为空），仅超级管理员接收——属预期的安全默认，不会越权扩散。
- **审计中间件**：写库使用独立会话且全程容错，审计失败不影响业务；高频写场景会放大 `audit_log` 体量，建议后续按保留期归档/清理。
- **短信/语音**：当前默认 simulate 模式（模拟真实数据，回执/触达记录形态与真实网关一致）；切真实厂商需确认凭据与计费，配置切换即可，不阻断业务。
- **压测结论**：落库率 100% 的甜点档已固化进 `app/config.py` 默认值；若上行规模翻倍（数千设备/更短间隔），再上调 `INGEST_WORKERS` 即可。
