# 功能模块优化清单（rail_monitor · 涉铁工程智能监控平台）

> 生成时间：2026-07-20
> 审查方式：Explore 子代理全量扫描，聚焦「功能模块可优化性」（业务逻辑完整性 / 性能 / 健壮性 / 安全 / 前端一致性 / 技术债）。
> 已完成的部门隔离、规则引擎 v2、实时链路、导出快照、Prometheus、门禁等不重复赘述。

---

## 高严重度（建议优先）

### 1. 实时位置「最新一条」全表扫描（高频时序表性能炸弹）
- **位置**：`app/service/location_service.py:56-68`（子查询无时间窗、无项目过滤）；调用点 `dashboard.py:104/278`、`realtime.py:122/222`、`rule_engine_v2.py:168`。
- **问题**：`device_location` 为高频时序表，`latest_locations` 全表 `group_by device_no` 取最大 id；`DeviceLocation` 缺 `(device_no, id)` 复合索引，Postgres 只能全表顺序扫描。大屏 `_compute_device_stats` 还以**无项目过滤**方式调用，每次刷新都全表扫。
- **影响**：设备/时序增长后，大屏刷新 + 每条上行消息都触发全表扫描，DB CPU/IO 飙升，拖慢页面与 MQTT 消费线程。
- **建议**：① 维护小表 `latest_device_location`（上行时 upsert 最新位置），所有「最新/在线」改读该表；② 至少补 `Index("ix_device_location_device_no_id", "device_no", "id")`；③ dashboard 调用必须带 `scope` 内 `project_id` 过滤（已有 `_scope_project_ids` 可传入）。

### 2. 消警：先下发指令后提交 DB，失败致「设备已静默但告警未更新」
- **位置**：`app/api/v1/alarms.py:265-277`（先 `mqtt_client.publish` 再 `db.commit()`）；`app/core/database.py:30-36`（`get_db` 的 `finally` 仅 `close()`，无 `rollback`）。
- **问题**：置「已消警」时先向设备发 `alarm on:False`，再提交状态。若 MQTT 发布抛异常，会话随连接回收回滚，**设备已收到关停指令但 DB 中 `alarm_status` 仍为「告警开始」**。
- **影响**：设备物理状态与业务数据不一致，运维重复处置；`get_db` 缺统一回滚放大半提交风险。
- **建议**：调换顺序——先 `db.commit()` 落库（操作员意图），成功后再下发；下发失败返回 502 但不回滚。给 `get_db` 的 `finally` 增加 `db.rollback()` 兜底（`try/yield/except rollback/finally close`）。

### 3. 告警永不自动「结束」→ 持续违规反复产生「告警开始」（堆积/风暴）
- **位置**：`app/core/rule_engine_v2.py:252-306`（仅产出「告警开始」，从无「告警结束」分支）；`alarm_service.py:38,63-65`（去重窗口固定 300s）。
- **问题**：规则引擎只发「开始」从不发「结束」。持续 1 小时的围栏侵入，会在每 300s 去重过期后**再生成新「告警开始」**；`alarm` 表「告警结束」枚举形同死字段。
- **影响**：长期违规造成告警堆积、人工负担大、数据无界增长。
- **建议**：设备离围栏/超阈值时产出配对「告警结束」候选；对同一 `(device_no, type, fence)` 已有开放「开始」未「结束」的告警做抑制（去重键加入开放状态判定）。

---

## 中严重度

| # | 模块 / 位置 | 问题 | 建议 |
|---|------------|------|------|
| 4 | 上行热路径 `rule_engine_v2.py:157-173` + `pipeline.py:79` ✅ **已修复(2026-07-20)** | 每条上行对每个含「间距」触发的激活计划各查一次 `latest_locations`（N 次放大，高频放大），且 `_distance_threshold` 亦逐计划重查 | 将 `latest_locations(project_id,ANTI_INTRUSION)` 与 `_distance_threshold` 提到 `build_alarm_candidates_v2` 的计划循环外、**每次上行只查 1 次**（同次上行 project_id 恒定、结果对所有计划相同）；`_plan_reference_machines` 改为接收预取的 `all_machines` 仅做计划级设备号过滤。守住：N→1 提循环外、懒加载（纯围栏/设备计划不触发）、部门隔离经 project_id 生效、nos 计划级绑定过滤不变。测试：`test_rule_engine_hotpath.py`（多计划仅查 1 次 + 无间距触发不查询） |
| 5 | 大屏 `/stats` `dashboard.py:243-244` ✅ **已修复(2026-07-20)** | 默认窗最长 12 个月，一次拉最多 50000 条告警进内存纯 Python 聚合（且 `to_alarm_out` 触发 project/work_plan 关联 N+1） | 新增 `aggregate_alarms_sql`：`GROUP BY date_trunc(周期), type/level/handle_status` 下推，仅返回聚合桶；dashboard 改用之，不再拉完整对象。实测 275 条告警：0.059s→0.004s(~15×)，且消除 N+1。测试：`test_dashboard_aggregation.py` |
| 6 | 历史快照预览/导出 `alarms.py:484-491,557` ✅ **已修复(2026-07-20)** | 每周期各跑一次全量查询（周×12月=52 次），内存拼装 | 改为一次查出整窗（首/末周期完整边界）+ Python 内 `_period_key` 分桶，N 次→1 次；`query_alarms_for_report` 支持 `limit=None` 不截断；空周期与部门隔离均保留。测试：`test_snapshot_preview.py`（空周期保留 + 单查询调用次数=1） |
| 7 | 事务边界 `database.py:30-36`、`alarm_service.py:181/198`、`alarms.py:276` ✅ **已修复(2026-07-20)** | service 有的只 flush、有的自 commit，所有权混乱；`get_db` 异常不回滚（#2 已修回滚） | `get_db` 统一回滚兜底（#2）；仅剩的「service 自 commit」实例 `update_alarm_media` 改为 `flush` 仅刷新，由 `update_alarm_media_endpoint` 统一 `db.commit()`；`create_alarm`/`handle_alarm` 本就 flush-only，全告警模块事务归属统一为「service 不提交、端点提交」 |
| 8 | 告警去重 `alarm_service.py:61-65,91` ✅ **已修复(2026-07-20)** | `exists` 后 `set` 非原子（并发可双写）；去重键缺内容维度 | `create_alarm` 改 `r.set(key,"pending",nx=True,ex=TTL)` 原子抢占：并发仅一方抢到占位，杜绝 `exists→set` 竞态双写；占位成功后 `r.set(key, id, xx=True, ex=TTL)` 写回真实告警 id 供规则引擎配对。测试：`test_create_alarm_dedup_refresh`(nx 失败续期)/`test_create_alarm_first_creates`(nx 抢占+写 id)/`test_create_alarm_dedup_atomic_no_db_row_on_hit`(命中不落库)。**设计权衡：未加 `alarm_info` 内容维度**——去重本意就是合并同一设备/围栏的「持续违规」为 1 条，加内容哈希会让每条读数都生成新告警，反而复活无界堆积，故不加 |
| 9 | **下发指令越权** `realtime.py:242-271` ✅ **已修复(2026-07-20)** | `send_command` 仅 `require_permissions("device:command")`，无 `get_data_scope` 校验，可跨部门给任意设备下发指令 | 注入 `db`/`DataScope`，经 `resolve_device`→`project_id`→`_scope_project_ids` 校验；越权返 404（不泄露设备存在）。测试：`test_send_command_dept_isolation` |
| 10 | **媒体公开** `media.py:120-168` ⚠️ **已决策：保持公开设计(2026-07-20)** | `/v1/media/{key}` 无 `get_current_user`，报警图片/视频凭 UUID 可被任意人访问，绕过部门隔离 | 用户决策：UUID 不可猜为**有意的设计权衡**（可用性优先，供前端 `<img>` 直连）。真正部门隔离需前端改走预签名 URL（`presigned_get_url`）并摒弃裸 `<img>`，列入**后续单独立项**，本轮不动代码以免破坏前端媒体展示 |
| 11 | 时区混杂 `job.py:29-34`、`rule_engine_v2.py:97/183`、`dashboard.py:229-235/287-294` ✅ **已加固(2026-07-20)** | 计划时间 naive、告警/上报 aware，大屏用 naive `datetime.combine`/`datetime.now()` 比 tz-aware 列，**正确性隐式依赖「服务器 locale 时区=Asia/Shanghai」**（部署到 UTC 机将整体漂移 8h） | 新建 `app/core/clock.py` 显式绑定业务时区 `Asia/Shanghai`：`now_local`/`day_start_local`/`day_end_local`(aware，与 timestamptz 列比较不依赖 PG session tz)、`now_naive_local`/`today_local`(北京 naive，与 naive 列同侧比较)、`ensure_aware_local`(补全用户 ISO)。**dashboard** 的 `today_start`/7 天趋势/`_resolve_trend_window` 边界全改 aware 北京时间；**rule_engine_v2** 的 `datetime.now()`→`now_naive_local()`（与 naive 的 plan_start/plan_end 同侧、消除 locale 依赖）。`requirements.txt` 显式声明 `tzdata`。测试：`test_clock.py`(6 例)。**遗留(另立项)**：`WorkPlan.plan_start/plan_end` 列彻底 naive→timestamptz(aware) + 数据迁移属更大改动，本轮先消除活跃风险源（locale 依赖），未改列类型 |
| 12 | 媒体上传阻塞 `media.py:73-99`、`minio_client.py:73-78` ✅ **已修复(2026-07-20)** | 单文件上限 100MB，在请求线程同步串行上传，占满线程池 | 改为 `upload_media` 为 `async` + 专用上传线程池 `minio_client.UPLOAD_EXECUTOR`（容量受限）并发上传，隔离 FastAPI 默认 anyio 线程池（承载 DB 查询等同步路由），避免大文件上传饿死 API 查询；`ensure_bucket` 加锁线程安全。多文件并行缩短耗时；仍流式传 `f.file`（内存不爆），大小校验/413 不变。**未采用 Celery**（属范围外中间件，且项目无 worker 实际运行）。测试：`test_media_upload_executor.py`（专用池前缀 + 并发 + 413 仍生效） |
| 13 | 告警列表无分页 `alarm_service.py:145-160`、`alarms.py:222-241` ✅ **已修复(2026-07-20)** | 仅 `limit` 无 `offset`，`total=len(items)` 最大 200，超 200 后不可见历史 | 后端抽 `_alarm_list_stmt` 复用过滤；`list_alarms` 改 `page/size` offset 分页，新增 `count_alarms`（`func.count` 子查询）返回**真实总数**；端点返回 `{items,total,page,size}`，对齐 persons/fences 既有分页模式，部门隔离不变。前端 `fetchAlarms` 加 `page/size`，`AlarmView` 用 `el-pagination`（total/sizes/prev/pager/next/jumper）+ 换页重载 + 筛选回第 1 页。测试：`test_alarm_pagination.py`（真实 total / 跨页不重叠 / 降序稳定 / 越界空页）；前端 `vue-tsc` 通过 |

---

## 低严重度（技术债 / 一致性）

| # | 位置 | 问题 | 建议 |
|---|------|------|------|
| 14 | `rule_engine_v2.py:46`（死开关）、`rule_engine.py:42/64/92`（死代码） ✅ **已修复(2026-07-20)** | `RULE_ENGINE_V2_ENABLED` 从未被读取；v1 多个函数未被调用 | 删 v1 死代码与死开关（v2 内联 `_distance_threshold`/`_join_media` 纯函数，pipeline 硬编码调 v2 无回归） |
| 15 | `base.py:17`（`CRUDService` 有测试 `test_crud_service.py` 引用故保留）、`data_scope.py:139` `register_model_link` 死函数 ✅ **已清理(2026-07-20)** | 无用代码 | 删除 `register_model_link`（无调用），`CRUDService` 因测试保留 |
| 16 | `web/src/types/index.ts:295-310` 缺 `work_plan_id` ✅ **已修复(2026-07-20)** | 前端 `Alarm` 类型与后端（返回 `work_plan_id`）不一致，溯源字段拿不到 | 补 `work_plan_id: number \| null`（`Alarm` 与 `AlarmItem` 均补，两接口字段现已完全对齐） |
| 17 | `AlarmView.vue` `list:any[]`→`Alarm[]`、`DashboardView.vue` 3 处 `catch(e:any)`→`catch(e:unknown)`+`instanceof Error` 收窄、`request.ts` 拦截器弹 `ElMessage` ✅ **已修复(2026-07-20)** | 异常被静默吞、失类型安全、缺 loading/错误态 | `AlarmView.list` 改 `Alarm[]`（导入 `Alarm` 类型）；`DashboardView` 三处 catch 由 `any` 改为 `unknown` 并用 `e instanceof Error ? e.message : 默认文案` 安全提取，`vue-tsc` 通过；拦截器现状已满足半数建议 |
| 18 | `config.py` 密码/验证码字段重复定义 ✅ **已修复(2026-07-20)** | 改一处漏一处 | 删 `config.py` 行 47-56 重复的 password_*/captcha_* 块，仅保留单一声明（后定义覆盖前定义，无害但混乱） |

---

## 优先级结论

**最该优先优化的 3 个模块**（按影响面与风险）：
1. **实时位置查询层** `location_service.py`（全表扫描，牵动大屏/在线看板/MQTT 上行热路径）
2. **告警处置闭环** `alarms.py` + `database.py`（消警指令与 DB 提交顺序错乱、事务无统一回滚）
3. **规则引擎** `rule_engine_v2.py`（告警只「开始」不「结束」导致堆积/重复告警）

**其次建议**：安全与隔离补漏（#9 下发指令越权、#10 媒体公开）——这两处直接突破已建成的 RBAC 四级隔离，属安全隐患，应尽早处理。

**建议执行顺序**：先 #2（事务/消警，改动小风险低）→ #9/#10（安全补漏）→ #1/#3（性能与告警语义，改动较大需回归）→ 中低严重度视资源推进。
