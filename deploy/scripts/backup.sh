#!/usr/bin/env bash
# =============================================================
# 涉铁工程智能监控平台 —— 备份脚本（PostgreSQL + MinIO）
# 作用：
#   - PostgreSQL：每日一个自定义格式 dump（-Fc），含保留策略（默认保留 7 份）
#   - MinIO：若安装 mc，则把业务桶镜像到本地备份目录（增量，含历史版本）
# 用法：
#   sudo bash deploy/scripts/backup.sh
# 可覆盖的环境变量：BACKUP_DIR / RETAIN_DAYS / POSTGRES_* / MINIO_*
# 依赖：postgresql-client（pg_dump）、minio-client（mc，可选）
# 说明：本脚本供 systemd timer（deploy/rail-monitor-backup.timer）每日调用；
#       恢复见 deploy/scripts/restore.sh。
# =============================================================
set -euo pipefail

# ---- 读取部署 .env（若存在），获取数据库/对象存储凭据 ----
ENV_FILE="${ENV_FILE:-/opt/rail_monitor/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

BACKUP_DIR="${BACKUP_DIR:-/var/backups/rail_monitor}"
RETAIN_DAYS="${RETAIN_DAYS:-7}"

# PostgreSQL 连接（优先 .env 变量，回退 config.py 默认值）
PGHOST="${POSTGRES_HOST:-127.0.0.1}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-dev}"
PGDATABASE="${POSTGRES_DB:-rail_monitor}"
export PGPASSWORD="${POSTGRES_PASSWORD:-dev123}"

# MinIO（可选）
MINIO_HOST="${MINIO_ENDPOINT%%:*}"
MINIO_PORT="${MINIO_ENDPOINT##*:}"
MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minioadmin}"
MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin}"
MINIO_BUCKET="${MINIO_BUCKET:-rail-monitor}"

TS="$(date +%Y%m%d-%H%M%S)"
PG_DIR="$BACKUP_DIR/postgres"
MINIO_DIR="$BACKUP_DIR/minio"

log() { echo "[$(date '+%F %T')] $*"; }

command -v pg_dump >/dev/null 2>&1 || { echo "✗ 未找到 pg_dump（请安装 postgresql-client）" >&2; exit 1; }

mkdir -p "$PG_DIR"
log "开始备份 PostgreSQL -> $PG_DATABASE"

# 自定义格式 dump（支持并行恢复与选择性还原）
pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
  -Fc -f "$PG_DIR/$PGDATABASE-$TS.dump" \
  && log "✓ PostgreSQL dump 完成: $PG_DIR/$PGDATABASE-$TS.dump" \
  || { echo "✗ pg_dump 失败" >&2; exit 1; }

# 保留策略：删除早于 RETAIN_DAYS 天的 dump
find "$PG_DIR" -name "$PGDATABASE-*.dump" -mtime "+$RETAIN_DAYS" -delete 2>/dev/null || true
log "保留最近 $RETAIN_DAYS 天（当前 $(find "$PG_DIR" -name "$PGDATABASE-*.dump" | wc -l | tr -d ' ') 份）"

# MinIO 镜像（可选）
if command -v mc >/dev/null 2>&1; then
  log "开始备份 MinIO 桶 -> $MINIO_BUCKET"
  mkdir -p "$MINIO_DIR"
  ALIAS="rmbackup-$TS"
  if mc alias set "$ALIAS" "http://$MINIO_HOST:$MINIO_PORT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null 2>&1; then
    mc mirror --overwrite "$ALIAS/$MINIO_BUCKET" "$MINIO_DIR/$MINIO_BUCKET-$TS" >/dev/null 2>&1 \
      && log "✓ MinIO 桶镜像完成: $MINIO_DIR/$MINIO_BUCKET-$TS" \
      || log "⚠ MinIO 镜像失败（继续，不影响 PG 备份）"
    mc alias rm "$ALIAS" >/dev/null 2>&1 || true
  else
    log "⚠ 无法连接 MinIO，跳过对象存储备份"
  fi
else
  log "ℹ 未安装 mc（minio-client），跳过 MinIO 备份"
fi

log "备份完成。备份目录: $BACKUP_DIR"
