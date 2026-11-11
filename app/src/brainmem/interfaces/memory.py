"""Memory 门面：对外统一入口。CLI / SDK / 未来 MCP 都通过它调用引擎。"""
from __future__ import annotations

from typing import Any

from brainmem.config import Config, load_config
from brainmem.engine.memory_engine import MemoryEngine
from brainmem.storage.base import Storage
from brainmem.storage.factory import make_storage


class Memory:
    def __init__(self, cfg: Config, storage: Storage, engine: MemoryEngine | None = None):
        self.cfg = cfg
        self.storage = storage
        self.engine = engine or MemoryEngine(cfg, storage)

    # ---- 构造 ----
    @classmethod
    def from_config(cls, path: str | None = None) -> "Memory":
        cfg = load_config(path)
        return cls(cfg, make_storage(cfg))

    @classmethod
    def in_memory(cls, clock: Any | None = None) -> "Memory":
        """内存库（测试 / 演示）。"""
        from brainmem.storage.sqlite.db import SqliteStorage

        cfg = load_config(None)
        cfg.sqlite_path = ":memory:"
        st = SqliteStorage(":memory:")
        st.init_schema()
        return cls(cfg, st, MemoryEngine(cfg, st, clock))

    # ---- 业务 ----
    def write(self, text: str, **kw: Any) -> dict[str, Any]:
        return self.engine.write(text, **kw)

    def write_note(self, title: str, content: str, **kw: Any) -> dict[str, Any]:
        return self.engine.write_note(title, content, **kw)

    def ingest(self, atoms: list[str], text: str | None = None,
               note_title: str | None = None, source: str = "AI",
               max_chars: int | None = None) -> dict[str, Any]:
        """唯一写入入口：AI 拆分简写好的原子批量入库（不建边）。"""
        return self.engine.ingest(atoms, text=text, note_title=note_title,
                                  source=source, max_chars=max_chars)

    def reinforce(self, node_id: str, source: str = "AI") -> dict[str, Any]:
        return self.engine.reinforce(node_id, source=source)

    def simplify(self, node_id: str, new_text: str, source: str = "AI") -> dict[str, Any]:
        return self.engine.simplify(node_id, new_text, source=source)

    def merge(self, node_ids: list[str], new_text: str, source: str = "AI",
              mode: str = "soft") -> dict[str, Any]:
        """合并记忆（**软合并**）：新建父记忆(标题=new_text)，成员全保留、原文汇总进父节点、
        可展开可回滚。mode 仅为兼容旧调用保留；传其它值会报错（硬合并已移除）。"""
        if mode != "soft":
            raise ValueError("仅支持软合并（mode='soft'）；硬合并已移除（它会丢原文/删成员）。")
        return self._consolidator().merge_soft(node_ids, new_text, source=source)

    def write_batch(self, items: list[str], **kw: Any) -> list[dict[str, Any]]:
        return [self.engine.write(t, **kw) for t in items]

    def get(self, node_id: str, include_verbatim: bool = False) -> dict[str, Any]:
        return self.engine.get(node_id, include_verbatim)

    def forget(self, node_id: str, mode: str = "hard") -> dict[str, Any]:
        return self.engine.forget(node_id, mode)

    def settle(self, node_id: str, day: float | None = None) -> dict[str, Any]:
        return self.engine.settle(node_id, day)

    def sweep_expired(self, dry_run: bool = True) -> dict[str, Any]:
        """归零清理：只物理删除"权重已归零"的记忆（连边、清冷存）。dry_run 默认只列清单。"""
        return self.engine.sweep_expired(dry_run=dry_run)

    def stats(self, tenant: str | None = None) -> dict[str, Any]:
        return self.engine.stats(tenant)

    def explain(self, node_id: str) -> dict[str, Any]:
        return self.engine.explain(node_id)

    def inspect(self, node_id: str) -> dict[str, Any]:
        """一条记忆的全部数据 + 所有关联边。"""
        return self.engine.inspect(node_id)

    def list_nodes(self, tenant: str | None = None) -> list[dict[str, Any]]:
        """列出全部记忆的关键字段（含权重/状态/连接数）。"""
        return self.engine.overview(tenant)

    def reconcile(self, sample_ratio: float = 1.0) -> dict[str, Any]:
        return self.engine.reconcile(sample_ratio)

    def search(self, query: str, top_k: int = 4, hops: int = 2,
               min_weight: float = 0.0, use: bool = True) -> list[dict[str, Any]]:
        return self.engine.search(query, top_k, hops, min_weight, use=use)

    def feedback(self, node_id: str, signal: str = "positive", context: str = "") -> dict[str, Any]:
        return self.engine.feedback(node_id, signal, context)

    def link(self, src: str, dst: str, relation: str = "ASSOCIATED",
             weight: float | None = None) -> dict[str, Any]:
        return self.engine.link(src, dst, relation, weight)

    def link_many(self, pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.engine.link_many(pairs)

    def scan(self, day: float | None = None) -> dict[str, Any]:
        """每日状态扫描与惰性结算（阶段3）。"""
        from brainmem.jobs.daily_state_scan import scan_and_settle

        return scan_and_settle(self.engine, day)

    # ---- 阶段4：巩固/合并 ----
    def _consolidator(self):
        from brainmem.engine.consolidation import Consolidator

        return Consolidator(self.engine)

    def consolidate(self, weekly: bool = False, batch_id: str | None = None,
                    min_edge_bp: float | None = None, min_coact: int | None = None) -> dict[str, Any]:
        return self._consolidator().run_nightly(
            batch_id=batch_id, weekly=weekly, min_edge_bp=min_edge_bp, min_coact=min_coact)

    def merge_undo(self, batch_id: str) -> dict[str, Any]:
        return self._consolidator().merge_undo(batch_id)

    # 注：原 `normalize`（全局乘性归一）已随 global_normalize 一并移除。

    def close(self) -> None:
        self.storage.close()
