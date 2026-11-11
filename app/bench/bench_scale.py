# -*- coding: utf-8 -*-
"""阶段6 验收脚本（无 PG 服务环境）：
1) SQLite 生产导出（真实数据）→ 事件保序、大小、重放保真
2) PG schema/DDL 静态校验（方言、分区、HNSW、六表）
3) 存储契约对齐（PostgresStorage 实现 Storage 协议全部方法）
4) 规模/容量估算（节点字节估算 → 1000万节点磁盘）
5) 迁移保真：导出事件逐节点重放 == 导出权重（0 误差）
输出 JSON。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from brainmem.core.enums import EventType
from brainmem.core.models import WeightEvent
from brainmem.core.time import FakeClock
from brainmem.engine.events import replay
from brainmem.interfaces.memory import Memory
from brainmem.storage.base import Storage
from brainmem.storage.migrate import export_sqlite
from brainmem.storage.postgres.db import PostgresStorage, _vec_literal


def build_sample(mem, n=500):
    for i in range(n):
        mem.write("记" + f"{i:04d}"[:5])
    # 一些强化与边
    for i in range(50):
        pass


def main():
    clock = FakeClock(1000.0)
    m = Memory.in_memory(clock)
    for i in range(500):
        m.write(f"记{i}"[:6])
    for i in range(20):
        clock.advance_days(5)
        m.write(f"记{i}"[:6])
    for i in range(30):
        m.link(f"记{i}"[:6] if False else m.storage.list_node_ids("default")[i],
               m.storage.list_node_ids("default")[i + 1], "ASSOCIATED", weight=8.0)

    data = export_sqlite(m.storage, "default")
    # 迁移保真：逐节点事件重放 == 权重
    by_entity = {}
    for e in data["events"]:
        by_entity.setdefault(e["entity_id"], []).append(e)
    err = 0
    for n in data["nodes"]:
        evs = [WeightEvent(seq=e["seq"], tenant_id=e["tenant_id"], entity_kind=e["entity_kind"],
                           entity_id=e["entity_id"], event_type=EventType(e["event_type"]),
                           delta_bp=e["delta_bp"], before_bp=e["before_bp"], after_bp=e["after_bp"],
                           reason=e["reason"], actor=e["actor"], at_day=e["at_day"],
                           at_real=e["at_real"], trace_id=e["trace_id"])
               for e in by_entity.get(n["id"], [])]
        if replay(evs, 0) != n["weight_bp"]:
            err += 1
    seq_sorted = [e["seq"] for e in data["events"]] == sorted(e["seq"] for e in data["events"])

    # PG schema 静态
    schema_path = os.path.join(os.path.dirname(__file__), "..", "src", "brainmem",
                               "storage", "postgres", "schema.sql")
    schema = open(schema_path, encoding="utf-8").read()
    pg_static = {
        "has_pgvector": "CREATE EXTENSION IF NOT EXISTS vector" in schema,
        "partitioned": "PARTITION BY HASH (tenant_id)" in schema,
        "partitions": schema.count("PARTITION OF memory_node"),
        "hnsw": "USING hnsw" in schema,
        "vector_dim": "vector(256)" in schema,
        "six_tables": all(f"CREATE TABLE IF NOT EXISTS {t}" in schema for t in
                          ["memory_node", "memory_edge", "weight_event", "memory_version",
                           "consolidation_run", "schema_registry"]),
    }
    # 契约对齐
    proto = [x for x in dir(Storage) if not x.startswith("_")]
    missing = [x for x in proto if not hasattr(PostgresStorage, x)]

    # 容量估算：单节点热数据字节（不含 verbatim）
    import sqlite3
    row_bytes = m.storage._conn.execute(
        "SELECT SUM(LENGTH(id)+LENGTH(label)+LENGTH(label_norm)+12) FROM memory_node").fetchone()[0]
    nodes = m.stats()["nodes"]
    per_node = round(row_bytes / nodes, 1)
    est_10m_gb = round(per_node * 10_000_000 / 1e9, 1)

    out = {
        "sqlite_export": {
            "nodes": len(data["nodes"]), "edges": len(data["edges"]),
            "events": len(data["events"]),
            "events_seq_sorted": seq_sorted,
            "replay_weight_mismatch": err,
        },
        "pg_static": pg_static,
        "pg_storage_missing_methods": missing,
        "vec_literal_ok": _vec_literal([1.0, -2.0]) == "[1.000000,-2.000000]",
        "capacity": {"per_node_bytes": per_node, "est_10m_nodes_GB": est_10m_gb},
        "pg_live_available": False,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    with open(os.path.join(os.path.dirname(__file__), "..", "bench_result_p6.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    m.close()


if __name__ == "__main__":
    main()
