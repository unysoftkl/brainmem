"""检索引擎：种子召回 → 扩散激活 → 多因子重排 → 工作记忆装填（设计书 5.4）。

检索本身只读；强化由 memory_feedback 单独触发（召回≠使用，5.4.2）。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from brainmem.config import Config
from brainmem.core.decay import BP, decay_bp, show
from brainmem.core.ids import new_id
from brainmem.core.lifecycle import state_of
from brainmem.core.models import MemoryEdge
from brainmem.services import similarity as sim
from brainmem.services.embedder import EmbeddingProvider
from brainmem.services.graph import spreading_activation
from brainmem.storage.base import Storage
from brainmem.core.time import TimeSource

# 重排默认权重（设计书 5.4.1）
ALPHA, BETA, GAMMA, DELTA, EPS = 0.35, 0.20, 0.25, 0.10, 0.10


@dataclass
class Hit:
    id: str
    label: str
    gist: str | None
    weight: float
    state: str
    score: float
    via: str  # seed / spread

    def to_dict(self) -> dict:
        return {
            "id": self.id, "label": self.label, "gist": self.gist,
            "weight": self.weight, "state": self.state,
            "score": round(self.score, 4), "via": self.via,
        }


class Retriever:
    def __init__(self, cfg: Config, storage: Storage, clock: TimeSource,
                 embedder: EmbeddingProvider):
        self.cfg = cfg
        self.storage = storage
        self.clock = clock
        self.embedder = embedder
        self.p = cfg.params()
        self.tenant = cfg.tenant

    def _seed_recall(self, qvec: list[float], k: int = 50) -> dict[str, float]:
        embs = self.storage.all_embeddings(self.tenant)
        if not embs:
            return {}
        q = np.asarray(qvec, dtype=np.float32)
        scores = []
        for nid, vec in embs.items():
            s = sim.cosine(qvec, vec)
            if s > 0:
                scores.append((nid, s))
        scores.sort(key=lambda x: x[1], reverse=True)
        return dict(scores[:k])

    def search(self, query: str, top_k: int = 4, hops: int = 2,
               min_weight: float = 0.0) -> list[Hit]:
        qvec = self.embedder.encode(query)
        seeds = self._seed_recall(qvec, k=50)
        if not seeds:
            return []
        act = spreading_activation(self.storage, seeds, hops=hops, gamma=0.55)
        now = self.clock.now_day()
        max_act = max(act.values()) or 1.0
        hits: list[Hit] = []
        for nid, a in act.items():
            node = self.storage.get_node(nid)
            if node is None:
                continue
            w_now = decay_bp(node.weight_bp, node.stability, now - node.last_touch_at, self.p)
            if w_now < int(min_weight * BP):
                continue
            s = sim.cosine(qvec, self.storage.get_embedding(nid) or [0.0] * self.embedder.dim)
            recency = 1.0 / (1.0 + (now - node.last_touch_at) / 30.0)
            source_prior = 1.0 if node.source_kind.value == "HUMAN" else 0.8
            score = (ALPHA * s + BETA * (w_now / BP) / self.p.W_MAX
                     + GAMMA * (a / max_act) + DELTA * recency + EPS * source_prior)
            via = "seed" if nid in seeds else "spread"
            hits.append(Hit(
                id=nid, label=node.label, gist=node.gist,
                weight=show(w_now), state=state_of(w_now).value,
                score=score, via=via,
            ))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def reinforce_edge(self, tx: Storage, src: str, dst: str, relation: str = "ASSOCIATED") -> None:
        """检索/写入共激活：增强或新建边。"""
        from brainmem.core.edge import edge_reinforce_bp

        now = self.clock.now_day()
        e = tx.get_edge(src, dst, relation)
        if e is None:
            e2 = MemoryEdge(
                id=new_id(), tenant_id=self.tenant, src_id=src, dst_id=dst,
                relation=relation, weight_bp=BP // 2, coactivation=0,
                created_at=now, last_touch_at=now,
            )
            tx.upsert_edge(e2)
            e = e2
        new_w, new_c = edge_reinforce_bp(e.weight_bp, e.coactivation, self.p)
        tx.upsert_edge(e.model_copy(update={"weight_bp": new_w, "coactivation": new_c,
                                            "last_touch_at": now}))
