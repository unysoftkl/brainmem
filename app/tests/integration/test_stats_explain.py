"""统计与解释（UC-20）。"""
from brainmem.core.decay import show


def test_uc20_stats(mem):
    mem.write("一二三")
    mem.write("四五六")
    mem.write("七八九")
    s = mem.stats()
    assert s["nodes"] == 3
    assert s["edges"] == 0
    assert sum(s["states"].values()) == 3


def test_uc20_explain(mem):
    r = mem.write("数学题")
    e = mem.explain(r["id"])
    assert e["id"] == r["id"]
    assert e["current_weight"] == mem.get(r["id"])["weight"]
    assert len(e["events"]) >= 1
    assert e["events"][0]["type"] == "CREATE"
    assert "归零" in e["decay_math"]
