"""阶段6：SQLite→PG 导出一致性（export 逻辑可在无 PG 环境验证）。"""
from brainmem.core.time import FakeClock
from brainmem.engine.events import replay
from brainmem.interfaces.memory import Memory
from brainmem.storage.migrate import export_sqlite


def test_export_preserves_event_replay():
    clock = FakeClock(1000.0)
    m = Memory.in_memory(clock)
    a = m.write("数学")["id"]
    b = m.write("几何")["id"]
    m.link(a, b, "ASSOCIATED", weight=8.0)
    clock.advance_days(10)
    m.write("数学")  # 强化
    m.write_note("买书记录", "张三在北京市海淀区买了三本书")  # 带原文记忆

    data = export_sqlite(m.storage, "default")
    assert data["tenant"] == "default"
    assert len(data["nodes"]) == m.stats()["nodes"]
    assert len(data["edges"]) == m.stats()["edges"]
    # 事件按 seq 保序
    seqs = [e["seq"] for e in data["events"]]
    assert seqs == sorted(seqs)

    # 每个节点：导出事件重放 == 节点权重（迁移保真的关键校验）
    by_entity = {}
    for e in data["events"]:
        by_entity.setdefault(e["entity_id"], []).append(e)
    from brainmem.core.models import WeightEvent
    for n in data["nodes"]:
        from brainmem.core.enums import EventType
        evs = [WeightEvent(
            seq=e["seq"], tenant_id=e["tenant_id"], entity_kind=e["entity_kind"],
            entity_id=e["entity_id"], event_type=EventType(e["event_type"]),
            delta_bp=e["delta_bp"], before_bp=e["before_bp"], after_bp=e["after_bp"],
            reason=e["reason"], actor=e["actor"], at_day=e["at_day"], at_real=e["at_real"],
            trace_id=e["trace_id"]) for e in by_entity.get(n["id"], [])]
        assert replay(evs, 0) == n["weight_bp"], n["id"]
    m.close()


def test_export_embeddings_present():
    m = Memory.in_memory(FakeClock(1000.0))
    nid = m.write("数学")["id"]
    data = export_sqlite(m.storage, "default")
    assert nid in data["embeddings"]
    assert len(data["embeddings"][nid]) == 256
    m.close()
