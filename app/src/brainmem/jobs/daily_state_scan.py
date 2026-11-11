"""后台任务：每日状态扫描与惰性结算（设计书 8.5 阶段3）。

只结算"会跨状态阈值"或"会归零"的节点，避免全表写事件导致事件流膨胀。
"""
from __future__ import annotations


def scan_and_settle(engine, day: float | None = None) -> dict:
    """扫描所有节点，对将跨阈值/归零者执行 settle。返回统计。"""
    from brainmem.core.decay import decay_bp
    from brainmem.core.lifecycle import state_of

    target = engine.clock.now_day() if day is None else day
    scanned = 0
    settled = 0
    deleted = 0
    transitions = 0
    for node in engine.storage.list_nodes(engine.tenant):
        scanned += 1
        proj = decay_bp(node.weight_bp, node.stability, target - node.last_touch_at, engine.p)
        if proj == 0 or state_of(proj) != node.state:
            before = node.state
            res = engine.settle(node.id, target)
            settled += 1
            if res.get("deleted"):
                deleted += 1
            if res.get("state") != before.value:
                transitions += 1
    return {"scanned": scanned, "settled": settled, "deleted": deleted,
            "transitions": transitions, "day": target}
