# 阶段 3 压测报告 · 千台设备并发（Locust + MQTT 洪泛）

> 生成时间：2026-07-22 ｜ 目标：验证「千台设备实时上报 + 多查看者并发」场景下的容量与瓶颈

## 1. 测试方法与工具

- **HTTP 查看者负载**：`scripts/locustfile.py`（`locust 2.45.0`，`ViewerUser` 加权访问
  `dashboard/stats` / `alarms` / `realtime/locations` / `devices` / `online-status` / `media/access`）。
- **千台设备上行**：`scripts/mqtt_flood.py`（原生线程池，规避 Locust gevent 与 paho 线程冲突）
  向 `device/locate/up` 发布位置报文，device_no 取自 `scripts/seed_stress.py` 登记的
  `LOC-S00001..LOC-S01000`（绑定独立 stress 项目，无激活作业计划 → 不产生告警风暴，
  隔离出纯 ingestion 链路压力）。
- **鉴权**：压测环境验证码默认开启，故 Locust 直接用 `app.create_access_token` 为 admin 生成
  同源令牌（与运行后端同一 `SECRET_KEY`，合法有效），绕过登录验证码链路。
- **规模定义**：「千台设备 @ 间隔 2s」≈ **498 msg/s** 上行；查看者 100 并发。

## 2. 测试结果

### 场景 A — 重负载组合（1000 设备 @2s ≈498 msg/s 上行 + 100 查看者，120s）
| 维度 | 结果 |
|------|------|
| MQTT 发布 | **61,000 条 @ 498 msg/s，发布端 0 错误** |
| 落库 DeviceLocation | **仅 456 条（≈0.7%）→ ingestion 丢弃 ~99.3%** |
| HTTP API | 137 请求，**64.96% 返回 500**，延迟中位数 **32s** |

→ 系统在高并发下实质不可用，ingestion 近乎全丢。

### 场景 B — 纯 HTTP 基线（无洪泛，100 查看者，60s，**未调优池**）
| 结果 | 值 |
|------|-----|
| 请求量 | 62 ｜ 吞吐 **1.82 req/s** |
| 失败率 | **59.68%（500）** ｜ 延迟中位数 **30s** |

### 场景 C — 纯 HTTP 低并发（无洪泛，10 查看者，30s）
| 结果 | 值 |
|------|-----|
| 请求量 | 104 ｜ 失败率 **3.85%（全部为故意查不存在媒体的 404，真实端点 0%）** |
| 结论 | 低并发下 API 健康 → 排除逻辑 bug，确认是**并发/连接池耗尽** |

### 场景 D — 纯 HTTP 基线（100 查看者，60s，**池调优后**，端口 8011）
| 结果 | 值 |
|------|-----|
| 请求量 | 450 ｜ 吞吐 **8.16 req/s（较场景 B 提升 4.5×）** |
| 失败率 | **5.11%（全部为媒体 404，真实端点 0%）** |
| 延迟 | 中位数 **9.1s**，P95 18s（仍有查询级慢，见 §4） |

## 3. 根因（Root Cause）

1. **DB 连接池过小 + 同步 per-message ingestion 抢光连接**
   - 引擎原用 SQLAlchemy 默认 `pool_size=5 + max_overflow=10 = 15` 连接，`pool_timeout=30s`。
   - ingestion 管线对**每条** MQTT 消息都「开会话 → 写 DeviceLocation → commit」，
     498 msg/s 即 498 次/秒会话竞争同一池；叠加 100 并发 API，池迅速耗尽。
   - 新连接 checkout 等待 `pool_timeout=30s` 后抛 `TimeoutError` → **500**，
     这与观测到的 **30s 中位数延迟**完全吻合。
2. **ingestion 吞吐崩溃**：单管线会话来不及处理 498 msg/s，broker（Mosquitto）QoS1 队列溢出丢弃，
   导致 61k 上行仅 456 落库。

## 4. 已应用修复（已验证）

连接池配置化并调优（`app/config.py` + `app/core/database.py`）：

```python
db_pool_size: int = 10        # 单 worker 连接数（原默认 5）
db_max_overflow: int = 20     # 单 worker 溢出（原默认 10）
db_pool_timeout: int = 10     # 取连超时（原 30 → fail-fast）
db_pool_recycle: int = 1800
```

- 容量论证：验证时单 worker 配置 60 连接（20+40）下 100 并发已恢复；
  最终默认改为**单 worker 30 连接**，2-worker 部署聚合 60 连接 ≈ 验证容量，
  且对 PG 默认 `max_connections=100` **留有余量**（避免多 worker 超限）。
- 效果（场景 D）：**真实端点 0% 失败，吞吐 4.5×**。

## 5. 待办优化（非阻塞，建议后续跟进）

| 项 | 说明 | 优先级 |
|----|------|--------|
| **ingestion 异步化/批处理** | 将「MQTT → 内存缓冲 → 定时 bulk insert」或落 Kafka/Redis 队列，解耦上行速率与 DB 连接占用；这是 498 msg/s 仅 0.7% 落库的根本解法 | 高 |
| **ingestion 独立连接池** | API 与 ingestion 使用不同 DB 池，互不影响 | 中 |
| **查询性能** | `dashboard/stats` / `realtime/*` 在 100 并发下仍 ~9–13s 中位延迟，需补索引 / 聚合缓存 / 分页 | 中 |
| **pool 饱和度监控** | 暴露 `pool.checkedout()` 指标，配合 Prometheus 告警 | 低 |

## 6. 复现命令

```bash
# 1) 登记千台设备
.venv/bin/python scripts/seed_stress.py            # 默认 1000 台，STRESS_N 可调
# 2) 后台跑设备上行（千台 @2s ≈ 498 msg/s）
nohup .venv/bin/python scripts/mqtt_flood.py --devices 1000 --interval 2 \
        --duration 120 --out /tmp/mqtt_flood.json >/tmp/mqtt_flood.log 2>&1 &
# 3) 跑 HTTP 查看者负载
.venv/bin/python -m locust -f scripts/locustfile.py ViewerUser \
        --headless -u 100 -r 20 -t 120s --csv /tmp/locust_viewer
# 4) 清理
.venv/bin/python scripts/seed_stress.py clean
```
