"""衰减解析解与速率单调（UC-08 ~ UC-11）。"""
from brainmem.core.decay import bp, days_to_zero, decay_bp, lambda_at
from brainmem.core.params import DEFAULT_PARAMS as P


def test_uc08_decay_90_days():
    """3 字节点 W0=6.00，S=0，90 天后 ≈ 3.67。"""
    wb = decay_bp(bp(6.0), 0, 90, P)
    assert abs(wb - bp(3.67)) < 200  # 误差 < 0.02


def test_uc09_rate_monotonic_decreasing():
    """越低掉越快：lambda(2.00) > lambda(8.00)。"""
    assert lambda_at(bp(2.0), 0, P) > lambda_at(bp(8.0), 0, P)


def test_uc10_days_to_zero_3char():
    """3 字节点归零 ≈ 173.1 天。"""
    assert abs(days_to_zero(bp(6.0), 0, P) - 173.1) < 0.5


def test_uc10_days_to_zero_various():
    """各字数寿命与标定表一致（抽样）。"""
    from brainmem.core.tables import initial_weight

    expected = {1: 260.8, 3: 173.1, 5: 132.4, 7: 94.6, 8: 60.6, 10: 10.1}
    for n, exp in expected.items():
        wb = bp(initial_weight(n))
        assert abs(days_to_zero(wb, 0, P) - exp) < 1.0, f"{n}字"


def test_uc11_read_does_not_advance(mem, clock):
    """连续 get 不推进 last_touch、不重置权重。"""
    r = mem.write("一二三")
    nid = r["id"]
    before = mem.storage.get_node(nid).last_touch_at
    clock.advance_days(10)
    for _ in range(10):
        mem.get(nid)
    after = mem.storage.get_node(nid).last_touch_at
    assert before == after  # 读不推进
    # 但惰性求值反映衰减
    assert float(mem.get(nid)["weight"]) < 6.0


def test_decay_monotonic_in_time():
    """无强化时 W(t2) <= W(t1)。"""
    prev = bp(10.0)
    for d in range(0, 400, 10):
        cur = decay_bp(bp(10.0), 0, d, P)
        assert cur <= prev
        prev = cur
