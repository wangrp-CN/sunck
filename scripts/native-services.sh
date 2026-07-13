#!/usr/bin/env bash
# 方案A：原生服务编排（PostgreSQL / Redis / Mosquitto / MinIO）
# 这是本项目在方案A下的标准化部署入口，不依赖 Docker。
# 用法：
#   ./scripts/native-services.sh start    启动全部原生服务
#   ./scripts/native-services.sh stop     停止全部原生服务
#   ./scripts/native-services.sh status   查看状态
set -euo pipefail

MINIO_PLIST="$HOME/Library/LaunchAgents/com.railmonitor.minio.plist"
MINIO_BIN="${MINIO_BIN:-/tmp/minio}"
MINIO_DATA="${MINIO_DATA:-/tmp/minio_data}"

start() {
  echo ">>> 启动 PostgreSQL / Redis / Mosquitto (brew)"
  brew services start postgresql@17
  brew services start redis
  brew services start mosquitto

  echo ">>> 启动 MinIO (launchd 守护)"
  if launchctl list | grep -q com.railmonitor.minio; then
    echo "    minio 已在运行"
  else
    launchctl bootstrap "gui/$(id -u)" "$MINIO_PLIST" 2>/dev/null || launchctl load "$MINIO_PLIST"
  fi

  echo ">>> 等待端口就绪..."
  for p in 5432 6379 1883 9000; do
    for _ in $(seq 1 30); do
      lsof -nP -iTCP:"$p" -sTCP:LISTEN -t >/dev/null 2>&1 && break
      sleep 1
    done
    if lsof -nP -iTCP:"$p" -sTCP:LISTEN -t >/dev/null 2>&1; then
      echo "    $p ✅"
    else
      echo "    $p ❌ 未监听"
    fi
  done
}

stop() {
  echo ">>> 停止原生服务"
  brew services stop postgresql@17 || true
  brew services stop redis || true
  brew services stop mosquitto || true
  launchctl bootout "gui/$(id -u)" "$MINIO_PLIST" 2>/dev/null || true
  echo ">>> 已停止"
}

status() {
  echo "--- brew 服务 ---"
  brew services list | grep -E 'postgresql|redis|mosquitto' || true
  if launchctl list | grep -q com.railmonitor.minio; then
    echo "minio          started"
  else
    echo "minio          stopped"
  fi
}

case "${1:-}" in
  start)  start ;;
  stop)   stop ;;
  status) status ;;
  *) echo "用法: $0 {start|stop|status}"; exit 1 ;;
esac
