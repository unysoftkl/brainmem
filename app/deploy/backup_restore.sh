#!/usr/bin/env bash
# PostgreSQL 备份 / 恢复演练（阶段6 验收：RTO < 1 小时）
# 用法：
#   bash deploy/backup_restore.sh backup    # pg_dump 自定义格式 -> 文件 + 计时
#   bash deploy/backup_restore.sh restore <dumpfile>   # 恢复到新库并计时，打印 RTO
# 前置：PATH 有 pg_dump/pg_restore/psql；连接用 PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE
set -euo pipefail

MODE="${1:-backup}"
STAMP="$(date +%Y%m%d_%H%M%S)"
DB="${PGDATABASE:-brainmem}"

case "$MODE" in
  backup)
    OUT="${2:-brainmem_${STAMP}.dump}"
    echo "[backup] pg_dump -Fc $DB -> $OUT"
    START=$(date +%s)
    pg_dump -Fc -d "$DB" -f "$OUT"
    END=$(date +%s)
    echo "[backup] done in $((END-START))s, size=$(du -h "$OUT" | cut -f1)"
    ;;
  restore)
    DUMP="${2:?需要 dump 文件路径}"
    TARGET="${3:-brainmem_restore}"
    echo "[restore] 重建目标库 $TARGET 并从 $DUMP 恢复"
    START=$(date +%s)
    psql -d postgres -c "DROP DATABASE IF EXISTS $TARGET;"
    psql -d postgres -c "CREATE DATABASE $TARGET;"
    # 目标库需 pgvector 扩展（schema.sql 里已有 CREATE EXTENSION）
    pg_restore -d "$TARGET" --no-owner --no-privileges "$DUMP"
    psql -d "$TARGET" -c "SELECT count(*) AS nodes FROM memory_node;"
    END=$(date +%s)
    echo "[restore] RTO = $((END-START))s (目标 < 3600s)"
    ;;
  *)
    echo "usage: $0 backup|restore [file] [targetdb]"; exit 2;;
esac
