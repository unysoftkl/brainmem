# 阶段 6 · PostgreSQL 生产部署手册

本目录把"阶段 6 生产就绪"的三项验收（**1000 万节点实跑 / P95<100ms / RTO<1h**）变成可一键执行的流程。本机无 PostgreSQL 服务，以下命令需在**装有 Docker** 或 **PostgreSQL 16 + pgvector** 的机器上执行。

## 0. 前置

- 方式 A（推荐，零安装）：Docker + Docker Compose
- 方式 B（裸机）：PostgreSQL 16+，并 `CREATE EXTENSION vector;`（pgvector 0.7+）
- Python 3.11+，`pip install -e ".[dev]"`

## 1. 起库

### A. Docker（一条命令，含 pgvector）
```bash
cd phase1
docker compose -f deploy/docker-compose.yml up -d db
# 应用也容器化（可选）：
docker compose -f deploy/docker-compose.yml --profile app up -d
```
连接串：`postgresql://brainmem:brainmem@127.0.0.1:5432/brainmem`

### B. 裸机
```bash
sudo -u postgres psql -c "CREATE USER brainmem WITH PASSWORD 'brainmem';"
sudo -u postgres psql -c "CREATE DATABASE brainmem OWNER brainmem;"
sudo -u postgres psql -d brainmem -c "CREATE EXTENSION vector;"   # 需先装 pgvector
```

```bash
export BRAINMEM_PG_DSN=postgresql://brainmem:brainmem@127.0.0.1:5432/brainmem
```

## 2. 建 schema（幂等）

```bash
python -c "from brainmem.storage.postgres.db import PostgresStorage as P; P().init_schema(); print('schema ok')"
```

## 3. 迁移 SQLite → PG（含对账，必须 0 误差）

```bash
# 先在 SQLite 上准备好数据（或用阶段1-5 产生的 brainmem.db）
python deploy/migrate_to_pg.py --sqlite /path/to/brainmem.db --tenant default --dump export.json
# 期望输出：MIGRATION OK (0 mismatch)，退出码 0
```

## 4. 契约测试（SQLite / PG 双实现）

```bash
python -m pytest tests/ -q            # 全量
# 若有专门的 PG 契约测试（需 PG），按 test_postgres_* 运行
```

## 5. 压测（1000 万节点 / P95<100ms）

```bash
# 先小规模验证流程（1 万，秒级）：
python deploy/bench_pg.py --nodes 10000 --queries 200
# 全量（1000 万，视机器数分钟~数十分钟）：
python deploy/bench_pg.py --nodes 10000000 --queries 1000
# 关注输出 query_p95_ms < 100 且 meets_p95_100ms=true
```

> 提示：千万级首次写入用 `--batch 5000`；如仍慢，可先 `COPY` 到临时表再 `INSERT ... SELECT`。HNSW 索引在大量插入后会变慢，压测前可 `REINDEX INDEX idx_node_emb_hnsw;`。

## 6. 备份 / 恢复演练（RTO<1h）

```bash
export PGHOST=127.0.0.1 PGPORT=5432 PGUSER=brainmem PGPASSWORD=brainmem PGDATABASE=brainmem
bash deploy/backup_restore.sh backup                       # 产出 brainmem_*.dump
bash deploy/backup_restore.sh restore brainmem_xxx.dump    # 打印 RTO 秒数
# 验收：RTO < 3600s，且恢复后 SELECT count(*) 与源一致
```

生产建议：`pg_basebackup` + WAL 归档做 PITR，备份到对象存储（S3/MinIO），定期演练。

## 7. 监控

`brainmem.services.monitoring.metrics(engine)` 返回权重分位/状态分布/规模/合并质量；接 Prometheus 时可包一个 `/metrics` 端点输出。

## 8. 验收清单

- [ ] `init_schema` 成功（六表 + 4 分区 + HNSW）
- [ ] `migrate_to_pg.py` 退出码 0、`mismatched=0`
- [ ] `bench_pg.py --nodes 10000000` 的 `query_p95_ms < 100`
- [ ] `backup_restore.sh restore` 的 RTO < 3600s
- [ ] 所有 SQL 带 `tenant_id` 过滤（分区裁剪），`memory_stats` 按租户返回
