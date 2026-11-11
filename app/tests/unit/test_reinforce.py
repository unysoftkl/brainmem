"""重复录入与强化（UC-06 ~ UC-07）。"""
from brainmem.core.decay import bp
from brainmem.core.params import DEFAULT_PARAMS as P
from brainmem.core.weights import reinforce


def test_uc06_repeat_outside_window_reinforces(mem, clock):
    r1 = mem.write("数学")  # 2 字，W0=7.00
    clock.advance_days(1)  # 超过 5 分钟窗口
    r2 = mem.write("数学")
    assert r2["created"] is False
    assert r2["deduped"] is False
    assert float(r2["weight"]) > 7.00
    assert mem.storage.get_node(r2["id"]).stability >= 1


def test_uc07_reinforce_monotonic_and_ceiling():
    wb, s, peak = bp(6.0), 0, bp(6.0)
    prev = wb
    for i in range(100):
        wb, s, peak, _ = reinforce(wb, s, peak, days_since=2.0, p=P)
        assert wb >= prev
        assert wb <= bp(20.0)
        assert s <= 24
        prev = wb
    assert wb > bp(15.0)  # 大量强化后接近上限
    assert s == 24
