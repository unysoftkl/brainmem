"""SQLite → PostgreSQL 迁移（阶段6，设计书 3.5 / 应用计划 6.5）。

三步：导出（按 seq 保序）→ 导入 PG → 按事件重建并 reconcile 对账（必须 0 误差）。
本模块的 pg 部分需要可达的 PG；export 部分可在任意环境跑（用于验证导出逻辑）。
"""
from __future__ import annotations

import json
from typing import Any


def export_sqlite(storage, tenant: str = "default") -> dict[str, Any]:
    """从 SQLite 导出全部数据为可导入的 JSON 结构（nodes/edges/events/versions）。"""
    nodes = [
        {
            "id": n.id, "tenant_id": n.tenant_id, "label": n.label, "label_norm": n.label_norm,
            "char_len": n.char_len, "kind": n.kind.value, "weight_bp": n.weight_bp,
            "stability": n.stability, "peak_bp": n.peak_bp, "state": n.state.value,
            "fidelity": n.fidelity, "gist": n.gist, "verbatim_ref": n.verbatim_ref,
            "fingerprint": n.fingerprint, "salience": n.salience, "born_at": n.born_at,
            "last_touch_at": n.last_touch_at, "source_kind": n.source_kind.value,
            "source_id": n.source_id, "deleted_at": n.deleted_at,
        }
        for n in storage.list_nodes(tenant)
    ]
    edges = [
        {
            "id": e.id, "tenant_id": e.tenant_id, "src_id": e.src_id, "dst_id": e.dst_id,
            "relation": e.relation.value, "weight_bp": e.weight_bp,
            "coactivation": e.coactivation, "state": e.state.value,
            "confidence": e.confidence, "provenance": e.provenance,
            "created_at": e.created_at, "last_touch_at": e.last_touch_at,
        }
        for e in storage.all_edges(tenant)
    ]
    events = []
    for n in nodes:
        for ev in storage.iter_events(n["id"]):
            events.append({
                "seq": ev.seq, "tenant_id": ev.tenant_id, "entity_kind": ev.entity_kind,
                "entity_id": ev.entity_id, "event_type": ev.event_type.value,
                "delta_bp": ev.delta_bp, "before_bp": ev.before_bp, "after_bp": ev.after_bp,
                "reason": ev.reason, "actor": ev.actor, "at_day": ev.at_day,
                "at_real": ev.at_real, "trace_id": ev.trace_id,
            })
    events.sort(key=lambda e: e["seq"])
    embeddings = storage.all_embeddings(tenant)
    return {"tenant": tenant, "nodes": nodes, "edges": edges, "events": events,
            "embeddings": {k: v for k, v in embeddings.items()}}


def write_export(data: dict[str, Any], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def import_postgres(dsn: str, data: dict[str, Any]) -> dict[str, Any]:
    """把 export 数据导入 PostgreSQL，并按事件重建权重后 reconcile。"""
    from brainmem.core.models import MemoryEdge, MemoryNode, WeightEvent
    from brainmem.core.enums import EventType, NodeKind, SourceKind, State, EdgeRelation, EdgeState
    from brainmem.storage.postgres.db import PostgresStorage

    pg = PostgresStorage(dsn)
    pg.init_schema()
    with pg.transaction() as tx:
        for n in data["nodes"]:
            tx.upsert_node(MemoryNode(
                id=n["id"], tenant_id=n["tenant_id"], label=n["label"], label_norm=n["label_norm"],
                char_len=n["char_len"], kind=NodeKind(n["kind"]), weight_bp=n["weight_bp"],
                stability=n["stability"], peak_bp=n["peak_bp"], state=State(n["state"]),
                fidelity=n["fidelity"], gist=n["gist"], verbatim_ref=n["verbatim_ref"],
                fingerprint=n["fingerprint"], salience=n["salience"], born_at=n["born_at"],
                last_touch_at=n["last_touch_at"], source_kind=SourceKind(n["source_kind"]),
                source_id=n["source_id"], deleted_at=n["deleted_at"]))
        for e in data["edges"]:
            tx.upsert_edge(MemoryEdge(
                id=e["id"], tenant_id=e["tenant_id"], src_id=e["src_id"], dst_id=e["dst_id"],
                relation=EdgeRelation(e["relation"]), weight_bp=e["weight_bp"],
                coactivation=e["coactivation"], state=EdgeState(e["state"]),
                confidence=e["confidence"], provenance=e["provenance"],
                created_at=e["created_at"], last_touch_at=e["last_touch_at"]))
        for e in data["events"]:
            tx.append_event(WeightEvent(
                tenant_id=e["tenant_id"], entity_kind=e["entity_kind"], entity_id=e["entity_id"],
                event_type=EventType(e["event_type"]), delta_bp=e["delta_bp"],
                before_bp=e["before_bp"], after_bp=e["after_bp"], reason=e["reason"],
                actor=e["actor"], at_day=e["at_day"], at_real=e["at_real"], trace_id=e["trace_id"]))
        for nid, vec in data.get("embeddings", {}).items():
            tx.upsert_embedding(nid, data["tenant"], vec)

    # 对账：PG 内事件重放 == 库内权重
    from brainmem.engine.events import replay
    checked = mismatched = 0
    for nid in pg.list_node_ids(data["tenant"]):
        node = pg.get_node(nid)
        if node is None:
            continue
        checked += 1
        if replay(pg.iter_events(nid), 0) != node.weight_bp:
            mismatched += 1
    pg.close()
    return {"imported_nodes": len(data["nodes"]), "imported_edges": len(data["edges"]),
            "imported_events": len(data["events"]), "checked": checked, "mismatched": mismatched}
