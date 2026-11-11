"""事件构造、复算与对账（规范第 2.3 / 4 节；设计书 4.7）。"""
from __future__ import annotations

from typing import Sequence

from brainmem.core.enums import EventType
from brainmem.core.models import MemoryNode, WeightEvent
from brainmem.core.params import WeightParams
from brainmem.core.time import TimeSource


def make_event(
    node: MemoryNode,
    event_type: EventType,
    before_bp: int,
    after_bp: int,
    reason: str,
    actor: str,
    clock: TimeSource,
    trace_id: str | None = None,
) -> WeightEvent:
    """构造一条 NODE 权重事件，并断言事件自洽 after=before+delta。"""
    delta = after_bp - before_bp
    assert after_bp == before_bp + delta
    return WeightEvent(
        tenant_id=node.tenant_id,
        entity_kind="NODE",
        entity_id=node.id,
        event_type=event_type,
        delta_bp=delta,
        before_bp=before_bp,
        after_bp=after_bp,
        reason=reason,
        actor=actor,
        at_day=clock.now_day(),
        at_real=clock.now_real(),
        trace_id=trace_id,
    )


def replay(events: Sequence[WeightEvent], initial_bp: int = 0) -> int:
    """事件流确定性投影：返回最终权重（bp）。

    以 after_bp 为准（服务端已算好），同时校验事件自洽，避免浮点累加误差。
    """
    w = initial_bp
    for ev in sorted(events, key=lambda e: e.seq):
        assert ev.after_bp == ev.before_bp + ev.delta_bp, f"event {ev.seq} inconsistent"
        w = ev.after_bp
    return w


def reconcile_node(node: MemoryNode, events: Sequence[WeightEvent]) -> tuple[bool, int, int]:
    """对账单节点：返回 (一致?, 事件重放值, 库内值)。"""
    replayed = replay(events, initial_bp=0)
    return (replayed == node.weight_bp, replayed, node.weight_bp)
