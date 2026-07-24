# 涉铁工程智能监控平台 · 功能开发 Roadmap

> 维护对象：`rail_monitor`（FastAPI + Vue3 + PostgreSQL + Redis + MQTT）
> 最后更新：2026-07-23
> 说明：本文档汇总平台「核心闭环之外」的功能模块规划与现状，作为后续迭代的排期基线。

---

## 1. 平台现状（已完成，闭环可用）

- **业务闭环**：监测（告警）→ 治理（隐患）→ 通知（站内信）端到端打通；告警↔隐患双向 FK 溯源 + 一键转隐患。
- **基础设施**：三套 DB 连接池（API / 上行落库 / 看板只读）、ingestion 批处理落库、WebSocket 实时通道（含裸 HTTP 兜底 426）、千台压测调优（端到端落库率 **100%**，`INGEST_WORKERS=8` + `INGEST_DB_POOL_SIZE=12` + Mosquitto `max_queued_messages=100000`）。
- **规模**：15 个后端路由 + 16 个前端页面，覆盖项目 / 设备 / 人员 / 机械 / 围栏 / 作业计划 / 告警 / 隐患 / 通知 / 大屏等域。
- **合规**：RBAC + 部门数据隔离（`app.core.data_scope`）已应用于全部业务查询。

---

## 2. 模块清单与状态

| # | 模块 | 性质 | 优先级 | 状态 | 依赖 / 备注 |
|---|------|------|--------|------|-------------|
| ③ | **消息中心独立管理页** | 纯前端 | P1 | ✅ 已完成 | API 已就绪；列表/未读/已读/跳转 + 菜单入口 |
| ④ | **设备指令下发 UI** | 纯前端 | P1 | ✅ 已完成 | 接 `POST /v1/realtime/command`，按设备类型动态动作 |
| ② | **通知定向收敛（按项目/角色）** | 后端 | P2 | ✅ 已完成 | 复用 `data_scope`，修复广播与数据隔离冲突 |
| ⑤ | **操作审计日志** | 全栈 | P2 | ✅ 已完成 | 中间件自动落库 + 受数据范围约束的查阅页 |
| ① | **短信 / 语音真网关** | 后端（预留） | P2 | 🔲 待凭据 | `SmsNotifier/VoiceNotifier` 已留桩，待第三方凭据 |
| ⑥ | **报表导出对称化** | 后端 | P2 | ✅ 已完成 | 隐患/设备 Excel·PDF 导出补齐 |
| ⑦ | **数据字典 / 枚举中心** | 全栈 | P3 | ✅ 已完成 | 设备类型、告警类型等枚举可视化维护 |
| ⑧ | **视频 AI 分析** | 重 | P3 | ✅ 已完成(PoC) | 通道/事件模型·接口·回推端点；推理服务留桩 |
| ⑨ | **巡检 / 打卡 / 履职** | 全栈 | P3 | ✅ 已完成 | 任务/打卡/异常转隐患，与人员定位联动 |
| ⑩ | **作业计划模板 / 克隆** | 后端 | P3 | ✅ 已完成 | WorkPlan 加 is_template + 克隆/存模板接口 |
| ⑪ | **多项目对比大屏** | 全栈 | P3 | ✅ 已完成 | `GET /v1/dashboard/project-compare` 风险分降序 |
| ⑫ | **设备健康 / 运维** | 全栈 | P3 | ✅ 已完成 | `GET /v1/devices/health` 在线率/健康分 |

图例：✅ 已完成 · 🔲 尚未启动

---

## 3. 分阶段计划

### P1 · 前端补齐（API 已就绪，零后端改动）— 已完成
目标：把"后端已提供但前端无入口"的能力补齐，见效快、风险低。
- ③ 消息中心独立页（2026-07-23 前完成）
- ④ 设备指令下发 UI（2026-07-23 前完成）

### P2 · 后端正确性 / 合规 — 进行中
目标：消除与数据隔离/监管要求的冲突，补齐强需求模块。
- **② 通知定向收敛（✅ 2026-07-23）**
  - 问题：原 `notify_alarm_raised` 向**全部活跃用户广播**站内信，与部门数据隔离冲突（跨项目信息扩散）。
  - 方案：`app/core/notify.py` 新增 `resolve_recipients_for_project`，复用 `resolve_data_scope`；仅项目数据范围内的用户（含超级管理员）接收。告警、隐患创建通知同源收敛。
  - 测试：`tests/test_notify_scope.py`（接收人收敛 + 无项目仅超管）。
- **⑤ 操作审计日志（✅ 2026-07-23）**
  - 方案：`AuditMiddleware` 对写请求（POST/PUT/PATCH/DELETE）自动落 `audit_log`（快照 user_id/username/dept_id）；查阅接口 `/v1/audit-logs` 受数据范围约束（本部门及以下可见）。
  - 模型/迁移/服务/接口/前端页齐备；`settings.audit_enabled` 总开关（测试默认关）。
  - 测试：`tests/test_audit_log.py`（服务层范围 + 中间件落库）。
- ① 短信/语音真网关（🔲）：在 `app/core/notify.py` 适配器内补全真实发送，业务调用不变。
- ⑥ 报表导出对称化（🔲）：为隐患、设备等列表补充 Excel/PDF 导出。

### P3 · 业务扩展 — 已完成（2026-07-24）
目标：补齐监管与现场高频业务能力；⑧⑨⑪⑫ 以最小 PoC 形态落地，可随真实视频流/推理接入逐步深化。
- **⑦ 数据字典（✅）**：`dict_type/dict_item` 模型+迁移+服务+接口+前端双栏页+菜单，系统字典只读保护。
- **⑧ 视频 AI（✅ PoC）**：`video_channel/video_event` 模型+迁移+接口；`POST /v1/videos/events/ingest` 供外部推理回推；前端通道管理+事件流。
- **⑨ 巡检打卡（✅）**：`inspection_task/inspection_record` 模型+迁移+服务+接口；打卡异常一键转隐患（巡检→治理闭环）；前端统计+列表+打卡+转隐患。
- **⑩ 计划模板/克隆（✅）**：`WorkPlan.is_template` 列+迁移；`clone`/`save-as-template` 深拷贝绑定、执行态清零；前端模板库开关+克隆/存模板按钮。
- **⑪ 对比大屏（✅）**：`GET /v1/dashboard/project-compare` 按项目聚合设备/人/机/栏/计划/告警/隐患，风险分降序；前端对比表。
- **⑫ 设备健康（✅）**：`GET /v1/devices/health` 在线判定与实时看板同源，健康分=在线60+活跃20+无告警20；前端健康看板。
- ⑥ 报表导出对称化（✅）：隐患/设备 Excel·PDF 导出。
- 全量后端 pytest 178 passed / 1 skipped；前端 `vue-tsc --noEmit` 通过 + 生产构建通过。

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
- **短信/语音**：属外部依赖，落地前需确认网关凭据与计费；当前为留桩，不阻断业务。
- **压测结论**：落库率 100% 的甜点档已固化进 `app/config.py` 默认值；若上行规模翻倍（数千设备/更短间隔），再上调 `INGEST_WORKERS` 即可。
