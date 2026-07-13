# 涉铁工程智能监控平台 · PyCharm 本地运行排障与启动指南

> 适用环境：macOS + PyCharm 2026.1.4 + 项目 `rail_monitor/`（FastAPI 后端）
> 最后更新：2026-07-13（基于实际截图排查修复）

---

## 一、问题根因（已定位并修复）

### 你遇到的两个现象

| 现象 | 截图证据 | 根因 |
|------|----------|------|
| 运行配置显示 **「无法编辑此配置」** | 截图2：右侧灰色 + 红字「运行配置错误: 由于插件不可用或配置数据无效, 导致配置损坏」 | **配置文件损坏**——`type="PythonConfiguration"` 在 PyCharm 2026 中不被识别，应使用 `type="PythonConfigurationType"` |
| 配置 XML 路径全部错位 | 截图1：`SDK_HOME=$PROJECT_DIR$/.venv/bin/python`、`WORKING_DIRECTORY=$PROJECT_DIR$`（缺 `rail_monitor/` 层） | **4份旧配置互相矛盾**，且放置位置与 `$PROJECT_DIR$` 解析不匹配 |

### 已执行的修复操作

1. **删除了全部 4 份旧的/损坏的运行配置文件**：
   - `RimpCode/.idea/runConfigurations/RailMonitor.xml`
   - `rail_monitor/.idea/runConfigurations/RailMonitor.xml`
   - `RimpCode/.run/RailMonitor.run.xml`
   - `rail_monitor/.run/RailMonitor.run.xml`

2. **重建了 2 份正确的配置**（互不冲突，各自匹配其所在目录的 `$PROJECT_DIR$`）：

   | 文件 | 适用场景 | `$PROJECT_DIR$` 解析为 |
   |------|----------|------------------------|
   | `rail_monitor/.idea/runConfigurations/RailMonitor.xml` | **主方案**（打开 rail_monitor 时） | `/.../rail_monitor/` |
   | `RimpCode/.idea/runConfigurations/RailMonitor.xml` | 备用（打开 RimpCode 根时） | `/.../RimpCode/` |

3. **关键修正项**（vs 旧版）：
   - ✅ `type`: `PythonConfiguration` → **`PythonConfigurationType`**（PyCharm 2026 兼容）
   - ✅ 每份配置的路径与其放置位置匹配，不会错位
   - ✅ 统一使用 uvicorn 启动方式（而非 python app/main.py），不依赖工作目录解析

---

## 二、五个问题的逐一诊断结论

| # | 问题 | 结论 | 状态 |
|---|------|------|------|
| 1 | 解释器是否正确 | `.venv`（Python 3.13.12）存在，依赖**全部已装好** | ✅ 正常 |
| 2 | 运行配置是否正确 | 旧配置损坏+错位 → **已删除重建** | ✅ 已修复 |
| 3 | 依赖包是否全装 | fastapi/uvicorn/sqlalchemy/psycopg2/redis/paho-mqtt/minio/celery/alembic/passlib 等**全部在** | ✅ 正常 |
| 4 | 浏览器无法访问 | 端口 8000 空闲、防火墙无影响；原因是**服务未通过正确配置启动** | ✅ 已定位 |
| 5 | 排查步骤与方案 | 见下文 | ✅ 见下 |

---

## 三、修复后你需要在 PyCharm 中做的操作

### ⚠️ 第一步：让 PyCharm 重新加载新配置（必须！）

因为修改了 `.idea/` 目录下的文件，PyCharm **需要重新加载项目才能识别新配置**。请按以下顺序操作：

#### 方式 A（推荐）：关闭后重新打开项目
1. 关闭当前 PyCharm 项目（`File → Close Project`）
2. 重新 `Open`，这次选择 **`/Users/wangpeng/PycharmProjects/RimpCode/rail_monitor`**
3. 等待索引完成（右下角进度条走完）
4. 打开 `Run → Edit Configurations`，左侧应能看到 **RailMonitor**（不再有红字报错）

#### 方式 B：不关闭项目的情况下刷新
1. 在 PyCharm 菜单选 `File → Invalidate Caches / Restart → Just Restart`
2. 重启后自动重新加载 `.idea/` 下的配置文件
3. 再去 `Run → Edit Configurations` 查看 RailMonitor 是否正常显示

### 第二步：确认 Python 解释器

1. `Settings (⌘,) → Python Interpreter`
2. 若显示的不是 `.venv`，点齿轮 ⚙️ → `Add → Virtualenv Environment → Existing environment`
3. 填入：`/Users/wangpeng/PycharmProjects/RimpCode/rail_monitor/.venv/bin/python`
4. 确定，下方列表应出现 fastapi/uvicorn/sqlalchemy 等包名

### 第三步：启动并浏览器访问

1. 顶部工具栏选中 **RailMonitor**，点 **▶ Run**（`⌃R`）
2. Run 窗口应出现：
   ```
   INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
   INFO:     Application startup complete.
   ```
3. **浏览器打开以下地址之一即可看到结果**：
   - **`http://127.0.0.1:8000/docs`** ← **推荐首选**（Swagger 交互式 API 文档页面，可在线测试接口）
   - `http://127.0.0.1:8000/redoc` ← ReDoc 风格文档
   - `http://127.0.0.1:8000/health` ← 纯 JSON 健康检查：`{"status":"ok","app":"涉铁工程智能监控平台","env":"development"}`

> 当前是骨架阶段，业务逻辑尚未实现，可看到的接口只有 `/health`、`/metrics`、各模块 `/ping` 和 WebSocket `/ws/alarm`。打开 `/docs` 能看到完整路由列表即代表运行成功。

---

## 四、如果重启后仍然有问题

### 问题 A：「Run 列表里看不到 RailMonitor」

**原因**：`.idea/` 被 gitignore 或 PyCharm 未监视。

**解决**：手动创建（只需做一次）：
1. `Run → Edit Configurations`
2. 左上角 **`+`** → 选 **`Python`**
3. 填写：
   - Name: `RailMonitor`
   - Python interpreter: 选 `rail_monitor/.venv/bin/python`
   - Script path: 点右侧 `...` 找到 `rail_monitor/.venv/bin/uvicorn`
   - Parameters: `app.main:app --host 0.0.0.0 --port 8000 --reload`
   - Working directory: 点 `...` 选 `rail_monitor` 目录
   - Env files: 可选，指向 `rail_monitor/.env`
4. 点 **Apply → OK**

### 问题 B：启动时报 `ModuleNotFoundError: No module named 'app'`

**原因**：Working directory 不是 `rail_monitor`，导致 Python 找不到 `app` 包。

**解决**：回到问题 A 步骤 3，确保 Working directory = `rail_monitor` 目录（含 `app/` 的那层）。

### 问题 C：启动时报 `No module named 'fastapi'`

**原因**：解释器选的是系统 Python 而非 `.venv`。

**解决**：确保解释器路径以 `.venv/bin/python` 结尾（步骤二）。

### 问题 D：`address already in use: port 8000`

**原因**：端口被其他进程占用。

```bash
# 查看谁占用了 8000
/usr/sbin/lsof -i :8000
# 杀掉它
kill -9 <PID>
```

或改端口：运行配置 Parameters 里把 `8000` 改成 `8010` 等。

### 问题 E：服务起来了但浏览器打不开

按顺序检查：
1. 用 **`http://127.0.0.1:8000/docs`**（不是 localhost，127.0.0.1 更可靠）
2. Run 窗口确认有 `Application startup complete.`（没有说明启动失败，看上方报错）
3. 终端兜底验证：`curl -s http://127.0.0.1:8000/health` 应返回 JSON
4. 如果 curl 正常但浏览器不行 → 清除浏览器缓存 / 试无痕模式 / 换个浏览器

---

## 五、常见错误速查表

| 报错信息 | 含义 | 解决方法 |
|----------|------|----------|
| **由于插件不可用或配置数据无效, 导致配置损坏** | 配置 type 错误 / 多份冲突 | ✅ 本次已修复；若仍出现→删 .idea 下 xml 后重启 PyCharm |
| `ModuleNotFoundError: No module named 'app'` | 工作目录不对 | Working dir 改为 rail_monitor |
| `No module named 'fastapi'` | 解释器没选 venv | 解释器改选 .venv/bin/python |
| `address already in use: port 8000` | 端口占用 | 换端口 或 kill 占用进程 |
| `ConnectionRefusedError` | 服务没起来 | 先确认 Run 窗口 startup complete |
| `/docs` 能开但接口返回 404/502 | 骨架阶段正常 | 业务逻辑待实现，不影响验证框架 |

---

## 六、最终验证清单（逐项勾选）

- [ ] **PyCharm 重新加载后** `Run → Edit Configurations` 中能看到 **RailMonitor**（无红字报错）
- [ ] **Python Interpreter** = `rail_monitor/.venv/bin/python`（Settings 中可见 fastapi/uvicorn 等包）
- [ ] 点 **▶ Run** 后 Run 窗口出现 `Uvicorn running on http://0.0.0.0:8000` + `Application startup complete.`
- [ ] 浏览器访问 **`http://127.0.0.1:8000/docs`** 显示 Swagger 页面（有接口列表）
- [ ] 浏览器访问 **`http://127.0.0.1:8000/health`** 返回 `{"status":"ok",...}`

---

## 附 1：不用 PyCharm 的终端启动方式（用于对照验证）

```bash
cd /Users/wangpeng/PycharmProjects/RimpCode/rail_monitor
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# 另开终端验证：
curl -s http://127.0.0.1:8000/health
```

## 附 2：本次修复后的运行配置内容参考

主配置文件位置：`rail_monitor/.idea/runConfigurations/RailMonitor.xml`

核心参数（打开 rail_monitor 目录时生效）：
- 类型：`PythonConfigurationType`（PyCharm 2026 标准）
- SDK：`$PROJECT_DIR$/.venv/bin/python` → 实际 = `rail_monitor/.venv/bin/python`
- 脚本：`$PROJECT_DIR$/.venv/bin/uvicorn`
- 参数：`app.main:app --host 0.0.0.0 --port 8000 --reload`
- 工作目录：`$PROJECT_DIR$` → 实际 = `rail_monitor`
- 环境文件：`$PROJECT_DIR$/.env`
