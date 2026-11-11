"""memory_ingest 写入入口 + 权重操作（reinforce/simplify/merge/consolidate）。"""
import pytest

from brainmem.core.errors import TooLongError


def test_ingest_writes_atoms_no_edges(mem):
    r = mem.ingest(["数学", "几何", "物理"], text=None)
    assert r["atom_count"] == 3
    assert mem.stats()["nodes"] == 3
    assert mem.stats()["edges"] == 0        # 不自动建边
    assert r["note"]["saved"] is False


def test_ingest_with_note(mem):
    r = mem.ingest(["六点钟起床差点迟到", "吃了两个包子出门"],
                   text="早上六点半起床差点迟到，吃了两个包子出门。",
                   note_title="早上的事")
    assert r["atom_count"] == 2
    assert r["note"]["saved"] is True
    assert mem.stats()["nodes"] == 3         # 2 原子 + 1 note


def test_ingest_accepts_over_ten_chars(mem):
    # 新策略：AI 自己决定字数，库按字数给权重；>10 字不再拒绝
    r = mem.ingest(["这是一条超过十个字的原子记忆内容"])
    assert r["atom_count"] == 1
    a = r["atoms"][0]
    assert len(a["text"]) > 10
    # 字数越多权重越低（A 缓单调）
    assert float(a["weight"]) < 1.00


def test_ingest_rejects_beyond_max_label(mem):
    from brainmem.core.tables import MAX_LABEL_CHARS
    with pytest.raises(TooLongError):
        mem.ingest(["字" * (MAX_LABEL_CHARS + 1)])


def test_weight_monotonic_by_length(mem):
    # 字数越少权重越高、越多越低（1-10 冻结表 + >10 尾公式）
    ws = []
    for n in [1, 3, 5, 8, 10, 15, 25]:
        r = mem.ingest(["字" * n])
        ws.append(float(r["atoms"][0]["weight"]))
    assert all(ws[i] > ws[i + 1] for i in range(len(ws) - 1)), ws


def test_ingest_dedup(mem):
    r = mem.ingest(["数学", "数学", "几何"])
    assert r["atom_count"] == 2


def test_ingest_rejects_punctuation_only(mem):
    # 纯标点/符号/空白不得入库
    with pytest.raises(TooLongError):
        mem.ingest(["  ", "，", "。", "!!!", "——"])
    assert mem.stats()["nodes"] == 0


def test_ingest_strips_edge_punct_but_keeps_content(mem):
    r = mem.ingest(["「数学」", "，几何，"])
    texts = [a["text"] for a in r["atoms"]]
    assert texts == ["数学", "几何"], texts


def test_write_rejects_punctuation_only(mem):
    with pytest.raises(TooLongError):
        mem.write("，。！")


def test_reinforce_raises_weight(mem):
    r = mem.ingest(["数学"])
    nid = r["atoms"][0]["id"]
    w0 = float(mem.get(nid)["weight"])
    w1 = float(mem.reinforce(nid)["weight"])
    assert w1 > w0


def test_simplify_changes_label_and_reinforces(mem):
    r = mem.ingest(["六点钟起床差点迟到"])
    nid = r["atoms"][0]["id"]
    w0 = float(mem.get(nid)["weight"])
    s = mem.simplify(nid, "差点迟到")
    assert s["changed"] is True
    assert mem.get(nid)["label"] == "差点迟到"
    assert float(s["weight"]) > w0


def _make_strong(mem, a, b, relation="ASSOCIATED", times=10):
    """反复共激活，把 a-b 边权/共激活抬到合并门槛(≥8.00 且 ≥5)。"""
    for _ in range(times):
        mem.link(a, b, relation)


def test_merge_requires_strong_links(mem):
    """合并前置条件：联系不够强必须拒绝。"""
    r = mem.ingest(["起床", "刷牙洗脸"])
    a, b = r["atoms"][0]["id"], r["atoms"][1]["id"]
    # 没有任何连接 -> 拒绝
    with pytest.raises(TooLongError):
        mem.merge([a, b], "早上准备")
    # 只连一次（边权弱、共激活1）-> 仍拒绝
    mem.link(a, b, "ASSOCIATED")
    with pytest.raises(TooLongError):
        mem.merge([a, b], "早上准备")
    # 反复加强到达标 -> 允许
    _make_strong(mem, a, b, times=10)
    res = mem.merge([a, b], "早上准备")       # 默认软合并
    assert res["mode"] == "soft"
    assert res["member_count"] == 2


def test_merge_hard_removed(mem):
    """硬合并已移除：传 mode='hard' 应报错。"""
    r = mem.ingest(["起床", "刷牙洗脸"])
    a, b = r["atoms"][0]["id"], r["atoms"][1]["id"]
    _make_strong(mem, a, b, times=10)
    with pytest.raises(ValueError):
        mem.merge([a, b], "早上准备", mode="hard")


def test_merge_soft_keeps_members_and_verbatim(mem):
    """软合并（默认 mode='soft'）：父节点+成员全保留+原文汇总，可展开、可回滚。"""
    r = mem.ingest(["养了条鱼"], text="2026-11-09 养了一条大肥鱼，取名小穗。", note_title="养鱼")
    a = r["atoms"][0]["id"]
    r2 = mem.ingest(["鱼会忘事"], text="2026-11-10 发现小穗会忘事，很担心。", note_title="担心")
    b = r2["atoms"][0]["id"]
    _make_strong(mem, a, b)
    res = mem.merge([a, b], "养鱼与忘事")     # 默认 soft
    assert res["mode"] == "soft"
    assert res["member_count"] == 2
    # 成员都还在
    ids_all = {n["id"] for n in mem.list_nodes()}
    assert a in ids_all and b in ids_all
    # 父节点带汇总原文
    parent = mem.get(res["id"], include_verbatim=True)
    assert parent.get("verbatim") and "大肥鱼" in parent["verbatim"]
    assert res["has_verbatim"] is True
    # 父节点下挂 MEMBER_OF 边
    edges = [e for e in mem.storage.all_edges("default")
             if e.src_id == res["id"]]
    assert len([e for e in edges if e.relation.value == "MEMBER_OF"]) == 2
    # 回滚：父删、成员还在
    u = mem.merge_undo(res["batch_id"])
    assert u["undone"] == 2
    ids_after = {n["id"] for n in mem.list_nodes()}
    assert a in ids_after and b in ids_after


def test_use_boosts_weight_on_search(mem, clock):
    """用进废退：检索命中即自动加权重。"""
    r = mem.ingest(["苹果", "水果"])
    ids = [a["id"] for a in r["atoms"]]
    mem.link(ids[0], ids[1], "ASSOCIATED")
    w0 = float(mem.get(ids[0])["weight"])
    # 检索（use=True 默认）→ 命中节点权重上升
    mem.search("苹果", top_k=2)
    w1 = float(mem.get(ids[0])["weight"])
    assert w1 > w0, (w0, w1)


def test_search_use_false_is_readonly(mem, clock):
    r = mem.ingest(["苹果"])
    nid = r["atoms"][0]["id"]
    w0 = float(mem.get(nid)["weight"])
    mem.search("苹果", top_k=2, use=False)
    assert float(mem.get(nid)["weight"]) == w0


def test_use_strengthens_walked_edges(mem, clock):
    """检索走到的连接，边权/共激活也增加。"""
    r = mem.ingest(["苹果", "水果"])
    a, b = [x["id"] for x in r["atoms"]]
    mem.link(a, b, "ASSOCIATED")
    e0 = [e for e in mem.storage.all_edges("default")][0]
    mem.search("苹果", top_k=2)     # walk edges
    e1 = [e for e in mem.storage.all_edges("default")][0]
    assert e1.coactivation > e0.coactivation
    assert e1.weight_bp >= e0.weight_bp


def test_get_with_use_boosts(mem):
    r = mem.ingest(["几何"])
    nid = r["atoms"][0]["id"]
    w0 = float(mem.get(nid)["weight"])
    mem.feedback(nid)  # 等价 memory_get(use=True) 走底层
    assert float(mem.get(nid)["weight"]) > w0
