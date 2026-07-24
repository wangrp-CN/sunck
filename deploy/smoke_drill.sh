#!/usr/bin/env bash
# =============================================================================
# 目标机 / 开发机 全栈真起冒烟演练
# -----------------------------------------------------------------------------
# 用途：在「同一网络命名空间」内拉起后端 + (可选) Nginx，走生产态验证码登录拿
#       JWT，端到端探活关键端点，验证部署闭环可用。最后清理进程。
#
# 重要：所有「起服务 + 探活 + 清理」必须在同一次进程/同一调用内完成，
#       否则跨进程网络隔离会使后续探测 ConnectionRefused。
#
# 适用：macOS 开发机或 Linux 部署机（systemd 之外的手动验证手段）。
#       生产环境请用 systemd 单元 + deploy/nginx.conf（80/443），本脚本的
#       Nginx 段仅用于本地 8088 端口反代验证。
#
# 用法：
#   bash deploy/smoke_drill.sh                  # 默认本机配置
#   APP_DIR=/opt/rail_monitor REDIS_PASSWORD=xxx bash deploy/smoke_drill.sh
#   SKIP_NGINX=1 bash deploy/smoke_drill.sh     # 只验证后端 + 登录 + 端点
# =============================================================================
set -u
APP_DIR="${APP_DIR:-/Users/wangpeng/PycharmProjects/RimpCode/rail_monitor}"
REDIS_PASSWORD="${REDIS_PASSWORD:-dev_local_redis}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-Admin@123456}"
API_PORT="${API_PORT:-8000}"
NGINX_LISTEN="${NGINX_LISTEN:-8088}"
REDIS_CLI="${REDIS_CLI:-redis-cli}"
NGINX_BIN="${NGINX_BIN:-/opt/homebrew/bin/nginx}"
SKIP_NGINX="${SKIP_NGINX:-0}"

cd "$APP_DIR"

echo "#################### [0] 基础设施状态 ####################"
(pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1 && echo "PG(5432): ready") || echo "PG(5432): NOT ready"
("$REDIS_CLI" -h 127.0.0.1 -p 6379 -a "$REDIS_PASSWORD" ping 2>/dev/null | grep -q PONG && echo "Redis(6379): PONG") || echo "Redis(6379): down"
(pgrep -x mosquitto >/dev/null && echo "MQTT(mosquitto): running") || echo "MQTT(mosquitto): down"
(pgrep -x minio >/dev/null && echo "MinIO: running") || echo "MinIO: down"

echo
echo "#################### [1] 启动后端 uvicorn (.env 驱动, 验证码生产态开启) ####################"
nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" >/tmp/drill_uv.log 2>&1 &
UVPID=$!
OK=0
for i in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:$API_PORT/openapi.json" -o /dev/null 2>/dev/null; then echo "openapi.json 就绪 (${i}s)"; OK=1; break; fi
  sleep 1
done
[ "$OK" = "0" ] && { echo "FATAL: 后端未就绪"; tail -n 20 /tmp/drill_uv.log; kill $UVPID 2>/dev/null; exit 1; }

echo
echo "#################### [2] 真实登录流 (生产态验证码, 答案取自 Redis) ####################"
CAP=$(curl -s "http://127.0.0.1:$API_PORT/api/v1/auth/captcha")
KEY=$(printf '%s' "$CAP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('data',{}).get('captcha_key',''))" 2>/dev/null)
ANS=$("$REDIS_CLI" -h 127.0.0.1 -p 6379 -a "$REDIS_PASSWORD" get "captcha:$KEY" 2>/dev/null | tr -d '\r\n')
echo "captcha_key=$KEY  answer=$ANS"
LOGIN=$(curl -s -X POST "http://127.0.0.1:$API_PORT/api/v1/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\",\"captcha\":\"$ANS\",\"captcha_key\":\"$KEY\"}")
TOKEN=$(printf '%s' "$LOGIN" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('data',{}).get('access_token','') if isinstance(d.get('data'),dict) else '')" 2>/dev/null)
LCODE=$(printf '%s' "$LOGIN" | python3 -c "import sys,json;print(json.load(sys.stdin).get('code'))" 2>/dev/null)
echo "login code=$LCODE  token_len=${#TOKEN}"
if [ -z "$TOKEN" ]; then
  echo "FATAL: 登录失败 -> $(printf '%s' "$LOGIN" | head -c 200)"
  kill $UVPID 2>/dev/null; exit 1
fi

echo
echo "#################### [3] 直连后端 探活关键端点 ####################"
for ep in "devices/health?hours=24" "dashboard/project-compare?days=7" "inspections/stats" "videos/channels" "dicts" "jobs?is_template=false&size=3"; do
  code=$(curl -s -o /tmp/d.json -w "%{http_code}" "http://127.0.0.1:$API_PORT/api/v1/$ep" -H "Authorization: Bearer $TOKEN")
  echo "  GET /api/v1/$ep -> $code"
done

echo
echo "#################### [4] 写操作冒烟 + 清理 (数据字典) ####################"
C=$(curl -s -o /tmp/d2.json -w "%{http_code}" -X POST "http://127.0.0.1:$API_PORT/api/v1/dicts" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"code":"DRILL_TEST","name":"演练测试字典","items":[{"label":"项一","value":"v1"}]}')
echo "  POST /api/v1/dicts -> $C"
curl -s -X DELETE "http://127.0.0.1:$API_PORT/api/v1/dicts/DRILL_TEST" -H "Authorization: Bearer $TOKEN" -o /dev/null -w "  DELETE /api/v1/dicts/DRILL_TEST -> %{http_code}\n"

if [ "$SKIP_NGINX" != "1" ]; then
  echo
  echo "#################### [5] 起 Nginx 反代 ($NGINX_LISTEN 高端口, 透传 /api 与 /ws) ####################"
  FE_ROOT="$APP_DIR/web/dist"
  [ -d "$FE_ROOT" ] || FE_ROOT=/tmp/fe-dist
  MIME=/opt/homebrew/etc/nginx/mime.types; [ -f "$MIME" ] || MIME=/usr/local/etc/nginx/mime.types; [ -f "$MIME" ] || MIME=""
  cat > /tmp/drill_nginx.conf <<EOF
events { worker_connections 1024; }
http {
  $([ -n "$MIME" ] && echo "include $MIME;")
  default_type application/octet-stream;
  sendfile on;
  server {
    listen $NGINX_LISTEN;
    server_name _;
    root $FE_ROOT;
    index index.html;
    location /api/ { proxy_pass http://127.0.0.1:$API_PORT; proxy_set_header Host \$host; proxy_set_header X-Real-IP \$remote_addr; }
    location /ws/  { proxy_pass http://127.0.0.1:$API_PORT; proxy_http_version 1.1; proxy_set_header Upgrade \$http_upgrade; proxy_set_header Connection "upgrade"; proxy_read_timeout 3600s; }
    location / { try_files \$uri \$uri/ /index.html; }
  }
}
EOF
  "$NGINX_BIN" -t -c /tmp/drill_nginx.conf -p /tmp >/tmp/drill_ng_test.log 2>&1 && echo "nginx -t: $(tail -n1 /tmp/drill_ng_test.log)"
  "$NGINX_BIN" -c /tmp/drill_nginx.conf -p /tmp >/tmp/drill_ng.log 2>&1 &
  sleep 2
  echo "---- 经 Nginx(:$NGINX_LISTEN) 探活 ----"
  for ep in "dicts" "devices/health?hours=24" "dashboard/project-compare?days=7"; do
    code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$NGINX_LISTEN/api/v1/$ep" -H "Authorization: Bearer $TOKEN")
    echo "  GET :$NGINX_LISTEN/api/v1/$ep -> $code"
  done
  echo "  GET :$NGINX_LISTEN/ (SPA 首页) -> $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$NGINX_LISTEN/)"
  echo "  GET :$NGINX_LISTEN/some/spa/route (history 回退) -> $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$NGINX_LISTEN/some/spa/route)"
fi

echo
echo "#################### [6] 清理 ####################"
"$NGINX_BIN" -c /tmp/drill_nginx.conf -p /tmp -s stop 2>/dev/null
pkill -f "nginx -c /tmp/drill_nginx.conf" 2>/dev/null
kill $UVPID 2>/dev/null
sleep 1
echo "#################### 演练完成 (exit 0) ####################"
