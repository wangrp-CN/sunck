#!/usr/bin/env bash
# =============================================================
# 涉铁工程智能监控平台 —— 恢复脚本（PostgreSQL + MinIO）
# 作用：从 backup.sh 产出的备份集中恢复 PostgreSQL 与 MinIO。
# 用法：
#   sudo bash deploy/scripts/restore.sh <备份标识> [目标库名]
#   sudo bash deploy/scripts/restore.sh 20260724-093000 rail_monitor
# 备份标识：postgres 目录下的文件名去掉 .dump 后缀，如 20260724-093000；
#           或 MinIO 目录名去掉桶名前缀，如 rail-monitor-20260724-093000。
# 前置：
#   1) 恢复会覆盖目标库，请先确认已对当前生产库另存备份！
#   2) 建议先停止写入（停 rail-monitor-api），恢复完成后重启。
#   3) 依赖 pg_restore / mc。
# =============================================================
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "用法: sudo bash $0 <备份标识> [目标库名]" >&2
  echo "示例: sudo bash $0 20260724-093000 rail_monitor" >&2
  exit 2
fi

ENV_FILE="${ENV_FILE:-/opt/rail_monitor/.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a; source "$ENV_FILE"; set +a
fi

BACKUP_DIR="${BACKUP_DIR:-/var/backups/rail_monitor}"
TS="$1"
PGDATABASE="${2:-${POSTGRES_DB:-rail_monitor}}"
PGHOST="${POSTGRES_HOST:-127.0.0.1}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-dev}"
export PGPASSWORD="${POSTGRES_PASSWORD:-dev123}"
MINIO_HOST="${MINIO_ENDPOINT%%:*}"
MINIO_PORT="${MINIO_ENDPOINT##*:}"
MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minioadmin}"
MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minioadmin}"
MINIO_BUCKET="${MINIO_BUCKET:-rail-monitor}"

DUMP="$BACKUP_DIR/postgres/$PGDATABASE-$TS.dump"
if [[ ! -f "$DUMP" ]]; then
  echo "✗ 未找到 PG dump: $DUMP" >&2
  exit 1
fi

echo "⚠ 即将把 $DUMP 恢复到数据库 $PGDATABASE@$PGHOST:$PGPORT（会覆盖现有数据）"
read -r -p "确认继续? [yes/N] " ANS
if [[ "$ANS" != "yes" ]]; then
  echo "已取消。"; exit 0
fi

# 终止现有连接并重建目标库（确保干净恢复）
echo "==> 重建目标库 $PGDATABASE"
PGOPTIONS="-c statement_timeout=0" psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$PGDATABASE' AND pid<>pg_backend_pid();" >/dev/null 2>&1 || true
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -c "DROP DATABASE IF EXISTS \"$PGDATABASE\";" >/dev/null 2>&1
psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -c "CREATE DATABASE \"$PGDATABASE\";" >/dev/null 2>&1

echo "==> 恢复数据 (pg_restore)"
pg_restore -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" --no-owner --if-exists --clean "$DUMP" \
  && echo "✓ PostgreSQL 恢复完成" || { echo "✗ pg_restore 失败" >&2; exit 1; }

# MinIO 回灌（可选）：从对应时间戳的镜像目录反向 mirror
MINIO_SRC="$BACKUP_DIR/minio/$MINIO_BUCKET-$TS"
if [[ -d "$MINIO_SRC" ]] && command -v mc >/dev/null 2>&1; then
  echo "==> 回灌 MinIO 桶 $MINIO_BUCKET"
  ALIAS="rmrestore-$TS"
  if mc alias set "$ALIAS" "http://$MINIO_HOST:$MINIO_PORT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null 2>&1; then
    mc mirror --overwrite "$MINIO_SRC" "$ALIAS/$MINIO_BUCKET" >/dev/null 2>&1 \
      && echo "✓ MinIO 回灌完成" || echo "⚠ MinIO 回灌失败（请手动处理）"
    mc alias rm "$ALIAS" >/dev/null 2>&1 || true
  fi
else
  echo "ℹ 跳过 MinIO 回灌（无镜像目录或 mc 不可用）"
fi

echo "✅ 恢复完成。请重启后端：sudo systemctl restart rail-monitor-api"
