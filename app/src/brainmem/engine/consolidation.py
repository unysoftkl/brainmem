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
from brainmem.core import text as textops
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

    def merge_soft(self, node_ids: list[str], new_text: str, source: str = "AI",
                   batch_id: str | None = None) -> dict[str, Any]:
        """按指定成员做**软合并**：新建一个 ABSTRACT 父节点（标题 new_text），
        用 MEMBER_OF 边把每个成员挂到父节点下，**成员全部保留、原文不丢、连接原样都在**。

        与"硬合并"相反：这里旧记忆一条不删，
        展开父节点即可看到"原来几条记忆及其相互连接"。可 merge_undo 回滚。
        """
        from brainmem.core.tables import MAX_LABEL_CHARS

        t = (new_text or "").strip()
        if not (1 <= len(t) <= MAX_LABEL_CHARS):
            from brainmem.core.errors import TooLongError
            raise TooLongError(f"合并标题需 1–{MAX_LABEL_CHARS} 字（当前 {len(t)} 字）")
        ids = [i for i in dict.fromkeys(node_ids) if i]
        if len(ids) < 2:
            from brainmem.core.errors import TooLongError
            raise TooLongError("merge 至少需要 2 条记忆")

        # 合并前置条件（计划书 6.3）：成员之间必须由"强连接"连通，否则拒绝
        ok, info = self.e._strong_cluster_ok(ids)
        if not ok:
            from brainmem.core.errors import TooLongError
            raise TooLongError(
                "这些记忆之间的联系还不够强，暂不能合并：需先用 memory_link 反复加强，"
                f"使它们之间边权 ≥ {self.p.merge_edge:.2f}、共激活 ≥ {self.p.merge_coact}，"
                f"且该连接自身能撑 ≥ {self.p.merge_edge_min_days:.0f} 天。"
                f"当前最强内部边：{info['current_best_edge']}；已达标的强边数：{info['ok_edges']}。"
            )

        batch_id = batch_id or new_id()
        now = self.clock.now_day()
        nodes = {n.id: n for n in self.s.list_nodes(self.tenant)}
        members = [nodes[i] for i in ids if i in nodes]
        if len(members) < 2:
            from brainmem.core.errors import NotFoundError
            raise NotFoundError("merge 的目标记忆不足 2 条（可能已被合并/删除）")

        mweights = [m.weight_bp for m in members]
        pw = parent_weight_bp(mweights, self.p.W_MAX_BP)

        # 汇总成员可复原的原文：①成员自己带 verbatim（note 节点）②成员 PART_OF 指向的 note 节点原文
        texts: list[str] = []
        seen_txt: set[str] = set()
        idset = set(ids)

        def _add(txt: str | None):
            if not txt:
                return
            t2 = str(txt).strip()
            if t2 and t2 not in seen_txt:
                seen_txt.add(t2)
                texts.append(t2)

        for m in members:
            if m.verbatim_ref:
                try:
                    _add(self.e.blob_store.get(m.verbatim_ref).decode("utf-8"))
                except Exception:
                    pass
            # 原子若通过 source_id 指向自己的原文 note，也把它卷进来
            if m.source_id:
                note = self.s.get_node(m.source_id)
                if note is not None and note.verbatim_ref:
                    try:
                        _add(self.e.blob_store.get(note.verbatim_ref).decode("utf-8"))
                    except Exception:
                        pass
        merged_text = "\n\n---\n\n".join(texts)
        ver_ref = self.e.blob_store.put(merged_text.encode("utf-8")) if merged_text else None

        with self.s.transaction() as tx:
            parent = MemoryNode(
                id=new_id(), tenant_id=self.tenant,
                label=t, label_norm=textops.normalize(t),
                char_len=len(t), kind=NodeKind.ABSTRACT, weight_bp=pw,
                stability=0, peak_bp=pw, state=state_of(pw),
                fidelity=80, gist=(merged_text[:200] if merged_text else t[:20]),
                fingerprint="merge:" + new_id(),
                salience=80, born_at=now, last_touch_at=now,
                source_kind=SourceKind.SYSTEM,
                verbatim_ref=ver_ref,
            )
            tx.upsert_node(parent)
            tx.upsert_embedding(parent.id, self.tenant, self.e.embedder.encode(t))
            self.e._index_add(parent)
            tx.append_event(make_event(parent, EventType.CREATE, 0, pw,
                                       "merge_soft:new", source, self.clock))
            # 回滚快照（记录成员原权重）
            tx.save_merge_snapshot(batch_id, parent.id,
                                   [(m.id, m.weight_bp) for m in members], now)
            # MEMBER_OF 边：父 → 每个成员，成员全部保留
            for m in members:
                tx.upsert_edge(MemoryEdge(
                    id=new_id(), tenant_id=self.tenant,
                    src_id=parent.id, dst_id=m.id,
                    relation=EdgeRelation.MEMBER_OF, weight_bp=int(8.0 * BP),
                    coactivation=0, created_at=now, last_touch_at=now,
                ))
                tx.append_event(make_event(m, EventType.MERGE, m.weight_bp, m.weight_bp,
                                           f"merge_soft:{batch_id}", source, self.clock))
        return {
            "mode": "soft",
            "id": parent.id, "label": parent.label, "weight": show(pw),
            "state": state_of(pw).value,
            "members": ids, "member_count": len(members),
            "batch_id": batch_id,
            "has_verbatim": bool(merged_text),
            "verbatim_chars": len(merged_text),
            "note": "成员全部保留，父节点下用 MEMBER_OF 挂住；原文已汇总进父节点(可 memory_get 展开)；可 merge_undo 回滚",
        }

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
