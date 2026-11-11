"""PostgreSQL + pgvector 存储实现（阶段6）。

与 SQLite 实现同一套 Storage 方法；向量列 `embedding vector(256)`，用 pgvector
`<=>`（余弦距离）召回。生产部署建议：分区表已按 tenant 哈希分 4 区、HNSW 索引。

连接串：`BRAINMEM_PG_DSN=postgresql://user:pw@host:5432/db`
（本环境无 PG 服务，故本模块的端到端运行需在具备 PostgreSQL 16 + pgvector 的机器上验证；
SQL/接口已与 SQLite 对齐，契约测试可对双实现复用。）
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator, Sequence

from brainmem.core.models import MemoryEdge, MemoryNode, MemoryVersion, WeightEvent

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def _row_to_node(r) -> MemoryNode:
    return MemoryNode(
        id=r["id"], tenant_id=r["tenant_id"], label=r["label"], label_norm=r["label_norm"],
        char_len=r["char_len"], kind=r["kind"], weight_bp=r["weight_bp"],
        stability=r["stability"], peak_bp=r["peak_bp"], state=r["state"],
        fidelity=r["fidelity"], gist=r["gist"], verbatim_ref=r["verbatim_ref"],
        fingerprint=r["fingerprint"], salience=r["salience"], born_at=r["born_at"],
        last_touch_at=r["last_touch_at"], source_kind=r["source_kind"],
        source_id=r["source_id"], deleted_at=r["deleted_at"],
    )


def _row_to_edge(r) -> MemoryEdge:
    return MemoryEdge(
        id=r["id"], tenant_id=r["tenant_id"], src_id=r["src_id"], dst_id=r["dst_id"],
        relation=r["relation"], weight_bp=r["weight_bp"], coactivation=r["coactivation"],
        state=r["state"], confidence=r["confidence"], provenance=r["provenance"],
        created_at=r["created_at"], last_touch_at=r["last_touch_at"],
    )


def _row_to_event(r) -> WeightEvent:
    return WeightEvent(
        seq=r["seq"], tenant_id=r["tenant_id"], entity_kind=r["entity_kind"],
        entity_id=r["entity_id"], event_type=r["event_type"], delta_bp=r["delta_bp"],
        before_bp=r["before_bp"], after_bp=r["after_bp"], reason=r["reason"],
        actor=r["actor"], at_day=r["at_day"], at_real=r["at_real"], trace_id=r["trace_id"],
    )


class PostgresStorage:
    def __init__(self, dsn: str | None = None):
        import psycopg
        from psycopg.rows import dict_row

        self.dsn = dsn or os.environ["BRAINMEM_PG_DSN"]
        self._conn = psycopg.connect(self.dsn, row_factory=dict_row, autocommit=True)

    # ---------- schema ----------
    def init_schema(self) -> None:
        with open(_SCHEMA_PATH, encoding="utf-8") as f:
            sql = f.read()
        with self._conn.cursor() as cur:
            cur.execute(sql)

    # ---------- transaction ----------
    @contextmanager
    def transaction(self) -> Iterator["PostgresStorage"]:
        with self._conn.transaction():
            yield self

    def _exec(self, sql: str, params: tuple = ()):  # noqa: ANN001
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur

    # ---------- reads ----------
    def get_node(self, node_id: str) -> MemoryNode | None:
        r = self._exec("SELECT * FROM memory_node WHERE id=%s LIMIT 1", (node_id,)).fetchone()
        return _row_to_node(r) if r else None

    def find_by_norm(self, tenant: str, label_norm: str) -> MemoryNode | None:
        r = self._exec(
            "SELECT * FROM memory_node WHERE tenant_id=%s AND label_norm=%s LIMIT 1",
            (tenant, label_norm)).fetchone()
        return _row_to_node(r) if r else None

    def list_nodes(self, tenant: str) -> Sequence[MemoryNode]:
        rows = self._exec("SELECT * FROM memory_node WHERE tenant_id=%s", (tenant,)).fetchall()
        return [_row_to_node(r) for r in rows]

    def list_node_ids(self, tenant: str) -> Sequence[str]:
        rows = self._exec("SELECT id FROM memory_node WHERE tenant_id=%s", (tenant,)).fetchall()
        return [r["id"] for r in rows]

    def get_edge(self, src_id: str, dst_id: str, relation: str) -> MemoryEdge | None:
        r = self._exec(
            "SELECT * FROM memory_edge WHERE src_id=%s AND dst_id=%s AND relation=%s LIMIT 1",
            (src_id, dst_id, relation)).fetchone()
        return _row_to_edge(r) if r else None

    def neighbors(self, node_id: str, limit: int = 100) -> Sequence[MemoryEdge]:
        rows = self._exec(
            "SELECT * FROM memory_edge WHERE src_id=%s ORDER BY weight_bp DESC LIMIT %s",
            (node_id, limit)).fetchall()
        return [_row_to_edge(r) for r in rows]

    def incident(self, node_id: str, limit: int = 200) -> Sequence[MemoryEdge]:
        rows = self._exec(
            "SELECT * FROM memory_edge WHERE (src_id=%s OR dst_id=%s) AND state='ACTIVE' "
            "ORDER BY weight_bp DESC LIMIT %s", (node_id, node_id, limit)).fetchall()
        return [_row_to_edge(r) for r in rows]

    def all_edges(self, tenant: str) -> Sequence[MemoryEdge]:
        rows = self._exec(
            "SELECT * FROM memory_edge WHERE tenant_id=%s AND state='ACTIVE'", (tenant,)).fetchall()
        return [_row_to_edge(r) for r in rows]

    def iter_events(self, entity_id: str) -> Sequence[WeightEvent]:
        rows = self._exec(
            "SELECT * FROM weight_event WHERE entity_id=%s ORDER BY seq ASC", (entity_id,)).fetchall()
        return [_row_to_event(r) for r in rows]

    # ---------- writes ----------
    def upsert_node(self, node: MemoryNode) -> None:
        self._exec(
            """INSERT INTO memory_node
            (id, tenant_id, label, label_norm, char_len, kind, weight_bp, stability, peak_bp,
             state, fidelity, gist, verbatim_ref, fingerprint, salience, born_at, last_touch_at,
             source_kind, source_id, deleted_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (id, tenant_id) DO UPDATE SET
              label=EXCLUDED.label, label_norm=EXCLUDED.label_norm, char_len=EXCLUDED.char_len,
              kind=EXCLUDED.kind, weight_bp=EXCLUDED.weight_bp, stability=EXCLUDED.stability,
              peak_bp=EXCLUDED.peak_bp, state=EXCLUDED.state, fidelity=EXCLUDED.fidelity,
              gist=EXCLUDED.gist, verbatim_ref=EXCLUDED.verbatim_ref,
              fingerprint=EXCLUDED.fingerprint, salience=EXCLUDED.salience,
              born_at=EXCLUDED.born_at, last_touch_at=EXCLUDED.last_touch_at,
              source_kind=EXCLUDED.source_kind, source_id=EXCLUDED.source_id,
              deleted_at=EXCLUDED.deleted_at""",
            (node.id, node.tenant_id, node.label, node.label_norm, node.char_len, node.kind.value,
             node.weight_bp, node.stability, node.peak_bp, node.state.value, node.fidelity,
             node.gist, node.verbatim_ref, node.fingerprint, node.salience, node.born_at,
             node.last_touch_at, node.source_kind.value, node.source_id, node.deleted_at),
        )

    def delete_node(self, node_id: str) -> None:
        self._exec("DELETE FROM memory_edge WHERE src_id=%s OR dst_id=%s", (node_id, node_id))
        self._exec("DELETE FROM memory_version WHERE node_id=%s", (node_id,))
        self._exec("DELETE FROM memory_node WHERE id=%s", (node_id,))

    def upsert_edge(self, edge: MemoryEdge) -> None:
        self._exec(
            """INSERT INTO memory_edge
            (id, tenant_id, src_id, dst_id, relation, weight_bp, coactivation, state, confidence,
             provenance, created_at, last_touch_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (tenant_id, src_id, dst_id, relation) DO UPDATE SET
              weight_bp=EXCLUDED.weight_bp, coactivation=EXCLUDED.coactivation,
              state=EXCLUDED.state, confidence=EXCLUDED.confidence,
              provenance=EXCLUDED.provenance, last_touch_at=EXCLUDED.last_touch_at""",
            (edge.id, edge.tenant_id, edge.src_id, edge.dst_id, edge.relation.value,
             edge.weight_bp, edge.coactivation, edge.state.value, edge.confidence,
             edge.provenance, edge.created_at, edge.last_touch_at),
        )

    def append_event(self, ev: WeightEvent) -> int:
        cur = self._exec(
            """INSERT INTO weight_event
            (tenant_id, entity_kind, entity_id, event_type, delta_bp, before_bp, after_bp,
             reason, actor, at_day, at_real, trace_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING seq""",
            (ev.tenant_id, ev.entity_kind, ev.entity_id, ev.event_type.value, ev.delta_bp,
             ev.before_bp, ev.after_bp, ev.reason, ev.actor, ev.at_day, ev.at_real, ev.trace_id),
        )
        return int(cur.fetchone()["seq"])

    def insert_events(self, events: Sequence[WeightEvent]) -> int:
        for e in events:
            self.append_event(e)
        return len(events)

    def insert_version(self, v: MemoryVersion) -> None:
        self._exec(
            "INSERT INTO memory_version(id,node_id,version_no,gist,verbatim_ref,diff,created_at,created_by,reason) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (v.id, v.node_id, v.version_no, v.gist, v.verbatim_ref, v.diff,
             v.created_at, v.created_by, v.reason),
        )

    def list_versions(self, node_id: str) -> Sequence[MemoryVersion]:
        rows = self._exec(
            "SELECT * FROM memory_version WHERE node_id=%s ORDER BY version_no ASC", (node_id,)).fetchall()
        return [MemoryVersion(id=r["id"], node_id=r["node_id"], version_no=r["version_no"],
                              gist=r["gist"], verbatim_ref=r["verbatim_ref"], diff=r["diff"],
                              created_at=r["created_at"], created_by=r["created_by"],
                              reason=r["reason"]) for r in rows]

    # ---------- embeddings（pgvector）----------
    def upsert_embedding(self, node_id: str, tenant: str, vec: Sequence[float]) -> None:
        self._exec("UPDATE memory_node SET embedding=%s::vector WHERE id=%s",
                   (_vec_literal(vec), node_id))

    def get_embedding(self, node_id: str) -> list[float] | None:
        r = self._exec("SELECT embedding FROM memory_node WHERE id=%s LIMIT 1", (node_id,)).fetchone()
        if not r or r["embedding"] is None:
            return None
        return [float(x) for x in str(r["embedding"]).strip("[]").split(",")]

    def all_embeddings(self, tenant: str) -> dict[str, list[float]]:
        rows = self._exec(
            "SELECT id, embedding FROM memory_node WHERE tenant_id=%s AND embedding IS NOT NULL",
            (tenant,)).fetchall()
        out = {}
        for r in rows:
            out[r["id"]] = [float(x) for x in str(r["embedding"]).strip("[]").split(",")]
        return out

    def vector_search(self, tenant: str, vec: Sequence[float], k: int = 50) -> list[tuple[str, float]]:
        """pgvector 余弦召回（1 - 余弦距离 = 相似度）。"""
        rows = self._exec(
            "SELECT id, 1 - (embedding <=> %s::vector) AS sim FROM memory_node "
            "WHERE tenant_id=%s AND embedding IS NOT NULL ORDER BY embedding <=> %s::vector LIMIT %s",
            (_vec_literal(vec), tenant, _vec_literal(vec), k)).fetchall()
        return [(r["id"], float(r["sim"])) for r in rows]

    # ---------- merge snapshot / consolidation ----------
    def save_merge_snapshot(self, batch_id: str, parent_id: str,
                            members: Sequence[tuple[str, int]], created_at: float) -> None:
        for mid, wb in members:
            self._exec(
                "INSERT INTO merge_snapshot(batch_id,parent_id,member_id,old_weight_bp,created_at) "
                "VALUES (%s,%s,%s,%s,%s) ON CONFLICT (batch_id,parent_id,member_id) DO UPDATE "
                "SET old_weight_bp=EXCLUDED.old_weight_bp",
                (batch_id, parent_id, mid, wb, created_at))

    def get_merge_snapshot(self, batch_id: str) -> list[dict]:
        rows = self._exec(
            "SELECT batch_id,parent_id,member_id,old_weight_bp FROM merge_snapshot WHERE batch_id=%s",
            (batch_id,)).fetchall()
        return [{"parent_id": r["parent_id"], "member_id": r["member_id"],
                 "old_weight_bp": r["old_weight_bp"]} for r in rows]

    def insert_consolidation_run(self, run) -> None:
        self._exec(
            "INSERT INTO consolidation_run(id,run_type,started_at,finished_at,sampled,changed,params,report) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            (run.id, run.run_type, run.started_at, run.finished_at, run.sampled,
             run.changed, run.params, run.report))

    # ---------- stats ----------
    def count_nodes(self, tenant: str) -> int:
        return int(self._exec("SELECT COUNT(*) c FROM memory_node WHERE tenant_id=%s",
                              (tenant,)).fetchone()["c"])

    def count_edges(self, tenant: str) -> int:
        return int(self._exec("SELECT COUNT(*) c FROM memory_edge WHERE tenant_id=%s",
                              (tenant,)).fetchone()["c"])

    def count_events(self, tenant: str) -> int:
        return int(self._exec("SELECT COUNT(*) c FROM weight_event WHERE tenant_id=%s",
                              (tenant,)).fetchone()["c"])

    def avg_weight_bp(self, tenant: str) -> float:
        v = self._exec("SELECT AVG(weight_bp) a FROM memory_node WHERE tenant_id=%s",
                       (tenant,)).fetchone()["a"]
        return float(v or 0.0)

    def state_distribution(self, tenant: str) -> dict[str, int]:
        rows = self._exec(
            "SELECT state, COUNT(*) c FROM memory_node WHERE tenant_id=%s GROUP BY state",
            (tenant,)).fetchall()
        return {r["state"]: r["c"] for r in rows}

    def close(self) -> None:
        self._conn.close()


def _vec_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"
