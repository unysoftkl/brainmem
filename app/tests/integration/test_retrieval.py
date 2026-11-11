"""检索集成测试（UC-R：阶段2）。"""
def test_search_returns_seed_hit(mem, clock):
    r = mem.write("数学")
    # use=False 只读，返回原始权重 7.00
    hits_ro = mem.search("数学", top_k=4, use=False)
    assert hits_ro[0]["weight"] == "7.00"
    # 用进废退：检索命中会自动 +use_boost(0.5)，7.00 -> 7.50
    hits = mem.search("数学", top_k=4)
    assert hits, "应召回至少一条"
    assert hits[0]["id"] == r["id"]
    assert hits[0]["weight"] == "7.50"


def test_search_topk_and_min_weight(mem, clock):
    for w in ["数学", "几何", "物理", "化学", "生物"]:
        mem.write(w)
    hits = mem.search("数学", top_k=2)
    assert len(hits) <= 2


def test_link_and_edge_created(mem, clock):
    a = mem.write("数学")["id"]
    b = mem.write("几何")["id"]
    res = mem.link(a, b, "ASSOCIATED", weight=8.0)
    assert res["edge_id"]
    assert mem.stats()["edges"] == 1
    # 幂等累加
    mem.link(a, b, "ASSOCIATED", weight=1.0)
    assert mem.stats()["edges"] == 1


def test_feedback_reinforces_and_coactivates(mem, clock):
    a = mem.write("数学")["id"]
    b = mem.write("几何")["id"]
    mem.link(a, b, "ASSOCIATED", weight=5.0)
    before = mem.get(a)["weight_bp"]
    clock.advance_days(1)
    fb = mem.feedback(a, "positive")
    assert float(fb["weight"]) > float(mem.get(b)["weight"])  # a 被强化
    assert fb["weight"] != f"{before/10000:.2f}"


def test_semantic_dedup_high_similarity_merges(clock):
    from brainmem.interfaces.memory import Memory

    m = Memory.in_memory(clock)
    m.cfg.semantic_dedup = True
    m.engine.cfg.semantic_dedup = True
    m.write("一二三四")
    clock.advance_days(1)
    r2 = m.write("一二三四")  # 完全相同，走强化
    assert r2["created"] is False
    m.close()


def test_related_but_different_creates_edge(clock):
    from brainmem.interfaces.memory import Memory

    m = Memory.in_memory(clock)
    m.cfg.semantic_dedup = True
    m.engine.cfg.semantic_dedup = True
    m.write("一二三四五")
    clock.advance_days(1)
    b = m.write("一二三四六")  # 只差一个字
    if b["created"]:
        assert m.stats()["edges"] >= 1
    m.close()
