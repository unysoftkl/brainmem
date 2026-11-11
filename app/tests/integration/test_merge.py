"""合并与巩固（阶段4 集成测试）。

注：`global_normalize`（全局乘性归一）已被移除——它会把所有记忆等比例放大、
复活本该遗忘的条目，属于工程兜底而非仿脑机制，违背"用进废退"设计。
因此本文件不再测试 normalize。
"""
from brainmem.core.decay import bp


def _make_cluster(mem, base="数", n=4):
    """建一簇强连接记忆（不同字避免语义合并；两两连边并共激活 5 次）。"""
    ids = [mem.write(f"{base}{ch}") for ch in "加减乘除"[:n]]
    ids = [r if isinstance(r, str) else r["id"] for r in ids]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            for _ in range(5):  # 共激活 5 次，达到合并阈值
                mem.link(ids[i], ids[j], "ASSOCIATED", weight=1.8)
    return ids


def test_merge_creates_parent_and_members_kept(mem, clock):
    ids = _make_cluster(mem, n=4)
    res = mem.consolidate()
    assert res["changed"] >= 1
    merges = res["merges"]
    assert merges, "应发生至少一次合并"
    parent_id = merges[0]["parent_id"]
    pnode = mem.storage.get_node(parent_id)
    assert pnode is not None and pnode.kind.value == "ABSTRACT"
    # 成员全部保留
    for mid in ids:
        assert mem.storage.get_node(mid) is not None
    # 父节点权重 > 任一成员
    pw = pnode.weight_bp
    mws = [mem.storage.get_node(mid).weight_bp for mid in ids]
    assert pw > max(mws)


def test_merge_undo_restores_weights(mem, clock):
    ids = _make_cluster(mem, n=3)
    before = {mid: mem.storage.get_node(mid).weight_bp for mid in ids}
    res = mem.consolidate()
    batch = res["batch_id"]
    if not res["merges"]:
        return
    undo = mem.merge_undo(batch)
    assert undo["undone"] >= 1
    for mid in ids:
        assert mem.storage.get_node(mid).weight_bp == before[mid], "回滚后权重应恢复原值"


def test_consolidation_run_recorded(mem, clock):
    _make_cluster(mem, n=3)
    res = mem.consolidate()
    rows = mem.storage._conn.execute(
        "SELECT * FROM consolidation_run WHERE id=?", (res["batch_id"],)
    ).fetchall()
    assert len(rows) == 1


def test_weak_edges_not_merged(mem, clock):
    a = mem.write("甲乙")["id"]
    b = mem.write("丙丁")["id"]
    mem.link(a, b, "ASSOCIATED", weight=2.0)  # 弱边，不达 8.0
    res = mem.consolidate()
    assert res["changed"] == 0
