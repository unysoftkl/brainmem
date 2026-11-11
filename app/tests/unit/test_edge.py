"""边权引擎（设计书 4.5）。"""
from brainmem.core.decay import bp
from brainmem.core.edge import edge_decay_bp, edge_instant_rate, edge_reinforce_bp
from brainmem.core.params import DEFAULT_PARAMS as P


def test_edge_reinforce_bounded_monotonic():
    eb, c = bp(1.0), 0
    prev = eb
    for _ in range(50):
        eb, c = edge_reinforce_bp(eb, c, P)
        assert eb >= prev
        assert eb <= bp(P.E_MAX)
        prev = eb
    assert c == 50
    assert eb <= bp(P.E_MAX)


def test_edge_rate_decreasing_in_weight():
    assert edge_instant_rate(bp(1.0), 0, P) > edge_instant_rate(bp(8.0), 0, P)


def test_edge_coactivation_slows_decay():
    # 同样权重，共激活多的衰减更慢
    lo = edge_decay_bp(bp(5.0), 0, 100, P)
    hi = edge_decay_bp(bp(5.0), 20, 100, P)
    assert hi >= lo


def test_edge_decay_monotonic_in_time():
    prev = bp(8.0)
    for d in range(0, 500, 25):
        cur = edge_decay_bp(bp(8.0), 0, d, P)
        assert cur <= prev
        prev = cur
