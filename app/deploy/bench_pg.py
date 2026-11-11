#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""PostgreSQL 实机压测（阶段6 验收：1000 万节点 / P95<100ms）。

用法：
  export BRAINMEM_PG_DSN=postgresql://brainmem:brainmem@127.0.0.1:5432/brainmem
  python deploy/bench_pg.py --nodes 1000000 --edges-per-node 10 --queries 500
说明：--nodes 可先小规模(10万)验证流程，再上 1000 万。批量 COPY/INSERT 提速。
输出 P50/P95/P99 检索延迟、写入吞吐、节点/边规模。
"""
import argparse
import json
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from brainmem.core.decay import BP  # noqa: E402
from brainmem.core.time import SystemClock  # noqa: E402
from brainmem.services.embedder import HashEmbedder  # noqa: E402
from brainmem.storage.postgres.db import PostgresStorage  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, default=1_000_000)
    ap.add_argument("--edges-per-node", type=int, default=10)
    ap.add_argument("--queries", type=int, default=500)
    ap.add_argument("--batch", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    dsn = os.environ.get("BRAINMEM_PG_DSN")
    if not dsn:
        print("ERROR: 需设置 BRAINMEM_PG_DSN", file=sys.stderr)
        return 2
    st = PostgresStorage(dsn)
    st.init_schema()
    emb = HashEmbedder()
    rnd = random.Random(args.seed)
    now = SystemClock().now_day()

    # 批量写入节点
    t0 = time.perf_counter()
    with st.transaction() as tx:
        for start in range(0, args.nodes, args.batch):
            for i in range(start, min(start + args.batch, args.nodes)):
                nid = f"n{i:012d}"
                vec = emb.encode(f"记{i}")
                tx._exec(
                    "INSERT INTO memory_node(id,tenant_id,label,label_norm,char_len,kind,"
                    "weight_bp,stability,peak_bp,state,fidelity,gist,fingerprint,salience,"
                    "born_at,last_touch_at,source_kind,embedding) VALUES "
                    "(%s,'default',%s,%s,3,'ATOM',%s,0,%s,'NORMAL',100,%s,%s,50,%s,%s,'HUMAN',%s::vector) "
                    "ON CONFLICT DO NOTHING",
                    (nid, f"记{i}"[:10], f"记{i}", 60000, 60000, f"记{i}", f"fp{i:012d}",
                     now, now, "[" + ",".join(f"{x:.6f}" for x in vec) + "]"),
                )
    write_s = time.perf_counter() - t0
    print(f"wrote {args.nodes} nodes in {write_s:.1f}s ({args.nodes/write_s:.0f}/s)")

    # 抽样查询延迟（向量召回 + 权重）
    lat = []
    for _ in range(args.queries):
        q = emb.encode(f"记{rnd.randint(0, args.nodes-1)}")
        t = time.perf_counter()
        st.vector_search("default", q, k=50)
        lat.append((time.perf_counter() - t) * 1000)
    lat.sort()
    p = lambda q: round(lat[min(len(lat)-1, int(q*len(lat)))], 3)
    out = {
        "nodes": args.nodes,
        "write_seconds": round(write_s, 1),
        "write_per_s": round(args.nodes / write_s, 1),
        "query_p50_ms": p(0.5),
        "query_p95_ms": p(0.95),
        "query_p99_ms": p(0.99),
        "meets_p95_100ms": p(0.95) < 100,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    st.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
