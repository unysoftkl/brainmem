"""MemoryEngine · 阶段1 记忆内核编排层。

职责：把 core 的纯算法与 storage 的持久化编排成完整业务流程。
- 写入：原子记忆 ≤10 字（超长拒绝并提示先概括）→规范化→查重→编码→落库，单事务。
  带原文记忆用 write_note(title, full_text)：短标题入库、原文进冷存。
- 读取：惰性求值当前权重（不落库、不推进 last_touch）。
- 结算：写路径把自然衰减结算成 DECAY 事件，再叠加变更。
- 复算：事件流投影对账。
"""
from __future__ import annotations

from typing import Any

from brainmem.config import Config
from brainmem.core import text as textops
from brainmem.core.decay import bp, days_to_zero, decay_bp, show
from brainmem.core.enums import STATE_LEVEL, EdgeRelation, EventType, NodeKind, SourceKind, State
from brainmem.core.errors import NotFoundError, TooLongError
from brainmem.core.ids import new_id
from brainmem.core.lifecycle import state_of, transition
from brainmem.core.models import MemoryEdge, MemoryNode, MemoryVersion
from brainmem.core.params import BP
from brainmem.core.tables import fidelity_pct, initial_weight
from brainmem.core.time import SystemClock, TimeSource
from brainmem.core.weights import fidelity_after_reinforce, reinforce
from brainmem.engine.events import make_event, reconcile_node, replay
from brainmem.engine.retrieval import Retriever
from brainmem.services import similarity as sim
from brainmem.services.blobstore import BlobStore, InMemoryBlobStore
from brainmem.services.compressor import condense as compress_condense
from brainmem.services.compressor import vestige as compress_vestige
from brainmem.services.embedder import EmbeddingProvider, HashEmbedder
from brainmem.storage.base import Storage


class MemoryEngine:
    def __init__(self, cfg: Config, storage: Storage, clock: TimeSource | None = None,
                 embedder: EmbeddingProvider | None = None,
                 blob_store: BlobStore | None = None):
        self.cfg = cfg
        self.storage = storage
        self.clock = clock or SystemClock()
        self.p = cfg.params()
        self.tenant = cfg.tenant
        self.embedder = embedder or HashEmbedder()
        self.retriever = Retriever(cfg, storage, self.clock, self.embedder)
        self.blob_store: BlobStore = blob_store or InMemoryBlobStore()
        self._char_index: dict[str, set[str]] | None = None

    # ------------------------------------------------------------------ 写入
    def write(
        self,
        text: str,
        *,
        source: str = "HUMAN",
        salience: int = 50,
        tags: list[str] | None = None,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        n = len(text)
        if n < 1:
            raise TooLongError("空文本：请提供至少 1 个字的内容")
        if not textops.has_meaningful_char(textops.normalize(text)):
            raise TooLongError("内容不含实义字符（纯标点/空白/符号），不予入库")
        from brainmem.core.tables import MAX_LABEL_CHARS
        if n > MAX_LABEL_CHARS:
            raise TooLongError(
                f"内容 {n} 字超过上限 {MAX_LABEL_CHARS} 字：请再简写"
                f"（保留原文请用 memory_ingest 的 text 参数）"
            )
        return self._write_atom(text, source=source, salience=salience, trace_id=trace_id)

    def write_note(
        self,
        title: str,
        content: str,
        *,
        source: str = "HUMAN",
        salience: int = 50,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        """标题入库 + 原文进冷存。图里显示标题，原文随时可查。字数上限见 MAX_LABEL_CHARS。"""
        t = (title or "").strip()
        from brainmem.core.tables import MAX_LABEL_CHARS
        if not (1 <= len(t) <= MAX_LABEL_CHARS):
            raise TooLongError(f"标题需 1–{MAX_LABEL_CHARS} 字（当前 {len(t)} 字）")
        if not content:
            raise TooLongError("原文不能为空")
        ref = self.blob_store.put(content.encode("utf-8"))
        return self._write_atom(
            t, source=source, salience=salience, trace_id=trace_id,
            gist_override=content, verbatim_ref=ref,
        )

    def _write_atom(
        self,
        text: str,
        *,
        source: str = "HUMAN",
        salience: int = 50,
        trace_id: str | None = None,
        extra_verbatim: str | None = None,
        gist_override: str | None = None,
        verbatim_ref: str | None = None,
    ) -> dict[str, Any]:
        norm = textops.normalize(text)
        fp = textops.fingerprint(norm, source)
        now = self.clock.now_day()

        with self.storage.transaction() as tx:
            dup = tx.find_by_norm(self.tenant, norm)
            if dup is not None:
                gap = now - dup.last_touch_at
                if gap <= self.cfg.dedup_window_days:
                    # 幂等窗口内：不新建、不强化
                    return self._result(dup, created=False, deduped=True)
                # 窗口外：重复录入 → 强化
                updated = self._reinforce(tx, dup, now, "write:repeat", source, trace_id)
                return self._result(updated, created=False, deduped=False)

            # 语义查重（双门限，设计书 5.3）——默认关闭以保住热写 P95；
            # 开启时用字符倒排（共享≥2 字符、上限 200）做候选剪枝。
            emb = self.embedder.encode(text)
            best_id, best_s = (None, 0.0)
            if self.cfg.semantic_dedup:
                best_id, best_s = self._best_match(norm, emb)
            if best_id is not None and best_s >= 0.92:
                # 同一记忆：不新建，触发强化
                node = tx.get_node(best_id)
                updated = self._reinforce(tx, node, now, "write:similar", source, trace_id)
                return self._result(updated, created=False, deduped=False)

            # 新建
            node = self._new_node(text, norm, fp, source, salience, now)
            if gist_override is not None or verbatim_ref is not None:
                upd: dict[str, Any] = {}
                if gist_override is not None:
                    upd["gist"] = gist_override[:200]
                if verbatim_ref is not None:
                    upd["verbatim_ref"] = verbatim_ref
                node = node.model_copy(update=upd)
            tx.upsert_node(node)
            tx.upsert_embedding(node.id, self.tenant, emb)
            self._index_add(node)
            ev = make_event(node, EventType.CREATE, 0, node.weight_bp, "write:new", source, self.clock, trace_id)
            tx.append_event(ev)
            tx.insert_version(
                MemoryVersion(
                    id=new_id(), node_id=node.id, version_no=1, gist=node.gist,
                    verbatim_ref=node.verbatim_ref, diff=None, created_at=now,
                    created_by=source, reason="create",
                )
            )
            # 相关但不同（0.75 ≤ s < 0.92）：新建并建 ASSOCIATED 边
            if best_id is not None and best_s >= 0.75:
                tx.upsert_edge(MemoryEdge(
                    id=new_id(), tenant_id=self.tenant, src_id=node.id, dst_id=best_id,
                    relation=EdgeRelation.ASSOCIATED, weight_bp=int(best_s * BP),
                    coactivation=0, created_at=now, last_touch_at=now,
                ))
            return self._result(node, created=True, deduped=False)

    def _ensure_index(self) -> None:
        if self._char_index is not None:
            return
        self._char_index = {}
        for node in self.storage.list_nodes(self.tenant):
            for ch in set(node.label_norm):
                self._char_index.setdefault(ch, set()).add(node.id)

    def _index_add(self, node: MemoryNode) -> None:
        self._ensure_index()
        assert self._char_index is not None
        for ch in set(node.label_norm):
            self._char_index.setdefault(ch, set()).add(node.id)

    def _best_match(self, norm: str, emb: list[float]) -> tuple[str | None, float]:
        """语义查重候选：字符倒排取"至少共享 2 个字符"的候选（按共享数降序、上限 200），
        再算完整相似度。要求共享≥2 避免"只共享一个常见字"导致的 O(N) 全表比较。
        """
        self._ensure_index()
        assert self._char_index is not None
        from collections import Counter

        counts: Counter[str] = Counter()
        for ch in set(norm):
            posting = self._char_index.get(ch, ())
            # 常见字（posting 过大）判别力低，跳过以免 O(N)
            if len(posting) > 500:
                continue
            for nid in posting:
                counts[nid] += 1
        cand = [nid for nid, c in counts.most_common(200) if c >= 2]
        best_id, best_s = None, 0.0
        for nid in cand:
            node = self.storage.get_node(nid)
            if node is None:
                continue
            vec = self.storage.get_embedding(nid)
            if vec is None:
                continue
            s = sim.similarity(norm, node.label_norm, emb, vec)
            if s > best_s:
                best_s, best_id = s, nid
        return best_id, best_s

    def _new_node(
        self, text: str, norm: str, fp: str, source: str, salience: int, now: float
    ) -> MemoryNode:
        n = len(text)
        w0 = initial_weight(n)
        wb = int(w0 * BP + 0.5)
        return MemoryNode(
            id=new_id(), tenant_id=self.tenant, label=text, label_norm=norm,
            char_len=n, weight_bp=wb, stability=0, peak_bp=wb, state=state_of(wb),
            fidelity=fidelity_pct(n), gist=textops.make_gist(text), verbatim_ref=None,
            fingerprint=fp, salience=salience, born_at=now, last_touch_at=now,
            source_kind=SourceKind(source),
        )

    def _reinforce(
        self, tx: Storage, node: MemoryNode, now: float, reason: str,
        actor: str, trace_id: str | None,
    ) -> MemoryNode:
        dt = now - node.last_touch_at
        wb0 = decay_bp(node.weight_bp, node.stability, dt, self.p)
        if wb0 != node.weight_bp:
            tx.append_event(make_event(node, EventType.DECAY, node.weight_bp, wb0, "decay:pre", actor, self.clock))
        new_wb, new_s, new_peak, _ = reinforce(wb0, node.stability, node.peak_bp, dt, self.p)
        tx.append_event(make_event(node, EventType.REINFORCE, wb0, new_wb, reason, actor, self.clock, trace_id))
        old_state = state_of(wb0)
        new_state = state_of(new_wb)
        updated = node.model_copy(update={
            "weight_bp": new_wb, "stability": new_s, "peak_bp": new_peak,
            "last_touch_at": now, "fidelity": fidelity_after_reinforce(node.fidelity),
            "state": new_state,
        })
        if STATE_LEVEL[new_state] > STATE_LEVEL[old_state]:
            # 升档：从冷存回挂原文摘要，保真度恢复（设计书 4.6 / 5.2.3）
            extra: dict[str, Any] = {}
            if node.verbatim_ref:
                try:
                    extra["gist"] = self.blob_store.get(node.verbatim_ref).decode("utf-8")[:60]
                except Exception:
                    pass
            if extra:
                updated = updated.model_copy(update=extra)
            tx.append_event(make_event(updated, EventType.RESTORE, new_wb, new_wb,
                                       f"state:{old_state.value}->{new_state.value}", actor, self.clock))
        tx.upsert_node(updated)
        return updated

    def _apply_use(
        self, tx: Storage, node: MemoryNode, now: float, reason: str, actor: str = "ai",
    ) -> MemoryNode:
        """**用进废退**：一次"使用"（检索命中/被取用）给节点加固定权重。
        与 _reinforce 不同：这里不抬稳固度、按固定 use_boost 加、封顶 W_MAX。
        先结算自然衰减（写 DECAY 事件），再写 REINFORCE 事件，保持事件流自洽。"""
        dt = now - node.last_touch_at
        wb0 = decay_bp(node.weight_bp, node.stability, dt, self.p)
        if wb0 != node.weight_bp:
            tx.append_event(make_event(node, EventType.DECAY, node.weight_bp, wb0,
                                       "decay:pre", actor, self.clock))
        boost_bp = int(self.p.use_boost * BP)
        cap = self.p.W_MAX_BP
        new_wb = min(cap, wb0 + boost_bp)
        if new_wb != wb0:
            tx.append_event(make_event(node, EventType.REINFORCE, wb0, new_wb,
                                       reason, actor, self.clock))
        old_state = state_of(wb0)
        new_state = state_of(new_wb)
        updated = node.model_copy(update={
            "weight_bp": new_wb, "peak_bp": max(node.peak_bp, new_wb),
            "last_touch_at": now, "state": new_state,
        })
        if STATE_LEVEL[new_state] > STATE_LEVEL[old_state] and node.verbatim_ref:
            try:
                updated = updated.model_copy(
                    update={"gist": self.blob_store.get(node.verbatim_ref).decode("utf-8")[:60]})
            except Exception:
                pass
            tx.append_event(make_event(updated, EventType.RESTORE, new_wb, new_wb,
                                       f"state:{old_state.value}->{new_state.value}",
                                       actor, self.clock))
        tx.upsert_node(updated)
        return updated

    def _walk_edges(
        self, tx: Storage, seed_ids: list[str], now: float, actor: str = "ai",
    ) -> int:
        """检索走到过的连接：给这些边加权重 + 记一次共激活（用进废退）。返回处理边数。"""
        from brainmem.core.edge import edge_reinforce_bp

        touched: set[str] = set()
        n = 0
        for sid in seed_ids:
            for e in tx.incident(sid, limit=500):
                if e.id in touched:
                    continue
                touched.add(e.id)
                # 边权重按 walk_edge_boost 温和增加；共激活 +1
                new_w = min(int(self.p.E_MAX * BP),
                            e.weight_bp + int(self.p.walk_edge_boost * BP))
                new_c = e.coactivation + 1
                tx.upsert_edge(e.model_copy(update={
                    "weight_bp": new_w, "coactivation": new_c, "last_touch_at": now}))
                n += 1
        return n

    # ------------------------------------------------------------------ 读取
    def get(self, node_id: str, include_verbatim: bool = False) -> dict[str, Any]:
        node = self.storage.get_node(node_id)
        if node is None:
            raise NotFoundError(node_id)
        proj = self._project(node)
        versions = self.storage.list_versions(node_id)
        out = {
            "id": node.id,
            "label": node.label,
            "gist": node.gist,
            "weight": show(proj),
            "weight_bp": proj,
            "state": state_of(proj).value,
            "stability": node.stability,
            "fidelity": node.fidelity,
            "char_len": node.char_len,
            "source_kind": node.source_kind.value,
            "born_at": node.born_at,
            "last_touch_at": node.last_touch_at,
            "versions": len(versions),
        }
        if include_verbatim:
            out["verbatim"] = self._verbatim_of(node)
        return out

    def _verbatim_of(self, node: MemoryNode) -> str:
        """原文：优先从冷存回读，回读失败退回标签本身。"""
        if node.verbatim_ref:
            try:
                return self.blob_store.get(node.verbatim_ref).decode("utf-8")
            except Exception:
                pass
        return node.label

    def _purge_blob_if_unused(self, ref: str | None, exclude_id: str) -> bool:
        """安全清理冷存 blob：仅当没有任何其它现存节点还引用同一 ref 时才删。
        blob 按内容哈希共享，删前必须确认独占，否则会误删别人的原文。"""
        if not ref:
            return False
        for other in self.storage.list_nodes(self.tenant):
            if other.id != exclude_id and other.verbatim_ref == ref:
                return False  # 还有别的节点在用，保留
        try:
            return bool(self.blob_store.delete(ref))
        except Exception:
            return False

    def _project(self, node: MemoryNode) -> int:
        """惰性求值：不改变状态，只算出当前权重（不落库、不推进 last_touch）。"""
        return decay_bp(node.weight_bp, node.stability, self.clock.now_day() - node.last_touch_at, self.p)

    # ------------------------------------------------------------------ 结算
    def settle(self, node_id: str, day: float | None = None) -> dict[str, Any]:
        """显式结算到指定逻辑天：写 DECAY 事件、更新状态；归零则物理删除。"""
        target = self.clock.now_day() if day is None else day
        with self.storage.transaction() as tx:
            node = tx.get_node(node_id)
            if node is None:
                raise NotFoundError(node_id)
            updated, deleted = self._apply_decay(tx, node, target)
            return {"id": updated.id, "weight": show(updated.weight_bp),
                    "state": updated.state.value, "deleted": deleted}

    def sweep_expired(self, dry_run: bool = True) -> dict[str, Any]:
        """**归零清理**：扫描全部记忆，只对"权重已归零"的节点做物理删除（连边一起，原文清冷存）。

        - 不刷新、不重算那些还没归零的记忆——它们的 weight_bp 一个字节都不动（惰性结算照旧，
          读取时 decay_bp 现算本来就是对的）。
        - 只动"已归零"这个最小集合，写操作极少。
        - dry_run=True（默认）：只列出"将删除清单"，不真删；确认无误后可 dry_run=False 真删。

        返回：{"dry_run","day","scanned","expired","deleted","items":[...]}"""
        now = self.clock.now_day()
        expired: list[dict[str, Any]] = []
        for n in self.storage.list_nodes(self.tenant):
            proj = decay_bp(n.weight_bp, n.stability, now - n.last_touch_at, self.p)
            if proj <= 0:  # 已归零
                expired.append({
                    "id": n.id, "label": n.label,
                    "weight_bp": n.weight_bp,
                    "state": n.state.value,
                    "days_since_touch": round(now - n.last_touch_at, 2),
                    "has_verbatim": bool(n.verbatim_ref),
                })

        deleted = 0
        if not dry_run and expired:
            for item in expired:
                with self.storage.transaction() as tx:
                    node = tx.get_node(item["id"])
                    if node is None:
                        continue
                    updated, was_deleted = self._apply_decay(tx, node, now)
                    if was_deleted:
                        deleted += 1
        return {
            "dry_run": dry_run,
            "day": now,
            "scanned": len(self.storage.list_nodes(self.tenant)),
            "expired": len(expired),
            "deleted": deleted,
            "items": expired,
        }

    def _apply_decay(
        self, tx: Storage, node: MemoryNode, day: float
    ) -> tuple[MemoryNode, bool]:
        dt = day - node.last_touch_at
        new_wb = decay_bp(node.weight_bp, node.stability, dt, self.p)
        if new_wb != node.weight_bp:
            tx.append_event(make_event(node, EventType.DECAY, node.weight_bp, new_wb, "cron:lazy", "system", self.clock))
        old_state = node.state
        new_state = state_of(new_wb)
        if new_state == State.DELETED:
            # 物理删除前：记录被连带删除的边（审计），供对账/追溯
            cut_edges = [
                {"edge_id": e.id, "relation": e.relation.value,
                 "other": (e.dst_id if e.src_id == node.id else e.src_id),
                 "edge_weight": round(e.weight_bp / BP, 4)}
                for e in self.storage.incident(node.id, limit=500)
            ]
            tx.append_event(make_event(node, EventType.DELETE, node.weight_bp, 0,
                                       f"weight_zero;edges_cut={len(cut_edges)}", "system", self.clock))
            tx.delete_node(node.id)
            # 清理该节点独占的 verbatim 冷存（共享的 blob 不动）
            self._purge_blob_if_unused(node.verbatim_ref, exclude_id=node.id)
            return node.model_copy(update={"weight_bp": 0, "state": State.DELETED,
                                           "last_touch_at": day, "verbatim_ref": None}), True
        updated = node.model_copy(update={"weight_bp": new_wb, "last_touch_at": day, "state": new_state})
        if new_state != old_state:
            if STATE_LEVEL[new_state] < STATE_LEVEL[old_state]:
                # 降档：执行内容压缩（不是删除，原文仍在冷存）。
                # 压缩源优先取冷存原文（组合记忆的 label 只是 gist，原文才含全部实体）。
                src_text = node.label
                if node.verbatim_ref:
                    try:
                        src_text = self.blob_store.get(node.verbatim_ref).decode("utf-8")
                    except Exception:
                        pass
                if new_state == State.CONDENSED:
                    g, fid = compress_condense(src_text)
                    updated = updated.model_copy(update={"gist": g, "fidelity": min(updated.fidelity, fid)})
                elif new_state == State.VESTIGE:
                    g, fid = compress_vestige(src_text)
                    updated = updated.model_copy(update={"gist": g, "fidelity": min(updated.fidelity, fid)})
            etype = EventType.RESTORE if STATE_LEVEL[new_state] > STATE_LEVEL[old_state] else EventType.COMPRESS
            tx.append_event(make_event(updated, etype, new_wb, new_wb,
                                       f"state:{old_state.value}->{new_state.value}", "system", self.clock))
        tx.upsert_node(updated)
        return updated, False

    # ------------------------------------------------------------------ 删除
    def forget(self, node_id: str, mode: str = "hard") -> dict[str, Any]:
        with self.storage.transaction() as tx:
            node = tx.get_node(node_id)
            if node is None:
                raise NotFoundError(node_id)
            tx.append_event(make_event(node, EventType.DELETE, node.weight_bp, 0,
                                       "user_deleted" if mode == "hard" else "soft_delete", "user", self.clock))
            if mode == "hard":
                tx.delete_node(node_id)
            else:
                tx.upsert_node(node.model_copy(update={"state": State.DELETED, "weight_bp": 0,
                                                       "deleted_at": self.clock.now_day()}))
            return {"id": node_id, "mode": mode, "deleted": True}

    # ------------------------------------------------------------------ 统计
    def stats(self, tenant: str | None = None) -> dict[str, Any]:
        t = tenant or self.tenant
        return {
            "tenant": t,
            "nodes": self.storage.count_nodes(t),
            "edges": self.storage.count_edges(t),
            "avg_weight": round(self.storage.avg_weight_bp(t) / BP, 4),
            "states": self.storage.state_distribution(t),
        }

    # ------------------------------------------------------------------ 解释
    def explain(self, node_id: str) -> dict[str, Any]:
        node = self.storage.get_node(node_id)
        if node is None:
            raise NotFoundError(node_id)
        events = self.storage.iter_events(node_id)
        proj = self._project(node)
        dt = self.clock.now_day() - node.last_touch_at
        t_zero = days_to_zero(node.weight_bp, node.stability, self.p)
        return {
            "id": node.id,
            "current_weight": show(proj),
            "state": state_of(proj).value,
            "born_day": node.born_at,
            "last_touch_day": node.last_touch_at,
            "events": [
                {"seq": e.seq, "type": e.event_type.value, "delta": round(e.delta_bp / BP, 4),
                 "reason": e.reason}
                for e in events
            ],
            "decay_math": (
                f"k'={self.p.k:.4f}/(1+{node.stability}/{self.p.S0:.1f}); "
                f"自 last_touch 已过 {dt:.2f} 天; 若不再强化, 约 {t_zero:.1f} 天后归零"
            ),
            "explain": (
                f"创建时 {show(events[0].after_bp) if events else '—'}，"
                f"经 {len(events)} 条事件后当前 {show(proj)}，状态 {state_of(proj).value}"
            ),
        }

    # ------------------------------------------------------------------ 完整档案
    def overview(self, tenant: str | None = None) -> list[dict[str, Any]]:
        """列出所有记忆的关键字段（id/label/权重/状态/连接数），按权重降序。"""
        t = tenant or self.tenant
        now = self.clock.now_day()
        out = []
        for n in self.storage.list_nodes(t):
            w = decay_bp(n.weight_bp, n.stability, now - n.last_touch_at, self.p)
            deg = len(self.storage.incident(n.id, limit=500))
            out.append({
                "id": n.id, "label": n.label, "weight": show(w),
                "state": state_of(w).value, "kind": n.kind.value,
                "degree": deg, "age_days": round(now - n.born_at, 1),
                "days_to_zero": round(days_to_zero(n.weight_bp, n.stability, self.p), 1),
            })
        out.sort(key=lambda x: float(x["weight"]), reverse=True)
        return out

    def inspect(self, node_id: str) -> dict[str, Any]:
        """返回一条记忆的【全部数据】：字段、权重、状态、可解释、全部事件、所有关联边（含对端）。"""
        node = self.storage.get_node(node_id)
        if node is None:
            raise NotFoundError(node_id)
        now = self.clock.now_day()
        proj = self._project(node)
        events = self.storage.iter_events(node_id)
        versions = self.storage.list_versions(node_id)

        def _neighbor_brief(nid: str) -> dict[str, Any]:
            n = self.storage.get_node(nid)
            if n is None:
                return {"id": nid, "label": "(已删除)", "weight_bp": 0, "state": "DELETED"}
            w = decay_bp(n.weight_bp, n.stability, now - n.last_touch_at, self.p)
            return {"id": nid, "label": n.label, "weight": show(w), "state": state_of(w).value}

        edges = []
        for e in self.storage.incident(node_id, limit=500):
            other = e.dst_id if e.src_id == node_id else e.src_id
            direction = "out" if e.src_id == node_id else "in"
            edges.append({
                "edge_id": e.id,
                "relation": e.relation.value,
                "direction": direction,          # out=这条指向对端, in=对端指向这条
                "other": _neighbor_brief(other),
                "edge_weight": round(e.weight_bp / BP, 4),
                "coactivation": e.coactivation,
                "edge_state": e.state.value,
                "created_at": e.created_at,
                "last_touch_at": e.last_touch_at,
            })
        edges.sort(key=lambda x: x["edge_weight"], reverse=True)

        return {
            "node": {
                "id": node.id, "label": node.label, "label_norm": node.label_norm,
                "char_len": node.char_len, "kind": node.kind.value,
                "weight_bp": node.weight_bp, "weight": show(node.weight_bp),
                "current_weight": show(proj), "state": state_of(proj).value,
                "stability": node.stability, "peak_bp": node.peak_bp,
                "fidelity": node.fidelity, "gist": node.gist,
                "verbatim_ref": node.verbatim_ref,
                "verbatim": self._verbatim_of(node),
                "fingerprint": node.fingerprint, "salience": node.salience,
                "source_kind": node.source_kind.value, "source_id": node.source_id,
                "born_at": node.born_at, "last_touch_at": node.last_touch_at,
                "age_days": round(now - node.born_at, 2),
                "days_to_zero": round(days_to_zero(node.weight_bp, node.stability, self.p), 1),
            },
            "degree": {  # 关联统计
                "total": len(edges),
                "out": sum(1 for e in edges if e["direction"] == "out"),
                "in": sum(1 for e in edges if e["direction"] == "in"),
            },
            "edges": edges,
            "event_count": len(events),
            "events": [
                {"seq": e.seq, "type": e.event_type.value, "delta_bp": e.delta_bp,
                 "delta": round(e.delta_bp / BP, 4), "before": round(e.before_bp / BP, 4),
                 "after": round(e.after_bp / BP, 4), "reason": e.reason,
                 "at_day": e.at_day}
                for e in events
            ],
            "version_count": len(versions),
        }

    # ------------------------------------------------------------------ 对账
    def reconcile(self, sample_ratio: float = 1.0) -> dict[str, Any]:
        # 简化：阶段1 直接遍历（数据量小）；抽样按 id 哈希取模
        import hashlib

        checked = 0
        mismatched = 0
        mismatches: list[dict[str, Any]] = []
        for nid in self.storage.list_node_ids(self.tenant):
            if sample_ratio < 1.0:
                h = int(hashlib.sha256(nid.encode()).hexdigest(), 16) % 1000
                if h >= int(sample_ratio * 1000):
                    continue
            node = self.storage.get_node(nid)
            if node is None:
                continue
            ok, replayed, stored = reconcile_node(node, self.storage.iter_events(nid))
            checked += 1
            if not ok:
                mismatched += 1
                if len(mismatches) < 10:
                    mismatches.append({"id": nid, "replayed": replayed, "stored": stored})
        return {"checked": checked, "mismatched": mismatched, "mismatches": mismatches}

    # ------------------------------------------------------------------ 检索
    def search(self, query: str, top_k: int = 4, hops: int = 2,
               min_weight: float = 0.0, use: bool = False) -> list[dict[str, Any]]:
        """扩散激活检索。**用进废退**：`use=True` 时（默认走这个），检索命中的记忆
        各 +use_boost 权重、检索走过的连接各 +walk_edge_boost 权重并记一次共激活。
        （`use=False` 只读，用于纯查询/对账。）"""
        hits = self.retriever.search(query, top_k, hops, min_weight)
        if use and hits:
            now = self.clock.now_day()
            with self.storage.transaction() as tx:
                for h in hits:
                    node = tx.get_node(h.id)
                    if node is not None:
                        self._apply_use(tx, node, now, "use:search")
                self._walk_edges(tx, [h.id for h in hits], now)
                # 用强化后的权重回填结果（让调用方看到最新值）
                for h in hits:
                    node = tx.get_node(h.id)
                    if node is not None:
                        h.weight = show(node.weight_bp)
                        h.state = node.state.value
        return [h.to_dict() for h in hits]

    def feedback(self, node_id: str, signal: str = "positive", context: str = "") -> dict[str, Any]:
        """检索命中被实际使用 → 强化该节点，并共激活其邻边（设计书 5.4.2）。"""
        with self.storage.transaction() as tx:
            node = tx.get_node(node_id)
            if node is None:
                raise NotFoundError(node_id)
            if signal != "positive":
                return {"id": node_id, "weight": show(node.weight_bp),
                        "state": node.state.value, "signal": signal}
            updated = self._reinforce(tx, node, self.clock.now_day(), "retrieval:hit", "user", None)
            # 共激活邻居边
            from brainmem.core.edge import edge_reinforce_bp

            now = self.clock.now_day()
            for e in tx.incident(node_id, limit=50):
                new_w, new_c = edge_reinforce_bp(e.weight_bp, e.coactivation, self.p)
                tx.upsert_edge(e.model_copy(update={"weight_bp": new_w, "coactivation": new_c,
                                                    "last_touch_at": now}))
            return {"id": node_id, "weight": show(updated.weight_bp),
                    "state": updated.state.value, "signal": signal}

    def link(self, src: str, dst: str, relation: str = "ASSOCIATED",
             weight: float | None = None) -> dict[str, Any]:
        """建边。**连谁由 AI 判断，权重由记忆库给**：weight 不传时用库的初始边权
        (params.link_init)，已存在的边按同关系累加并计一次共激活。"""
        if weight is None:
            weight = self.p.link_init
        now = self.clock.now_day()
        with self.storage.transaction() as tx:
            if tx.get_node(src) is None:
                raise NotFoundError(src)
            if tx.get_node(dst) is None:
                raise NotFoundError(dst)
            existing = tx.get_edge(src, dst, relation)
            if existing is not None:
                wb = min(bp(self.p.E_MAX), existing.weight_bp + int(weight * BP))
                tx.upsert_edge(existing.model_copy(update={
                    "weight_bp": wb, "coactivation": existing.coactivation + 1,
                    "last_touch_at": now}))
                eid = existing.id
            else:
                eid = new_id()
                tx.upsert_edge(MemoryEdge(
                    id=eid, tenant_id=self.tenant, src_id=src, dst_id=dst,
                    relation=EdgeRelation(relation), weight_bp=int(weight * BP),
                    coactivation=1, created_at=now, last_touch_at=now,
                ))
            return {"edge_id": eid, "src": src, "dst": dst, "relation": relation,
                    "edge_weight": round(min(bp(self.p.E_MAX), int(weight * BP)) / BP, 4)}

    def link_many(self, pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """批量建边。pairs: [{"src":id,"dst":id,"relation":"ASSOCIATED"?}]，权重全由库给。"""
        out = []
        for p in pairs:
            out.append(self.link(p["src"], p["dst"],
                                 relation=p.get("relation", "ASSOCIATED")))
        return out

    def ingest(
        self,
        atoms: list[str],
        text: str | None = None,
        note_title: str | None = None,
        source: str = "AI",
        max_chars: int | None = None,
    ) -> dict[str, Any]:
        """**唯一写入入口**：把 AI 已拆分简写好的原子记忆批量落库。

        职责边界：拆分 / 简写 / 建连接全部由 AI 完成，本工具**只负责入库与权重**。
        - atoms：AI 重组后的原子（每条 1–MAX_LABEL_CHARS 字，AI 自己决定长度），
          保序去重后逐条写入（重复=强化）。库按字数给权重 W0=f(字数)。
        - text：可选。整段原文，存一条冷存记忆（note），标题用 note_title 或取原子首条。
        - 不建任何边——连接交给 AI 用 memory_link / memory_link_many。
        """
        from brainmem.core.tables import MAX_LABEL_CHARS
        if max_chars is None:
            max_chars = MAX_LABEL_CHARS
        if not atoms:
            raise TooLongError("atoms 为空：请至少给一条原子记忆")
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in atoms:
            s = textops.normalize(str(raw)).strip()
            s = textops.strip_edge_punct(s)          # 去掉首尾标点/符号
            if not s or not textops.has_meaningful_char(s):
                continue                              # 纯标点/空白/符号，跳过
            if len(s) > max_chars:
                raise TooLongError(
                    f"原子「{s}」{len(s)} 字超过 {max_chars} 字上限：请再简写（留可降级的内核）"
                )
            if s in seen:
                continue
            seen.add(s)
            cleaned.append(s)
        if not cleaned:
            raise TooLongError("atoms 清洗后为空（没有含实义字符的原子）")

        results = [self.write(t, source=source) for t in cleaned]
        note_res = None
        title = None
        if text and text.strip():
            title = (note_title or cleaned[0])[:max_chars]
            note_res = self.write_note(title, text.strip(), source=source)
            # 用 source_id 让每个原子"指向自己的原文 note"（不是建边，保持"不自动建边"契约）。
            # 这样合并原子时能顺着 source_id 找回原文，卷进父节点 → 可复原的长文本。
            with self.storage.transaction() as tx:
                for a in results:
                    n = tx.get_node(a["id"])
                    if n is not None:
                        tx.upsert_node(n.model_copy(update={"source_id": note_res["id"]}))
        return {
            "atoms": [{"text": t, "id": results[i]["id"],
                       "weight": results[i]["weight"], "state": results[i]["state"]}
                      for i, t in enumerate(cleaned)],
            "atom_count": len(cleaned),
            "note": ({"id": note_res["id"], "title": title, "saved": True}
                     if note_res else {"saved": False}),
            "hint": "已入库（未建边）。需要连接请用 memory_link / memory_link_many。",
        }

    # ---------------------------------------------------- 权重操作（库的全部职责）
    def reinforce(self, node_id: str, source: str = "AI") -> dict[str, Any]:
        """给一条记忆加权重（重复录入 / 回顾 / 有用反馈）。"""
        now = self.clock.now_day()
        with self.storage.transaction() as tx:
            node = tx.get_node(node_id)
            if node is None:
                raise NotFoundError(node_id)
            updated = self._reinforce(tx, node, now, "reinforce:explicit", source, None)
        return {"id": updated.id, "weight": show(updated.weight_bp),
                "state": updated.state.value}

    def simplify(self, node_id: str, new_text: str, source: str = "AI") -> dict[str, Any]:
        """把一条记忆替换为更简的写法并**加权重**——这是 AI"睡觉整理"的核心动作：
        记忆衰减变糊后，AI 把它压成更短的内核（如「六点钟起床差点迟到」→「差点迟到」），
        既保留了记忆、又通过再次录入把权重提回来。AI 自己决定简写到几个字（≤MAX_LABEL_CHARS）。"""
        t = (new_text or "").strip()
        from brainmem.core.tables import MAX_LABEL_CHARS
        if not (1 <= len(t) <= MAX_LABEL_CHARS):
            raise TooLongError(f"简写后需 1–{MAX_LABEL_CHARS} 字（当前 {len(t)} 字）")
        now = self.clock.now_day()
        with self.storage.transaction() as tx:
            node = tx.get_node(node_id)
            if node is None:
                raise NotFoundError(node_id)
            if textops.normalize(t) == node.label_norm:
                updated = self._reinforce(tx, node, now, "simplify:same", source, None)
                return {"id": updated.id, "label": updated.label,
                        "weight": show(updated.weight_bp), "state": updated.state.value,
                        "changed": False}
            updated = self._reinforce(tx, node, now, "simplify", source, None)
            updated = updated.model_copy(update={
                "label": t, "label_norm": textops.normalize(t), "char_len": len(t)})
            tx.upsert_node(updated)
            self._index_add(updated)
        return {"id": updated.id, "label": updated.label,
                "weight": show(updated.weight_bp), "state": updated.state.value,
                "changed": True}

    def _strong_cluster_ok(self, ids: list[str]) -> tuple[bool, dict[str, Any]]:
        """合并前置条件（计划书 6.3 + 用户要求）：
        待合并的记忆之间，必须由"足够强、且强到 1 年才遗忘"的连接连通：
        - 边权 ≥ merge_edge(8.00) 且 共激活 ≥ merge_coact(5)（计划书原门槛）；
        - 且该边自身寿命 ≥ merge_edge_min_days(365 天)（强到一年才遗忘）。
        否则不许合并。返回 (是否达标, 诊断信息)。"""
        from brainmem.core.edge import edge_days_to_zero

        idset = set(ids)
        min_edge_bp = int(self.p.merge_edge * BP)
        min_coact = self.p.merge_coact
        min_days = self.p.merge_edge_min_days
        internal = [e for e in self.storage.all_edges(self.tenant)
                    if e.src_id in idset and e.dst_id in idset]
        # 达标边 = 边权/共激活达标 且 自身能撑 ≥1 年
        strong = [e for e in internal
                  if e.weight_bp >= min_edge_bp and e.coactivation >= min_coact
                  and edge_days_to_zero(e.weight_bp, e.coactivation, self.p) >= min_days]
        # 用达标边做连通性判断：所有成员必须在一个连通分量里
        adj: dict[str, set[str]] = {i: set() for i in idset}
        for e in strong:
            adj[e.src_id].add(e.dst_id)
            adj[e.dst_id].add(e.src_id)
        seen: set[str] = set()
        if idset:
            stack = [next(iter(idset))]
            while stack:
                u = stack.pop()
                if u in seen:
                    continue
                seen.add(u)
                stack.extend(adj[u] - seen)
        connected = seen == idset and len(idset) >= 2 and len(strong) >= 1
        best = max(internal, key=lambda e: (e.weight_bp, e.coactivation), default=None)
        best_days = (0.0 if best is None else
                     edge_days_to_zero(best.weight_bp, best.coactivation, self.p))
        info = {
            "required": {"edge_weight": self.p.merge_edge, "coactivation": min_coact,
                         "self_life_days": min_days},
            "ok_edges": len(strong),
            "connected": connected,
            "current_best_edge": (None if best is None else
                                  {"edge_weight": round(best.weight_bp / BP, 2),
                                   "coactivation": best.coactivation,
                                   "self_life_days": round(best_days, 0)}),
        }
        return connected, info
    @staticmethod
    def _result(node: MemoryNode, *, created: bool, deduped: bool) -> dict[str, Any]:
        return {
            "id": node.id,
            "weight": show(node.weight_bp),
            "state": node.state.value,
            "created": created,
            "deduped": deduped,
        }

    def replay_events(self, node_id: str) -> int:
        return replay(self.storage.iter_events(node_id))
