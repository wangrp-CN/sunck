#!/usr/bin/env bash
# 一键联调：原生服务 → 迁移 → 播种 → 后端 → 设备模拟器 → 自动验证
#
# 用法：
#   bash scripts/run_demo.sh                # 全流程（含启动 PG/Redis/MQTT/MinIO）
#   bash scripts/run_demo.sh --skip-services  # 服务已在运行时跳过启动原生服务
#   bash scripts/run_demo.sh --skip-services --port 8011  # 避开被占用的 8000 端口
#
# 端口：默认 8000；用 --port N 指定。若指定端口已被占用（如 PyCharm 后端），
#       脚本会友好报错退出而不会自动终止外部进程——请换端口或先释放。
#
# 门禁开关（失败即终止联调）：
#   SKIP_TESTS=1   跳过后端 pytest 回归门禁（[3.6/6]）
#   SKIP_FE=1      跳过前端门禁（[3.7/6]：依赖安装 + 构建 + Vitest 单测）
#   SKIP_FE_BUILD=1 跳过前端构建，仅跑 Vitest 单测（[3.7/6] 加速纯回归；SKIP_FE 仍整体跳过）
#
# 前置：Mac 上已 brew install postgresql@17 redis mosquitto；项目 .venv 已装依赖。
# 停止：脚本末尾会打印 kill 命令；停止原生服务用 scripts/native-services.sh stop

set -o pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv/bin"
cd "$ROOT"

SKIP_SERVICES=0
PORT=8000
while [ $# -gt 0 ]; do
  case "$1" in
    --skip-services) SKIP_SERVICES=1; shift ;;
    --port) PORT="${2:-8000}"; shift 2 ;;
    --port=*) PORT="${1#*=}"; shift ;;
    *) shift ;;
  esac
done

c_blue='\033[1;34m'; c_green='\033[1;32m'; c_red='\033[1;31m'; c_reset='\033[0m'
log()  { echo -e "${c_blue}>>>${c_reset} $*"; }
ok()   { echo -e "${c_green}✓${c_reset} $*"; }
err()  { echo -e "${c_red}✗ $*${c_reset}"; }

# 端口是否被占用（可移植：用 venv python 的 socket.connect 探测，不依赖 lsof）
# 返回 0=被占用(有进程监听) / 1=空闲。避免某些环境(如缺少 lsof 的 CI runner)误判。
port_in_use() {
  "$VENV/python" - "$PORT" <<'PY' >/dev/null 2>&1
import socket, sys
port = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(0.5)
try:
    sys.exit(0 if s.connect_ex(("127.0.0.1", port)) == 0 else 1)
finally:
    s.close()
PY
}

[ -x "$VENV/python" ] || { err "未找到 .venv，请先创建虚拟环境并安装依赖"; exit 1; }
command -v brew >/dev/null 2>&1 || log "警告：未检测到 brew，native-services.sh 可能无法启动原生服务"

# ---- [1/6] 原生服务 ----
if [ "$SKIP_SERVICES" -eq 1 ]; then
  log "[1/6] 跳过原生服务启动（--skip-services）"
else
  log "[1/6] 启动原生服务 (PG/Redis/MQTT/MinIO)"
  bash scripts/native-services.sh start || log "原生服务启动失败，请手动确认 PG/Redis/Mosquitto 已运行"
fi

# ---- [2/6] 迁移 ----
log "[2/6] 数据库迁移 (alembic upgrade head)"
"$VENV/alembic" upgrade head || { err "迁移失败"; exit 1; }
ok "迁移完成"

# ---- [3/6] 播种 ----
log "[3/6] 播种 RBAC + 演示数据"
"$VENV/python" scripts/seed_rbac.py || log "seed_rbac 返回非零（可能已存在，可忽略）"
"$VENV/python" scripts/seed_demo.py || log "seed_demo 返回非零（可能已存在，可忽略）"

# 3.5) 清空历史告警 + Redis 去重键，保证演示数据自洽（仅演示脚本；生产请勿使用）
log "[3.5/6] 清空历史告警与去重缓存（演示自洽，确保 v2 溯源比例准确）"
"$VENV/python" -c "from app.core.database import SessionLocal; from sqlalchemy import text; db=SessionLocal(); db.execute(text('DELETE FROM alarm')); db.commit(); print('alarm cleared')" 2>/dev/null || log "清空告警失败（可忽略）"
"$VENV/python" -c "
from app.core.redis import get_redis_client
r=get_redis_client()
if r is not None:
    ks=list(r.scan_iter('alarm:dedup:*'))
    for k in ks: r.delete(k)
    print(f'dedup cleared: {len(ks)}')
else:
    print('redis unavailable, skip dedup clear')
" 2>/dev/null || log "清空去重缓存失败（可忽略）"

# 3.5b) 在清空之后播种跨周/月历史告警，供趋势图按周/月聚合多桶自证
#       （必须位于 [3.5] 清空之后，否则会被 DELETE FROM alarm 移除）
log "[3.5b/6] 播种跨周期历史告警（多桶趋势自证）"
"$VENV/python" scripts/seed_history_alarms.py || log "seed_history_alarms 返回非零（可忽略）"

# ---- [3.6/6] 回归测试（媒体/附件/告警/实时/隔离）----
# 用 in-process TestClient 运行，不占用 8000 端口；依赖已启动的 PG/Redis/MinIO。
# 默认作为「护栏」阻断：测试失败即终止联调；设 SKIP_TESTS=1 可跳过。
if [ "${SKIP_TESTS:-0}" = "1" ]; then
  log "[3.6/6] 跳过回归测试（SKIP_TESTS=1）"
else
  log "[3.6/6] 运行回归测试 (pytest)"
  if CAPTCHA_ENABLED=false "$VENV/pytest" -q -p no:logging -o log_cli=false \
        tests/test_media.py tests/test_attachments.py \
        tests/test_realtime.py tests/test_dashboard_scope.py \
        tests/test_job_alarm.py tests/test_alarm_report.py \
        tests/test_snapshot_preview.py tests/test_metrics.py \
        tests/test_crud_service.py > /tmp/railmonitor_pytest.log 2>&1; then
    ok "回归测试通过（详情 /tmp/railmonitor_pytest.log）"
  else
    err "回归测试失败，摘要如下（完整见 /tmp/railmonitor_pytest.log）："
    grep -E "FAILED|ERROR|passed|failed" /tmp/railmonitor_pytest.log | tail -15
    exit 1
  fi
fi

# ---- [3.7/6] 前端门禁（依赖 → 构建 → Vitest 单测）----
# 纯前端校验，不依赖后端/数据库；与 [3.6] 后端 pytest 同组作为联调护栏。
# 任一环节失败即终止联调；设 SKIP_FE=1 可跳过（如仅调试后端、或 CI 中单独跑前端）。
if [ "${SKIP_FE:-0}" = "1" ]; then
  log "[3.7/6] 跳过前端门禁（SKIP_FE=1）"
else
  # 定位 npm：优先 PATH，回退到与 node 同目录（受管/系统 node 皆可）
  NPM_BIN="$(command -v npm 2>/dev/null)"
  if [ -z "$NPM_BIN" ]; then
    NODE_BIN="$(command -v node 2>/dev/null)"
    if [ -n "$NODE_BIN" ]; then
      CAND="${NODE_BIN%/*}/npm"
      [ -x "$CAND" ] && NPM_BIN="$CAND"
    fi
  fi
  if [ -z "$NPM_BIN" ]; then
    err "未找到 npm，无法执行前端门禁；请先在 PATH 中加入 node/npm，或设 SKIP_FE=1 跳过"
    exit 1
  fi
  log "[3.7/6] 前端门禁：依赖检查 → 构建 → Vitest 单测"
  WEB_DIR="$ROOT/web"
  if [ ! -d "$WEB_DIR/node_modules" ]; then
    log "  web/node_modules 缺失，执行 npm install"
    if (cd "$WEB_DIR" && "$NPM_BIN" install) > /tmp/railmonitor_fe_install.log 2>&1; then
      ok "前端依赖安装完成"
    else
      err "前端依赖安装失败（/tmp/railmonitor_fe_install.log）"; exit 1
    fi
  fi
  # 构建（vite build，校验打包/导入链路）；SKIP_FE_BUILD=1 时跳过以加速纯单测回归
  if [ "${SKIP_FE_BUILD:-0}" = "1" ]; then
    log "  跳过前端构建（SKIP_FE_BUILD=1），仅跑 Vitest 单测"
  else
    log "  构建前端 (npm run build)"
    if (cd "$WEB_DIR" && "$NPM_BIN" run build) > /tmp/railmonitor_fe_build.log 2>&1; then
      ok "前端构建通过（/tmp/railmonitor_fe_build.log）"
    else
      err "前端构建失败，摘要如下（完整见 /tmp/railmonitor_fe_build.log）："
      tail -20 /tmp/railmonitor_fe_build.log
      exit 1
    fi
  fi
  # Vitest 单测（核心门禁）
  log "  运行 Vitest 单测 (npm run test)"
  if (cd "$WEB_DIR" && "$NPM_BIN" run test) > /tmp/railmonitor_fe_test.log 2>&1; then
    ok "前端单测通过（/tmp/railmonitor_fe_test.log）"
    grep -E "Test Files|Tests " /tmp/railmonitor_fe_test.log | tail -5 | sed 's/^/    /'
  else
    err "前端单测失败，摘要如下（完整见 /tmp/railmonitor_fe_test.log）："
    tail -25 /tmp/railmonitor_fe_test.log
    exit 1
  fi
fi

# ---- [4/6] 后端 ----
# 端口冲突检测：绝不自动终止占用端口的外部进程（如 PyCharm 后端），
# 冲突时友好报错退出，提示用户释放或改用 --port。
if port_in_use; then
  err "端口 $PORT 已被其他进程占用（如 PyCharm 后端）。门禁不自动终止外部进程。"
  err "请先释放该端口，或改用其他端口： bash $0 --skip-services --port 8011"
  exit 1
fi
log "[4/6] 启动后端 (uvicorn :$PORT, 演示环境关闭登录验证码)"
CAPTCHA_ENABLED=false "$VENV/uvicorn" app.main:app --host 0.0.0.0 --port "$PORT" > /tmp/railmonitor_app.log 2>&1 &
APP_PID=$!
for _ in $(seq 1 30); do
  curl -sf http://127.0.0.1:"$PORT"/health >/dev/null 2>&1 && break
  sleep 1
done
if ! curl -sf http://127.0.0.1:"$PORT"/health >/dev/null 2>&1; then
  err "后端未就绪，日志如下："; tail -30 /tmp/railmonitor_app.log
  kill "$APP_PID" 2>/dev/null; exit 1
fi
ok "后端就绪 (pid=$APP_PID, port=$PORT)"

# ---- [5/6] 设备模拟器 ----
log "[5/6] 启动设备模拟器（持续上报 定位/大机/列车）"
"$VENV/python" scripts/device_simulator.py > /tmp/railmonitor_sim.log 2>&1 &
SIM_PID=$!
ok "模拟器已启动 (pid=$SIM_PID)"

# ---- [6/6] 等待并验证 ----
log "[6/6] 等待模拟器上报与规则判定 (10s)..."
sleep 10

echo ""
echo "=================================================="
echo -e "${c_green}联调已启动${c_reset}"
echo "  后端 API : http://127.0.0.1:$PORT/docs"
echo "  模拟器PID: $SIM_PID    后端PID: $APP_PID"
echo "  前端     : 另开终端 → cd web && npm run dev (默认 http://127.0.0.1:5173)"
echo "--------------------------------------------------"

TOKEN=$(curl -sf -X POST http://127.0.0.1:$PORT/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"Admin@123456"}' \
  | "$VENV/python" -c 'import sys,json;d=json.load(sys.stdin);print(d.get("data",{}).get("access_token",""))' 2>/dev/null)

if [ -n "$TOKEN" ]; then
  ok "已获取 admin token（前12位）: ${TOKEN:0:12}..."
  echo ""
  echo "  [实时位置] /api/v1/realtime/locations :"
  curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:$PORT/api/v1/realtime/locations \
    | "$VENV/python" -c 'import sys,json
d=json.load(sys.stdin)
data=d.get("data") or {}
items=data.get("items") if isinstance(data,dict) else data
items=items or []
print(f"    共 {len(items)} 条设备坐标；示例: {items[0] if items else None}")' 2>/dev/null
  echo "  [告警列表] /api/v1/alarms :"
  curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/api/v1/alarms?page=1&page_size=5" \
    | "$VENV/python" -c 'import sys,json
from collections import Counter
d=json.load(sys.stdin)
data=d.get("data") or {}
items=data.get("items") if isinstance(data,dict) else data
items=items or []
c=Counter(i.get("alarm_type") for i in items)
linked=sum(1 for i in items if i.get("work_plan_id"))
print(f"    本页 {len(items)} 条；类型分布: {dict(c)}")
print(f"    规则引擎 v2 溯源：{linked}/{len(items)} 条告警带 work_plan_id")' 2>/dev/null
  echo "  [轨迹回放] /api/v1/realtime/trajectory?device_no=LOC-001 :"
  curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/api/v1/realtime/trajectory?device_no=LOC-001&start=2026-01-01T00:00:00&end=2030-01-01T00:00:00" \
    | "$VENV/python" -c 'import sys,json
d=json.load(sys.stdin)
data=d.get("data") or {}
items=data.get("items") if isinstance(data,dict) else data
items=items or []
print(f"    共 {len(items)} 个轨迹点；首点: {items[0] if items else None}")' 2>/dev/null
  echo "  [告警报表] /api/v1/alarms/report :"
  curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/api/v1/alarms/report" \
    | "$VENV/python" -c 'import sys,json
d=json.load(sys.stdin)
data=d.get("data") or {}
s=data.get("summary") or {}
print("    总数 %s / 已处置 %s / 待处理 %s / 处置率 %s%%" % (s.get("total"), s.get("handled"), s.get("pending"), s.get("handle_rate")))
bt=", ".join("%s:%s" % (x.get("label") or x.get("key"), x.get("count")) for x in (s.get("by_type") or []))
bl=", ".join("%s:%s" % (x.get("key"), x.get("count")) for x in (s.get("by_level") or []))
print("    按类型: %s" % bt)
print("    按级别: %s" % bl)
print("    预览明细 %s 条；筛选描述: %s" % (data.get("preview_count"), data.get("filters_desc")))' 2>/dev/null
  echo "  [导出 Excel/PDF] /api/v1/alarms/export :"
  EX_HDR=$(curl -s -D - -o /dev/null -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/api/v1/alarms/export?fmt=excel" | "$VENV/python" -c 'import sys
for l in sys.stdin:
    if l.lower().startswith("content-type"): print(l.strip())' 2>/dev/null)
  PDF_MAGIC=$(curl -s -H "Authorization: Bearer $TOKEN" "http://127.0.0.1:$PORT/api/v1/alarms/export?fmt=pdf" | head -c 4)
  [ -n "$EX_HDR" ] && echo "    Excel Content-Type: $EX_HDR"
  [ "$PDF_MAGIC" = "%PDF" ] && ok "PDF 导出校验通过 (%PDF 头)" || err "PDF 导出校验失败 (magic=$PDF_MAGIC)"

  # [仪表盘周期联动] /api/v1/dashboard/stats 的 granularity/start/end 联动：
  # alarms_window 必须等于 /api/v1/alarms/report 同窗口 by_period 之和（同分桶口径）。
  echo "  [仪表盘周期联动] /api/v1/dashboard/stats :"
  DASH_OK=$(curl -s -H "Authorization: Bearer $TOKEN" \
    "http://127.0.0.1:$PORT/api/v1/dashboard/stats?granularity=month&start=2026-05-01T00:00:00&end=2026-07-31T23:59:59" \
    | "$VENV/python" -c '
import sys, json
d = json.load(sys.stdin)["data"]
c = d.get("counts") or {}
buckets = {p["period"]: p["count"] for p in (d.get("alarm_trend_period") or [])}
window = c.get("alarms_window")
cur = d.get("current_period")
cur_cnt = c.get("alarms_current_period")
bucket_sum = sum(buckets.values())
match_window = (window == bucket_sum)
match_cur = (cur_cnt == buckets.get(cur, 0))
print(f"window={window} bucket_sum={bucket_sum} MATCH={match_window} | current_period={cur} current={cur_cnt} bucket={buckets.get(cur,0)} MATCH={match_cur}")
sys.exit(0 if (match_window and match_cur) else 1)' 2>/dev/null)
  [ "$?" = "0" ] && ok "仪表盘周期联动自洽 (window==Σ桶 & 当前周期命中)" || err "仪表盘周期联动自洽失败: $DASH_OK"

  # [跨周期历史快照] /api/v1/alarms/export?snapshot=true 应返回多 sheet（概览+明细合并+周期 sheet）
  echo "  [历史快照导出] /api/v1/alarms/export?snapshot=true :"
  SNAP_HDR=$(curl -s -D - -o /dev/null -H "Authorization: Bearer $TOKEN" \
    --data-urlencode "granularity=month" --data-urlencode "snapshot=true" \
    --data-urlencode "start=2026-05-01T00:00:00" --data-urlencode "end=2026-07-31T23:59:59" \
    -G "http://127.0.0.1:$PORT/api/v1/alarms/export?fmt=excel" \
    | "$VENV/python" -c 'import sys
for l in sys.stdin:
    if l.lower().startswith("content-type"): print(l.strip())' 2>/dev/null)
  [ -n "$SNAP_HDR" ] && echo "    快照 Excel Content-Type: $SNAP_HDR"
  SNAP_SHEETS=$(curl -s -H "Authorization: Bearer $TOKEN" \
    --data-urlencode "granularity=month" --data-urlencode "snapshot=true" \
    --data-urlencode "start=2026-05-01T00:00:00" --data-urlencode "end=2026-07-31T23:59:59" \
    -G "http://127.0.0.1:$PORT/api/v1/alarms/export?fmt=excel" \
    | "$VENV/python" -c 'import sys, io
from openpyxl import load_workbook
data = sys.stdin.buffer.read()
wb = load_workbook(io.BytesIO(data))
names = wb.sheetnames
period_sheets = [n for n in names if n not in ("概览","明细合并")]
merged_rows = (wb["明细合并"].max_row - 1) if "明细合并" in names else 0
print("sheets=%d period_sheets=%d merged_rows=%d has_overview=%s" % (len(names), len(period_sheets), merged_rows, "概览" in names))
sys.exit(0 if (len(period_sheets) >= 1 and merged_rows > 0 and "概览" in names) else 1)' 2>/dev/null)
  [ "$?" = "0" ] && ok "历史快照多表导出通过 ($(echo $SNAP_SHEETS))" || err "历史快照多表导出失败"

  # [快照预览↔导出一致性] 预览 JSON 与导出的 Excel 必须逐桶一致（同源）。
  # 校验：预览 summary.total == 导出明细合并行数；预览各周期 total == 对应周期 sheet 行数；
  #        预览 project_summary 合计 == 导出总数。
  echo "  [快照预览↔导出一致性] /api/v1/alarms/snapshot/preview vs export :"
  PREVIEW_SNAP=$(curl -s -H "Authorization: Bearer $TOKEN" \
    --data-urlencode "granularity=month" --data-urlencode "snapshot=true" \
    --data-urlencode "start=2026-05-01T00:00:00" --data-urlencode "end=2026-07-31T23:59:59" \
    -G "http://127.0.0.1:$PORT/api/v1/alarms/snapshot/preview" \
    | "$VENV/python" -c 'import sys, json
d = json.load(sys.stdin)
assert d.get("code") == 0, d
p = d["data"]
print(json.dumps({
    "total": p["summary"]["total"],
    "periods": {x["period"]: x["total"] for x in p["periods"]},
    "proj_sum": sum(x["count"] for x in p["project_summary"]),
}, ensure_ascii=False))' 2>/dev/null)

  EXPORT_SNAP=$(curl -s -H "Authorization: Bearer $TOKEN" \
    --data-urlencode "granularity=month" --data-urlencode "snapshot=true" \
    --data-urlencode "start=2026-05-01T00:00:00" --data-urlencode "end=2026-07-31T23:59:59" \
    -G "http://127.0.0.1:$PORT/api/v1/alarms/export?fmt=excel" \
    | "$VENV/python" -c 'import sys, io, json
from openpyxl import load_workbook
data = sys.stdin.buffer.read()
wb = load_workbook(io.BytesIO(data))
names = wb.sheetnames
merged_rows = (wb["明细合并"].max_row - 1) if "明细合并" in names else 0
period_sheets = [n for n in names if n not in ("概览","明细合并","项目汇总") and not n.startswith("项目-")]
period_totals = {}
for pk in period_sheets:
    ws = wb[pk]
    cnt = 0
    for ri in range(2, ws.max_row + 1):
        if ws.cell(row=ri, column=2).value:
            cnt += 1
    period_totals[pk] = cnt
print(json.dumps({"total": merged_rows, "periods": period_totals}, ensure_ascii=False))' 2>/dev/null)

  if [ -n "$PREVIEW_SNAP" ] && [ -n "$EXPORT_SNAP" ]; then
    # 注意：两个 JSON 作为 argv 传入（不要 pipe 到 stdin，否则 sys.argv 为空）
    MATCH=$("$VENV/python" -c '
import sys, json
pv = json.loads(sys.argv[1]); ex = json.loads(sys.argv[2])
ok = (pv["total"] == ex["total"]) and (pv["periods"] == ex["periods"]) and (pv["proj_sum"] == ex["total"])
print("preview_total=%s export_total=%s periods_match=%s proj_sum_match=%s" % (
    pv["total"], ex["total"], pv["periods"] == ex["periods"], pv["proj_sum"] == ex["total"]))
sys.exit(0 if ok else 1)' "$PREVIEW_SNAP" "$EXPORT_SNAP" 2>/dev/null)
    [ "$?" = "0" ] && ok "快照预览与导出逐桶一致 ($MATCH)" || err "快照预览与导出不一致: $MATCH"
  else
    err "快照预览/导出一致性检查未能获取数据"
  fi
else
  err "未能自动获取 token（登录失败）。请检查后端日志 /tmp/railmonitor_app.log"
fi
echo "  模拟器最近上报:"
grep "上报完成" /tmp/railmonitor_sim.log 2>/dev/null | tail -3 | sed 's/^/    /'
echo "=================================================="
echo "停止: kill $APP_PID $SIM_PID ; bash scripts/native-services.sh stop"
