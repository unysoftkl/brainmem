"""阶段5 验收（自动化）：ForgettingBench 关键阈值 + 检索延迟上界（小规模）。"""
from brainmem.core.time import FakeClock
from brainmem.interfaces.memory import Memory


def _uniq(i):
    return f"考{i:03d}"[:6]


def test_forgetting_bench_thresholds():
    clock = FakeClock(1000.0)
    m = Memory.in_memory(clock)
    imp = []
    for i in range(40):
        t = "要" + _uniq(i)
        imp.append((m.write(t)["id"], t))
    for i in range(60):
        m.write("次" + _uniq(i))
    for month in range(12):
        clock.advance_days(30)
        for (_, t) in imp:
            m.write(t)
    clock.advance_days(5)
    m.scan()
    recall = 0
    for (i, t) in imp:
        if m.storage.get_node(i) is None:
            continue
        if any(h["id"] == i for h in m.search(t, top_k=4, hops=1)):
            recall += 1
    assert recall / len(imp) >= 0.90
    m.close()


def test_multi_hop_recall():
    clock = FakeClock(1000.0)
    m = Memory.in_memory(clock)
    a = m.write("起点")["id"]
    b = m.write("中转")["id"]
    c = m.write("终点")["id"]
    for _ in range(5):
        m.link(a, b, "ASSOCIATED", weight=2.0)
        m.link(b, c, "ASSOCIATED", weight=2.0)
    hits = m.search("起点", top_k=4, hops=2)
    assert any(h["id"] == c for h in hits)
    m.close()
