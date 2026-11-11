"""阶段6：监控指标。"""
from brainmem.core.time import FakeClock
from brainmem.interfaces.memory import Memory
from brainmem.services.monitoring import metrics


def test_metrics_snapshot():
    m = Memory.in_memory(FakeClock(1000.0))
    m.write("一二三")
    m.write("四五六")
    m.write("七八九")
    snap = metrics(m.engine)
    assert snap["nodes"] == 3
    assert snap["state_distribution"]
    assert 0 <= snap["weight_avg"] <= 20
    for k in ("weight_min", "weight_p50", "weight_p95", "weight_max"):
        assert k in snap
    m.close()
