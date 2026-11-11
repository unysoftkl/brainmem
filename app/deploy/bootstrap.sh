#!/usr/bin/env bash
# 阶段6 一键启动（Linux/macOS/WSL，需已安装 Docker）
# 用法： bash deploy/bootstrap.sh
set -euo pipefail
cd "$(dirname "$0")/.."   # 切到 phase1/

command -v docker >/dev/null || { echo "未找到 docker，请先安装 Docker"; exit 1; }
echo "[1/4] 启动 PostgreSQL16 + pgvector..."
docker compose -f deploy/docker-compose.yml up -d db
echo "[2/4] 等待数据库就绪..."
for i in $(seq 1 40); do
  if docker exec brainmem-db pg_isready -U brainmem -d brainmem >/dev/null 2>&1; then break; fi
  sleep 3
done
export BRAINMEM_PG_DSN="postgresql://brainmem:brainmem@127.0.0.1:5432/brainmem"
echo "[3/4] 建 schema..."
python -c "import sys;sys.path.insert(0,'src');from brainmem.storage.postgres.db import PostgresStorage as P;p=P();p.init_schema();print('schema ready');p.close()"
echo "[4/4] 完成。连接串: $BRAINMEM_PG_DSN"
echo "下一步: python deploy/migrate_to_pg.py --sqlite <your.db>"
