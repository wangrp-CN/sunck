# 涉铁工程智能监控平台 · 后端骨架

> 依据 `涉铁工程智能监控平台-开发计划.md` 搭建的**项目框架骨架**。本阶段仅搭建可运行的基础结构，
> **不含具体业务逻辑实现**（各模块以 `/ping` 占位，按开发计划阶段逐步填充）。

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
- 指标：`GET /metrics`

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
已应用隔离：`/api/v1/auth/users`、`/api/v1/projects`(list/create/get/update)。

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

## 下一步（按开发计划阶段推进）
- 阶段0：✅ 骨架 / RBAC / 部门数据隔离 / 验证码+密码强度 / 个人中心 / 前端骨架 / pre-commit 门禁 已全部完成
- 阶段1：实时链路闭环（MQTT 上报→落库→规则判定→WebSocket 推送）
- 阶段2~5：主数据、作业/告警、大屏、加固上线
