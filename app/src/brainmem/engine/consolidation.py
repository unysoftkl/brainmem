"""巩固批处理（设计书 6.3 / 6.4 / 阶段4）。

- run_nightly：采样 → 合并（社区检测 + 软合并）。
- merge：Leiden 社区检测 + 软合并父节点，写 MERGE 事件 + 合并快照。
- merge_undo：按 batch_id 一键回滚（权重误差 0.00）。
每个阶段按 batch_id 幂等（记录到 consolidation_run）。

注：原 `global_normalize`（乘性全局归一，W_i ← W_i·W_target/mean）已按用户
要求移除。理由：它把所有记忆按同一系数等比例放大、会"复活"本该遗忘的条目，
与"用进废退"的核心设计相悖，也不是仿脑机制（人脑睡眠是选择性巩固，而非
等比例放大整体权重）。`weekly` 参数保留以兼容既有调用签名，但不再产生额外行为。
"""
from __future__ import annotations

from typing import Any

from brainmem.core.decay import BP, decay_bp, show
from brainmem.core.enums import EdgeRelation, EventType, NodeKind, SourceKind, State
from brainmem.core.ids import new_id
from brainmem.core.lifecycle import state_of
from brainmem.core.models import ConsolidationRun, MemoryEdge, MemoryNode
from brainmem.engine.events import make_event
from brainmem.services.merger import find_clusters, name_parent, parent_weight_bp


class Consolidator:
    def __init__(self, engine):
        self.e = engine
        self.p = engine.p
        self.s = engine.storage
        self.clock = engine.clock
        self.tenant = engine.tenant

    # ------------------------------------------------------------------ 夜间
    def run_nightly(self, batch_id: str | None = None, weekly: bool = False,
                    min_edge_bp: float | None = None,
                    min_coact: int | None = None) -> dict:
        """夜间巩固：采样 → 合并。

        `weekly` 仅为兼容签名保留：原先它额外触发 global_normalize，
        该机制已移除，因此现在传入 weekly 不改变任何行为。
        """
        batch_id = batch_id or new_id()
        start_real = self.clock.now_real()
        sampled = 0
        changed = 0

        if min_edge_bp is None:
            min_edge_bp = self.p.merge_edge
        if min_coact is None:
            min_coact = self.p.merge_coact

        # 1. 采样
        nodes = {n.id: n for n in self.s.list_nodes(self.tenant)}
        sampled = len(nodes)

        # 2. 合并（先取当前衰减后的权重作为合并输入）
        weights: dict[str, int] = {}
        now = self.clock.now_day()
        for nid, n in nodes.items():
            weights[nid] = decay_bp(n.weight_bp, n.stability, now - n.last_touch_at, self.p)
        edges = list(self.s.all_edges(self.tenant))
        clusters = find_clusters(weights, edges, int(min_edge_bp * BP), min_coact)

        merge_reports: list[dict] = []
        for cl in clusters:
            rep = self._merge_cluster(batch_id, cl, weights)
            if rep:
                merge_reports.append(rep)
                changed += 1

        run = ConsolidationRun(
            id=batch_id, run_type="nightly" + ("+weekly" if weekly else ""),
            started_at=start_real, finished_at=self.clock.now_real(),
            sampled=sampled, changed=changed,
            params=f"min_edge_bp={min_edge_bp},min_coact={min_coact}",
            report=str({"merges": merge_reports}),
        )
        with self.s.transaction() as tx:
            tx.insert_consolidation_run(run)
        return {"batch_id": batch_id, "sampled": sampled, "changed": changed,
                "merges": merge_reports}

    # ------------------------------------------------------------------ 合并
    def _merge_cluster(self, batch_id: str, cluster, weights: dict[str, int]) -> dict | None:
        member_ids = [m for m in cluster.members if m in weights]
        if len(member_ids) < 2:
            return None
        now = self.clock.now_day()
        with self.s.transaction() as tx:
            members = [tx.get_node(mid) for mid in member_ids]
            members = [m for m in members if m is not None]
            if len(members) < 2:
                return None
            mweights = [weights[m.id] for m in members]
            labels = [m.label for m in members]
            pw = parent_weight_bp(mweights, self.p.W_MAX_BP)
            parent = MemoryNode(
                id=new_id(), tenant_id=self.tenant,
                label=name_parent(labels, mweights)[:10], label_norm="merge:" + new_id(),
                char_len=min(10, len(name_parent(labels, mweights)) or 1),
                kind=NodeKind.ABSTRACT, weight_bp=pw, stability=0, peak_bp=pw,
                state=state_of(pw), fidelity=80, gist=name_parent(labels, mweights)[:20],
                fingerprint="merge:" + new_id(), salience=80,
                born_at=now, last_touch_at=now, source_kind=SourceKind.SYSTEM,
            )
            tx.upsert_node(parent)
            tx.upsert_embedding(parent.id, self.tenant, self.e.embedder.encode(parent.label))
            self.e._index_add(parent)
            tx.append_event(make_event(parent, EventType.CREATE, 0, pw, "merge:new", "system", self.clock))
            # 快照（成员原权重，供回滚）
            tx.save_merge_snapshot(batch_id, parent.id,
                                   [(m.id, m.weight_bp) for m in members], now)
            # MEMBER_OF 边（成员全部保留）
            for m in members:
                tx.upsert_edge(MemoryEdge(
                    id=new_id(), tenant_id=self.tenant, src_id=parent.id, dst_id=m.id,
                    relation=EdgeRelation.MEMBER_OF, weight_bp=int(8.0 * BP),
                    coactivation=0, created_at=now, last_touch_at=now,
                ))
                tx.append_event(make_event(m, EventType.MERGE, m.weight_bp, m.weight_bp,
                                           f"merge:{batch_id}", "system", self.clock))
        return {"parent_id": parent.id, "name": parent.label,
                "members": member_ids, "parent_weight": show(pw)}

    def merge_undo(self, batch_id: str) -> dict[str, Any]:
        """一键回滚：删除父节点与 MEMBER_OF 边，成员权重恢复原值（误差 0.00）。"""
        snaps = self.s.get_merge_snapshot(batch_id)
        if not snaps:
            return {"batch_id": batch_id, "undone": 0}
        parent_ids = {s["parent_id"] for s in snaps}
        now = self.clock.now_day()
        with self.s.transaction() as tx:
            for s in snaps:
                n = tx.get_node(s["member_id"])
                if n is not None:
                    tx.upsert_node(n.model_copy(update={
                        "weight_bp": s["old_weight_bp"],
                        "last_touch_at": now,
                        "state": state_of(s["old_weight_bp"]),
                    }))
                    tx.append_event(make_event(n, EventType.RESTORE, n.weight_bp,
                                               s["old_weight_bp"], f"merge_undo:{batch_id}",
                                               "system", self.clock))
            for pid in parent_ids:
                tx.delete_node(pid)  # 连带删除其 MEMBER_OF 边
        return {"batch_id": batch_id, "undone": len(snaps), "parents_removed": len(parent_ids)}
