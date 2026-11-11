"""合并器（设计书 6.3）：社区检测 + 软合并父节点权重。

- 社区检测：优先 igraph+leidenalg（Leiden）；不可用时退回 networkx Louvain。
- 软合并：新建 ABSTRACT 父节点 + MEMBER_OF 边，成员全部保留。
- 父节点权重：W_new = min(W_MAX, λ_m · ΣW_i · (1 + log2(1+n)/4))，λ_m = 0.80。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from brainmem.core.models import MemoryEdge


@dataclass
class Cluster:
    members: list[str]          # 成员节点 id
    edges: list[MemoryEdge]     # 簇内边（用于判断连接强度）


def find_clusters(
    nodes: dict[str, float],      # id -> weight_bp（仅参与合并的候选）
    edges: list[MemoryEdge],
    min_edge_bp: int,
    min_coact: int,
) -> list[Cluster]:
    """在候选子图上做社区检测，返回满足合并条件的簇。"""
    cand = set(nodes)
    sub = [e for e in edges if e.src_id in cand and e.dst_id in cand]
    # 只保留强边（边权 & 共激活达标）作为社区检测的边
    strong = [e for e in sub if e.weight_bp >= min_edge_bp and e.coactivation >= min_coact]
    if not strong:
        return []

    membership: list[list[str]] = []
    try:
        import igraph as ig
        import leidenalg

        idx: dict[str, int] = {}
        g = ig.Graph()
        for e in strong:
            for n in (e.src_id, e.dst_id):
                if n not in idx:
                    idx[n] = len(idx)
        g.add_vertices(len(idx))
        g.add_edges([(idx[e.src_id], idx[e.dst_id]) for e in strong])
        g.es["weight"] = [e.weight_bp for e in strong]
        part = leidenalg.find_partition(
            g, leidenalg.ModularityVertexPartition, weights="weight")
        rev = {v: k for k, v in idx.items()}
        membership = [[rev[v] for v in cluster] for cluster in part]
    except Exception:
        import networkx as nx
        from networkx.algorithms.community import louvain_communities

        G = nx.Graph()
        for e in strong:
            G.add_edge(e.src_id, e.dst_id, weight=e.weight_bp)
        membership = [list(c) for c in louvain_communities(G, weight="weight")]

    clusters: list[Cluster] = []
    for members in membership:
        if len(members) < 2:
            continue
        mset = set(members)
        intern = [e for e in strong if e.src_id in mset and e.dst_id in mset]
        clusters.append(Cluster(members=members, edges=intern))
    return clusters


def parent_weight_bp(member_weights_bp: list[int], w_max_bp: int, lam: float = 0.80) -> int:
    """父节点权重：min(W_MAX, λ_m · ΣW_i · (1 + log2(1+n)/4))。"""
    if not member_weights_bp:
        return 0
    s = sum(member_weights_bp)
    n = len(member_weights_bp)
    w = lam * s * (1.0 + math.log2(1 + n) / 4.0)
    return min(w_max_bp, int(w + 0.5))


def name_parent(members_labels: list[str], weights_bp: list[int]) -> str:
    """父节点名：取簇内权重最高的实体名（评审：全自动，不设人工确认）。"""
    if not members_labels:
        return "abstract"
    i = max(range(len(members_labels)), key=lambda k: weights_bp[k])
    return members_labels[i][:10]
