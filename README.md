# 涉铁工程智能监控平台

> 涉铁工程智能监控平台（后端 + 前端，告警可视化方向）：已实现 RBAC / 部门数据隔离 / 实时链路闭环 / 告警报表与趋势 / 跨周期历史快照 / 仪表盘周期联动等能力，详见后续章节。

## 技术栈

FastAPI + Uvicorn · SQLAlchemy 2.0 + Alembic · PostgreSQL · Redis · MQTT(paho/EMQX) ·
MinIO · Celery · WebSocket · Prometheus，前端（独立工程）Vue3 + 高德地图 + ECharts。

## 目录结构

```
rail_monitor/
├── app/
│   ├── main.py            # 应用入口（装配路由/中间件/生命周期）
│   ├── config.py          # 配置（.env 驱动）
│   ├── core/              # 基础设施：日志/数据库/Redis/安全/响应/异常/依赖
│   ├── model/             # ORM 模型（按功能模块拆分）
│   ├── schema/            # Pydantic 请求/响应模型（common + auth 示例）
│   ├── service/           # 业务逻辑层（CRUDService 基类）
│   ├── api/               # 路由层（v1 各模块占位）
│   ├── mqtt/              # 设备实时上行/下行接入（接口需求 §3.1）
│   └── ws/                # WebSocket 实时推送（告警/轨迹）
├── alembic/               # 数据库迁移
├── tests/                 # 冒烟测试
├── .env / .env.example    # 环境变量
├── pyproject.toml         # 工程元数据 + 工具配置
├── requirements.txt       # 依赖清单（venv 安装依据）
├── docker-compose.yml     # 依赖服务一键编排
└── nginx.conf             # 反向代理
```

## 本地运行

### 1. 安装依赖（已内置 .venv）
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 按需修改
```

### 2. 启动依赖（可选，docker 或本机原生 PG/Redis/MQTT/MinIO）
```bash
docker compose up -d
```

### 3. 启动应用
```bash
python app/main.py                  # 直接运行（host/port 取自配置）
# 或开发热重载
uvicorn app.main:app --reload --port 8000
```
- 健康检查：`GET /health`
- 接口文档：`GET /docs`
- 指标：`GET /metrics`（Prometheus 格式，业务指标见下表）

  | 指标名 | 类型 | 维度 | 含义 |
  |--------|------|------|------|
  | `http_requests_total` | Counter | method, path, status | HTTP 请求总数 |
  | `http_request_duration_seconds` | Histogram | method, path | HTTP 请求时延分布（秒） |
  | `alarms_created_total` | Counter | alarm_type, alarm_level | 实时链路产生的告警总数 |
  | `mqtt_messages_total` | Counter | device_type | MQTT 设备上行报文总数 |
  | `ws_connections` | Gauge | — | 当前 WebSocket 在线连接数 |

  > 自监控排除：`/metrics` 与 `/health` 自身请求不计入 `http_requests_total`。

### 4. PyCharm 直接运行
项目根已提供 `.run/RailMonitor.run.xml`，在 PyCharm 的 Run/Debug 配置中即可看到
**RailMonitor** 配置（指向 `.venv` 解释器与 `app/main.py`），无需手动配置。

## 数据库迁移
```bash
alembic revision --autogenerate -m "init"
alembic upgrade head
```

## RBAC 鉴权与权限管理（已实现）

基于 JWT 的无状态鉴权，已完成用户/角色/权限（RBAC）完整闭环。

### 初始化数据（播种）
首次建表后执行，创建默认权限、角色与超级管理员：
```bash
.venv/bin/python scripts/seed_rbac.py
```
- 超级管理员账号：`admin` / `Admin@123456`（生产请用环境变量 `DEFAULT_ADMIN_PASSWORD` 覆盖）
- 内置角色：`admin`(全部权限)、`project_manager`、`monitor`、`operator`、`guest`
- 数据幂等，可重复执行。

### 认证接口（`/api/v1/auth`）
| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| POST | `/login` | 登录，返回 access/refresh 令牌 | 公开 |
| POST | `/refresh` | 用刷新令牌换取新令牌 | 公开 |
| GET  | `/me` | 当前用户信息（含角色/权限） | 登录 |
| PATCH | `/me` | 修改个人资料（昵称/头像/邮箱/手机） | 登录 |
| POST | `/logout` | 退出登录（无状态） | 登录 |
| POST | `/change-password` | 修改密码（校验密码复杂度） | 登录 |
| GET  | `/captcha` | 获取图形验证码（base64 + key，存 Redis） | 公开 |
| GET  | `/permissions` | 权限列表 | 登录 |
| POST | `/register` | 新建用户并分配角色（校验密码复杂度） | `user:add` |
| GET  | `/users` | 用户分页列表 | `user:list` |
| GET  | `/roles` | 角色列表 | `role:list` |
| POST | `/roles` | 新建角色 | `role:add` |
| PUT  | `/roles/{id}` | 更新角色 | `role:edit` |
| DELETE | `/roles/{id}` | 删除角色（系统内置不可删） | `role:delete` |
| POST | `/roles/{id}/permissions` | 分配角色权限 | `role:assign` |

### 关键特性
- **密码加密**：bcrypt 哈希存储，登录校验不回显账号是否存在。
- **登录失败重试限制**：连续失败达到 `max_login_attempts`(默认5)次锁定 `account_lock_minutes`(默认15)分钟（返回 423）。
- **图形验证码**：`GET /captcha` 生成（base64 图片 + key 存 Redis，TTL 可配），登录按 `captcha_enabled` 开关校验；测试环境默认关闭（见 `tests/conftest.py`）。
- **密码强度策略**：注册/改密校验最小长度 + 大小写/数字/特殊字符开关（取自 `app/config.py` 的 `password_*` 配置），含弱密码黑名单。
- **统一错误响应**：所有响应均为 `ApiResponse` 结构 `{code, message, data}`，HTTP 异常也统一转换。
- **访问控制**：`require_permissions(*codes)` / `require_roles(*codes)` 依赖；超级管理员自动通过。

## 部门数据隔离（已实现）

在 RBAC 之上按用户角色合并出统一数据范围 `DataScope`，业务查询经 `apply_data_scope(stmt, model, scope)` 自动过滤。

### 数据范围四级（`Role.data_scope`）
| 值 | 含义 | 可见数据 |
|----|------|----------|
| 1 | 全部 | 不做过滤（超级管理员强制为全部） |
| 2 | 自定义部门 | 角色经 `role_dept` 关联的部门（**自动含其下级**） |
| 3 | 本部门及以下 | 用户所属部门及其全部下级 |
| 4 | 仅本人 | `created_by == 当前用户` |

多角色取并集（本部门∪自定义部门取部门并集；仅本人作为额外 OR 叠加）。

### 部门与角色部门接口
| 方法 | 路径 | 说明 | 权限 |
|------|------|------|------|
| GET  | `/departments` | 部门扁平列表 | `dept:list` |
| GET  | `/departments/tree` | 部门树形结构 | `dept:list` |
| POST | `/departments` | 新建部门 | `dept:add` |
| PUT  | `/departments/{id}` | 更新部门 | `dept:edit` |
| DELETE | `/departments/{id}` | 删除部门（软删，有子部门/用户占用则拒绝） | `dept:delete` |
| POST | `/roles/{id}/departments` | 分配角色自定义数据范围部门 | `role:assign`（仅 `data_scope=2`） |

### 接入方式（业务接口）
```python
from app.core.deps import get_data_scope
from app.core.data_scope import DataScope, apply_data_scope

@router.get("")
def list_x(db=Depends(get_db), scope: DataScope = Depends(get_data_scope), ...):
    stmt = select(X)
    stmt = apply_data_scope(stmt, X, scope)   # 直接携带 dept_id → DIRECT；经 project → VIA_PROJECT
    ...
```
新增业务模型需隔离时，在 `app/core/data_scope.py` 的 `_MODEL_DEPT_LINK` 注册 `DIRECT` 或 `VIA_PROJECT` 即可。
已应用隔离：`/api/v1/auth/users`、`/api/v1/projects`(list/create/get/update)、`/api/v1/alarms`(list/get/export/report/snapshot **及 `/{id}/handle`、`/{id}/media` 处置/媒体更新**)、`/api/v1/attachments`(upload/list/delete，**按实体所属 project 归口隔离**)、`/api/v1/devices`·`persons`·`machines`·`fences`·`jobs`、`/api/v1/realtime`(locations/trajectory)、`/api/v1/dashboard`(stats/recent-alarms)。

### 调用示例
```bash
# 登录
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"Admin@123456"}'
# 携带令牌访问受保护接口
curl http://127.0.0.1:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access_token>"
```

## 前端工程 `web/`（已实现骨架）

基于 **Vite + Vue3 + TypeScript + Pinia + Vue Router + Element Plus** 的 SPA 骨架，已打通路由守卫、Pinia 状态、Axios（`/api` 代理到 FastAPI）与统一响应解包。
详见 [`web/README.md`](web/README.md)。开发：`cd web && npm install && npm run dev`（http://localhost:5173）。

## 工程门禁（pre-commit，已实现）

提交前自动执行：`ruff`(lint+format) + `black` + 基础钩子（行尾/EOF/YAML/大文件/合并冲突）；`pytest` 挂在 `pre-push`。
配置文件 `.pre-commit-config.yaml`，本地安装：`pip install pre-commit && pre-commit install`。
> 注：仓库已 `git init` 并打好基线提交；首次提交会触发钩子自动格式化（属正常行为，按提示重新 `add` 提交即可）。

## 告警可视化与历史快照（已实现）

告警模块已形成完整可视化闭环：趋势切换 → 单周期下钻 → 按粒度导出 → 跨周/月历史快照 → 仪表盘按周期联动。

### 关键端点
| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/v1/alarms/report` | 报表汇总，`granularity`(day/week/month) 分桶；`summary_only=true` 仅返回分布 |
| GET  | `/api/v1/alarms/export` | 导出 Excel/PDF。支持 `granularity`+`period`（整周/整月）或 `snapshot=true`（跨周期多表快照） |
| GET  | `/api/v1/alarms/snapshot/preview` | 快照预览（JSON）：概览 + 各周期分布 + 按项目汇总，与 Excel/PDF 快照**同源**，供前端「预览 → 导出」确认 |
| GET  | `/api/v1/dashboard/stats` | 大屏聚合，支持 `granularity`+`start`+`end` 周期联动，返回 `alarm_trend_period` / `alarms_window` / `alarms_current_period` |

> 趋势图、报表、导出、仪表盘四者共用同一套 `_period_key` 分桶口径（见 `app/service/alarm_service.py`），切换周期时数据逐桶一致。

### 趋势图周期切换（`web/src/views/AlarmView.vue`）
天/周/月单选 + 单周期下钻；下钻明细与按粒度导出行数一一对应。

### 跨周/月历史快照（`/export?snapshot=true`）
按天/周/月将所选范围拆为多个周期，**每个周期单独成表**：Excel 为多 sheet（`概览` + 每周期明细（按项目分组）+ `明细合并` + `项目汇总`），PDF 为概览 + 分布表 + 合并明细 + 按项目分布。覆盖所有周期（含空周期），便于连续脉络对比。

### 快照预览（报表弹窗）
`AlarmView` 的「告警报表」弹窗内提供「预览快照」按钮：调用 `/snapshot/preview` 渲染**概览指标 + 各周期分布（可展开看按项目拆分）+ 按项目汇总（带合计行）**，数据与导出文件同源，确认无误后再点「导出快照 Excel / PDF」。

### 仪表盘按周期联动（`web/src/views/DashboardView.vue`）
趋势卡支持天/周/月 + 日期范围；切换时「告警总数 → 区间告警」「今日告警 → 本周期告警」同步刷新，与趋势图、报表/导出三者逐桶一致。

### 四端图表一致性（重点）
告警趋势图在 **PDF 导出 / Excel 导出 / DashboardView 迷你图 / AlarmView 报表弹窗趋势区** 四端保持同源、同形态、同配色：

| 端 | 实现 | 配色（围栏侵入 / 间距过近 / 设备自报） |
|----|------|----------------------------------------|
| PDF 趋势图 | reportlab `VerticalBarChart`（`categoryAxis.style="stacked"`）+ 三层系列 + 顶部 `Legend` | 红 `#C00000` / 橙 `#ED7D31` / 蓝 `#2E75B6` |
| Excel 概览图 | openpyxl `BarChart`（`grouping="stacked"` + `overlap=100`）+ 三色系列 + 底部图例 | 同上 |
| DashboardView 迷你图 | `.bar-track.stack` + 3×`.bar-seg` 分色 + `.mini-legend` | 同上 |
| AlarmView 弹窗趋势区 | 同 DashboardView 结构（复制「按类型分色堆叠」） | 同上 |

- **同源**：四端均来自 `_compute_snapshot` / `build_snapshot_payload` / `SnapshotPreviewResult`，与 `/alarms/report`、`/dashboard/stats` 共用 `_period_key`（day/week/month）分桶口径。
- **按类型分色堆叠**：同一周期三类告警纵向叠加，红=围栏侵入(fence_intrusion) / 橙=间距过近(distance_too_close) / 蓝=设备自报(device_alarm)，均带图例。
- 前端最大值取用统一封装 `web/src/utils/snapshot.ts` 的 `snapTrendMaxOf`，避免各端计算口径漂移。

### 前端 · 其它平台模块（作业计划甘特视图）
`web/src/components/WorkPlanGantt.vue` 按 `plan_start~plan_end` 渲染分色横条（红=监控中 / 橙=执行中 / 绿=已完成 / 灰=草稿），含设备数徽标、时间轴刻度、当前时间竖线；`JobView` 集成甘特卡片，与 rule_engine_v2 计划门控（仅激活计划产生告警）打通。

### 测试覆盖
| 层 | 范围 | 用例数 | 说明 |
|----|------|--------|------|
| 后端 | run_demo.sh [3.6/6] 门禁（7 文件：`test_media`/`test_attachments`/`test_realtime`/`test_dashboard_scope`/`test_job_alarm`/`test_alarm_report`/`test_snapshot_preview`） | **53** | pytest 全绿，含堆叠图/快照预览↔导出一致性/部门隔离 |
| 前端 | Vitest（8 文件：`DailyTrendChart`/`MapPanel`/`WorkPlanGantt`/`geo`/`period`/`snapshot`/`AlarmView`/`DashboardView`） | **40** | 含分色堆叠迷你图、甘特、快照纯函数、地图模拟、周期分桶 |

> 测试已纳入 `run_demo.sh` 门禁：后端 [3.6/6] 与前端 [3.7/6]（依赖→构建→Vitest）任一失败即终止联调；可用 `SKIP_TESTS=1` / `SKIP_FE=1` / `SKIP_FE_BUILD=1` 局部跳过。

### 一键联调
```bash
bash scripts/run_demo.sh                 # 全流程：服务→迁移→播种→测试→前端门禁→后端→模拟器→自动验证
bash scripts/run_demo.sh --skip-services  # 服务已运行时跳过原生服务启动
# 跳过门禁：SKIP_TESTS=1（后端 pytest）   SKIP_FE=1（前端门禁）
```
脚本在 `[6/6]` 自动实证：实时位置、告警列表、轨迹、报表、周期联动自洽、历史快照多表导出。

## 里程碑与后续

- 阶段0（骨架 / RBAC / 部门隔离 / 验证码 / 前端骨架 / pre-commit 门禁）：✅ 已完成
- 阶段1（实时链路：MQTT 上报 → 落库 → 规则引擎 v2 判定 → WebSocket 推送）：✅ 已完成
- 阶段2~5（主数据 / 作业计划 / 告警 / 大屏）：✅ 告警可视化闭环已交付（趋势 / 导出 / 快照 / 仪表盘联动 / 四端图表一致 / 甘特视图）
- 阶段收尾（2026-07-17）：✅ 四端图表一致性 + 测试护栏（后端 53 / 前端 40） + 前端打包优化（消除 >500KB chunk 警告）
- 可选后续：~~快照按项目分 sheet~~ ✅ 已完成（2026-07-17，Excel 每项目一张明细 sheet `项目-{name}` + PDF 每项目明细节 + 预览 `projects_detail`，三端同源 `period_rows`/`project_names`，与既有「项目汇总」summary 互补，预览↔导出逐桶一致）；~~仪表盘其余卡片（设备在线率 / 围栏统计）按周期联动~~ ✅ 已完成（2026-07-17，复用 /online-status 心跳口径 + WorkPlan 窗口重叠判定）；~~设备在线看板 / 围栏地图绘制 / 轨迹回放播放器~~ ✅ 已完成。
