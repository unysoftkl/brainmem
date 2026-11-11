"""图引擎：扩散激活（个性化 PageRank 的截断版，设计书 5.4.1）。

a_v = Σ_{u∈N(v)} E_uv / Σ_{w∈N(u)} E_uw · a_u · γ_hop
最多 hops 跳，γ_hop 默认 0.55。超级节点（度数>10000）出边乘 1/sqrt(log10 d) 阻尼。
"""
from __future__ import annotations

import math

from brainmem.storage.base import Storage


def spreading_activation(
    storage: Storage,
    seeds: dict[str, float],
    hops: int = 2,
    gamma: float = 0.55,
    max_degree: int = 10000,
) -> dict[str, float]:
    act: dict[str, float] = dict(seeds)
    frontier = dict(seeds)
    for _ in range(max(0, hops)):
        new: dict[str, float] = {}
        for u, a in frontier.items():
            edges = storage.incident(u, limit=500)
            total = sum(e.weight_bp for e in edges) or 1
            deg = len(edges)
            damp = 1.0 if deg <= max_degree else 1.0 / math.sqrt(math.log10(deg) + 1e-9)
            for e in edges:
                v = e.dst_id if e.src_id == u else e.src_id
                if v == u:
                    continue
                contrib = (e.weight_bp / total) * a * gamma * damp
                new[v] = new.get(v, 0.0) + contrib
        for v, val in new.items():
            act[v] = act.get(v, 0.0) + val
        frontier = new
    return act
