"""监控指标（阶段6）：权重分布 / 状态分布 / 规模 / 合并质量。

供 Prometheus 抓取或人工巡检；不引入额外依赖，返回纯 dict。
"""
from __future__ import annotations

import statistics

from brainmem.core.decay import BP, decay_bp


def metrics(engine) -> dict:
    tenant = engine.tenant
    now = engine.clock.now_day()
    nodes = engine.storage.list_nodes(tenant)
    weights = [decay_bp(n.weight_bp, n.stability, now - n.last_touch_at, engine.p) for n in nodes]
    dist = engine.storage.state_distribution(tenant)

    def q(vals, p):
        if not vals:
            return 0.0
        s = sorted(vals)
        return round(s[min(len(s) - 1, int(p * len(s)))] / BP, 4)

    # 合并质量：批次数与父节点数（merge_snapshot 中不同 parent）
    snap = 0
    parents = 0
    try:
        rows = engine.storage._conn.execute(  # sqlite only
            "SELECT COUNT(*) c, COUNT(DISTINCT parent_id) p FROM merge_snapshot").fetchone()
        snap, parents = rows["c"], rows["p"]
    except Exception:
        pass

    return {
        "tenant": tenant,
        "nodes": len(nodes),
        "edges": engine.storage.count_edges(tenant),
        "events": engine.storage.count_events(tenant) if hasattr(engine.storage, "count_events") else None,
        "state_distribution": dist,
        "weight_avg": round((sum(weights) / len(weights) / BP) if weights else 0.0, 4),
        "weight_min": q(weights, 0.0),
        "weight_p50": q(weights, 0.5),
        "weight_p95": q(weights, 0.95),
        "weight_max": q(weights, 1.0),
        "merge_snapshot_rows": snap,
        "merge_parents": parents,
    }
