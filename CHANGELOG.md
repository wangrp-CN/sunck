# CHANGELOG · 涉铁工程智能监控平台（rail_monitor）

记录各阶段交付与关键变更。告警可视化方向以「趋势 → 导出 → 快照 → 大屏联动」闭环为主线。

---

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
