"""SQLite 存储实现（WAL + FTS5）。唯一碰数据库的地方。"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator, Sequence

from brainmem.core.models import MemoryEdge, MemoryNode, MemoryVersion, WeightEvent

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")


def _row_to_node(r: sqlite3.Row) -> MemoryNode:
    return MemoryNode(
        id=r["id"], tenant_id=r["tenant_id"], label=r["label"],
        label_norm=r["label_norm"], char_len=r["char_len"], kind=r["kind"],
        weight_bp=r["weight_bp"], stability=r["stability"], peak_bp=r["peak_bp"],
        state=r["state"], fidelity=r["fidelity"], gist=r["gist"],
        verbatim_ref=r["verbatim_ref"], fingerprint=r["fingerprint"],
        salience=r["salience"], born_at=r["born_at"], last_touch_at=r["last_touch_at"],
        source_kind=r["source_kind"], source_id=r["source_id"], deleted_at=r["deleted_at"],
    )


def _row_to_edge(r: sqlite3.Row) -> MemoryEdge:
    return MemoryEdge(
        id=r["id"], tenant_id=r["tenant_id"], src_id=r["src_id"], dst_id=r["dst_id"],
        relation=r["relation"], weight_bp=r["weight_bp"], coactivation=r["coactivation"],
        state=r["state"], confidence=r["confidence"], provenance=r["provenance"],
        created_at=r["created_at"], last_touch_at=r["last_touch_at"],
    )


def _row_to_event(r: sqlite3.Row) -> WeightEvent:
    return WeightEvent(
        seq=r["seq"], tenant_id=r["tenant_id"], entity_kind=r["entity_kind"],
        entity_id=r["entity_id"], event_type=r["event_type"], delta_bp=r["delta_bp"],
        before_bp=r["before_bp"], after_bp=r["after_bp"], reason=r["reason"],
        actor=r["actor"], at_day=r["at_day"], at_real=r["at_real"], trace_id=r["trace_id"],
    )


class SqliteStorage:
    def __init__(self, path: str = ":memory:"):
        self.path = path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        if path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")

    # ---------- schema ----------
    def init_schema(self) -> None:
        for name in ("001_init.sql", "002_embedding.sql", "003_merge.sql"):
            sql_path = os.path.join(MIGRATIONS_DIR, name)
            if os.path.exists(sql_path):
                with open(sql_path, encoding="utf-8") as f:
                    self._conn.executescript(f.read())
        self._migrate_wide_label()

    def _char_len_check_max(self) -> int | None:
        """读出 memory_node.char_len 的 CHECK 上限（1 AND N 里的 N），读不到返回 None。"""
        r = self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='memory_node'"
        ).fetchone()
        if not r or not r[0]:
            return None
        import re
        m = re.search(r"char_len\s+INTEGER[^,]*BETWEEN\s+1\s+AND\s+(\d+)", r[0], re.I)
        return int(m.group(1)) if m else None

    def _migrate_wide_label(self) -> None:
        """若 char_len 约束仍是 1..10，则重建表放宽到 1..100（幂等：已放宽则跳过）。"""
        cur = self._char_len_check_max()
        if cur is None or cur >= 100:
            return
        path = os.path.join(MIGRATIONS_DIR, "004_wide_label.sql")
        if not os.path.exists(path):
            return
        self._conn.execute("PRAGMA foreign_keys=OFF")
        try:
            with open(path, encoding="utf-8") as f:
                self._conn.executescript(f.read())
        finally:
            self._conn.execute("PRAGMA foreign_keys=ON")

    # ---------- transaction ----------
    @contextmanager
    def transaction(self) -> Iterator["SqliteStorage"]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self
                self._conn.execute("COMMIT")
            except Exception:
                self._conn.execute("ROLLBACK")
                raise

    # ---------- reads ----------
    def get_node(self, node_id: str) -> MemoryNode | None:
        r = self._conn.execute("SELECT * FROM memory_node WHERE id=?", (node_id,)).fetchone()
        return _row_to_node(r) if r else None

    def find_by_norm(self, tenant: str, label_norm: str) -> MemoryNode | None:
        r = self._conn.execute(
            "SELECT * FROM memory_node WHERE tenant_id=? AND label_norm=?",
            (tenant, label_norm),
        ).fetchone()
        return _row_to_node(r) if r else None

    def get_edge(self, src_id: str, dst_id: str, relation: str) -> MemoryEdge | None:
        r = self._conn.execute(
            "SELECT * FROM memory_edge WHERE src_id=? AND dst_id=? AND relation=?",
            (src_id, dst_id, relation),
        ).fetchone()
        return _row_to_edge(r) if r else None

    def neighbors(self, node_id: str, limit: int = 100) -> Sequence[MemoryEdge]:
        rows = self._conn.execute(
            "SELECT * FROM memory_edge WHERE src_id=? ORDER BY weight_bp DESC LIMIT ?",
            (node_id, limit),
        ).fetchall()
        return [_row_to_edge(r) for r in rows]

    def incident(self, node_id: str, limit: int = 200) -> Sequence[MemoryEdge]:
        rows = self._conn.execute(
            "SELECT * FROM memory_edge WHERE (src_id=? OR dst_id=?) AND state='ACTIVE' "
            "ORDER BY weight_bp DESC LIMIT ?",
            (node_id, node_id, limit),
        ).fetchall()
        return [_row_to_edge(r) for r in rows]

    def iter_events(self, entity_id: str) -> Sequence[WeightEvent]:
        rows = self._conn.execute(
            "SELECT * FROM weight_event WHERE entity_id=? ORDER BY seq ASC", (entity_id,)
        ).fetchall()
        return [_row_to_event(r) for r in rows]

    # ---------- writes ----------
    def upsert_node(self, node: MemoryNode) -> None:
        self._conn.execute(
            """INSERT INTO memory_node
            (id, tenant_id, label, label_norm, char_len, kind, weight_bp, stability,
             peak_bp, state, fidelity, gist, verbatim_ref, fingerprint, salience,
             born_at, last_touch_at, source_kind, source_id, deleted_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              tenant_id=excluded.tenant_id, label=excluded.label,
              label_norm=excluded.label_norm, char_len=excluded.char_len,
              kind=excluded.kind, weight_bp=excluded.weight_bp,
              stability=excluded.stability, peak_bp=excluded.peak_bp,
              state=excluded.state, fidelity=excluded.fidelity, gist=excluded.gist,
              verbatim_ref=excluded.verbatim_ref, fingerprint=excluded.fingerprint,
              salience=excluded.salience, born_at=excluded.born_at,
              last_touch_at=excluded.last_touch_at, source_kind=excluded.source_kind,
              source_id=excluded.source_id, deleted_at=excluded.deleted_at""",
            (
                node.id, node.tenant_id, node.label, node.label_norm, node.char_len,
                node.kind.value, node.weight_bp, node.stability, node.peak_bp,
                node.state.value, node.fidelity, node.gist, node.verbatim_ref,
                node.fingerprint, node.salience, node.born_at, node.last_touch_at,
                node.source_kind.value, node.source_id, node.deleted_at,
            ),
        )

    def delete_node(self, node_id: str) -> None:
        # 先删边与版本，再删节点（FTS 由触发器清理）
        self._conn.execute(
            "DELETE FROM memory_edge WHERE src_id=? OR dst_id=?", (node_id, node_id)
        )
        self._conn.execute("DELETE FROM memory_version WHERE node_id=?", (node_id,))
        self._conn.execute("DELETE FROM memory_embedding WHERE node_id=?", (node_id,))
        self._conn.execute("DELETE FROM memory_node WHERE id=?", (node_id,))

    def list_nodes(self, tenant: str) -> Sequence[MemoryNode]:
        rows = self._conn.execute(
            "SELECT * FROM memory_node WHERE tenant_id=?", (tenant,)
        ).fetchall()
        return [_row_to_node(r) for r in rows]

    # ---------- embeddings ----------
    def upsert_embedding(self, node_id: str, tenant: str, vec: Sequence[float]) -> None:
        import array

        blob = array.array("f", [float(x) for x in vec]).tobytes()
        self._conn.execute(
            "INSERT OR REPLACE INTO memory_embedding(node_id, tenant_id, dim, vector) VALUES (?,?,?,?)",
            (node_id, tenant, len(vec), blob),
        )

    def get_embedding(self, node_id: str) -> list[float] | None:
        import array

        r = self._conn.execute(
            "SELECT vector, dim FROM memory_embedding WHERE node_id=?", (node_id,)
        ).fetchone()
        if not r:
            return None
        arr = array.array("f")
        arr.frombytes(r["vector"])
        return list(arr)

    def all_embeddings(self, tenant: str) -> dict[str, list[float]]:
        import array

        rows = self._conn.execute(
            "SELECT node_id, vector FROM memory_embedding WHERE tenant_id=?", (tenant,)
        ).fetchall()
        out: dict[str, list[float]] = {}
        for r in rows:
            arr = array.array("f")
            arr.frombytes(r["vector"])
            out[r["node_id"]] = list(arr)
        return out

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO memory_edge
            (id, tenant_id, src_id, dst_id, relation, weight_bp, coactivation, state,
             confidence, provenance, created_at, last_touch_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                edge.id, edge.tenant_id, edge.src_id, edge.dst_id, edge.relation.value,
                edge.weight_bp, edge.coactivation, edge.state.value, edge.confidence,
                edge.provenance, edge.created_at, edge.last_touch_at,
            ),
        )

    def append_event(self, ev: WeightEvent) -> int:
        cur = self._conn.execute(
            """INSERT INTO weight_event
            (tenant_id, entity_kind, entity_id, event_type, delta_bp, before_bp,
             after_bp, reason, actor, at_day, at_real, trace_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                ev.tenant_id, ev.entity_kind, ev.entity_id, ev.event_type.value,
                ev.delta_bp, ev.before_bp, ev.after_bp, ev.reason, ev.actor,
                ev.at_day, ev.at_real, ev.trace_id,
            ),
        )
        return int(cur.lastrowid)

    def insert_events(self, events: Sequence[WeightEvent]) -> int:
        rows = [
            (e.tenant_id, e.entity_kind, e.entity_id, e.event_type.value, e.delta_bp,
             e.before_bp, e.after_bp, e.reason, e.actor, e.at_day, e.at_real, e.trace_id)
            for e in events
        ]
        self._conn.executemany(
            """INSERT INTO weight_event
            (tenant_id, entity_kind, entity_id, event_type, delta_bp, before_bp,
             after_bp, reason, actor, at_day, at_real, trace_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        return len(rows)

    def insert_version(self, v: MemoryVersion) -> None:
        self._conn.execute(
            """INSERT INTO memory_version
            (id, node_id, version_no, gist, verbatim_ref, diff, created_at, created_by, reason)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (v.id, v.node_id, v.version_no, v.gist, v.verbatim_ref, v.diff,
             v.created_at, v.created_by, v.reason),
        )

    def list_versions(self, node_id: str) -> Sequence[MemoryVersion]:
        rows = self._conn.execute(
            "SELECT * FROM memory_version WHERE node_id=? ORDER BY version_no ASC",
            (node_id,),
        ).fetchall()
        return [
            MemoryVersion(
                id=r["id"], node_id=r["node_id"], version_no=r["version_no"],
                gist=r["gist"], verbatim_ref=r["verbatim_ref"], diff=r["diff"],
                created_at=r["created_at"], created_by=r["created_by"], reason=r["reason"],
            )
            for r in rows
        ]

    # ---------- stats ----------
    def count_nodes(self, tenant: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM memory_node WHERE tenant_id=?", (tenant,)
        ).fetchone()[0]

    def count_edges(self, tenant: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM memory_edge WHERE tenant_id=?", (tenant,)
        ).fetchone()[0]

    def count_events(self, tenant: str) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM weight_event WHERE tenant_id=?", (tenant,)
        ).fetchone()[0]

    def avg_weight_bp(self, tenant: str) -> float:
        v = self._conn.execute(
            "SELECT AVG(weight_bp) FROM memory_node WHERE tenant_id=?", (tenant,)
        ).fetchone()[0]
        return float(v or 0.0)

    def state_distribution(self, tenant: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT state, COUNT(*) c FROM memory_node WHERE tenant_id=? GROUP BY state",
            (tenant,),
        ).fetchall()
        return {r["state"]: r["c"] for r in rows}

    def list_node_ids(self, tenant: str) -> Sequence[str]:
        rows = self._conn.execute(
            "SELECT id FROM memory_node WHERE tenant_id=?", (tenant,)
        ).fetchall()
        return [r["id"] for r in rows]

    def all_edges(self, tenant: str) -> Sequence[MemoryEdge]:
        rows = self._conn.execute(
            "SELECT * FROM memory_edge WHERE tenant_id=? AND state='ACTIVE'", (tenant,)
        ).fetchall()
        return [_row_to_edge(r) for r in rows]

    # ---------- 合并快照 ----------
    def save_merge_snapshot(self, batch_id: str, parent_id: str,
                            members: Sequence[tuple[str, int]], created_at: float) -> None:
        self._conn.executemany(
            "INSERT OR REPLACE INTO merge_snapshot(batch_id, parent_id, member_id, old_weight_bp, created_at) "
            "VALUES (?,?,?,?,?)",
            [(batch_id, parent_id, mid, wb, created_at) for mid, wb in members],
        )

    def get_merge_snapshot(self, batch_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT batch_id, parent_id, member_id, old_weight_bp FROM merge_snapshot WHERE batch_id=?",
            (batch_id,),
        ).fetchall()
        return [{"parent_id": r["parent_id"], "member_id": r["member_id"],
                 "old_weight_bp": r["old_weight_bp"]} for r in rows]

    def delete_merge_snapshot(self, batch_id: str) -> None:
        self._conn.execute("DELETE FROM merge_snapshot WHERE batch_id=?", (batch_id,))

    # ---------- 巩固批次 ----------
    def insert_consolidation_run(self, run) -> None:
        self._conn.execute(
            "INSERT INTO consolidation_run(id, run_type, started_at, finished_at, sampled, changed, params, report) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (run.id, run.run_type, run.started_at, run.finished_at,
             run.sampled, run.changed, run.params, run.report),
        )

    def close(self) -> None:
        self._conn.close()
