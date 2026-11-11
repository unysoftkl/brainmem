"""压缩/保真度/扫描 集成（UC-C：阶段3）。"""
from brainmem.core.decay import decay_bp
from brainmem.core.params import DEFAULT_PARAMS as P
from brainmem.core.tables import initial_weight


def test_compression_on_state_drop(mem, clock):
    # 8 字节点入库即 CONDENSED；继续衰减进入 VESTIGE 时应压缩 gist
    r = mem.write("一二三四五六七八")
    nid = r["id"]
    assert mem.get(nid)["state"] == "CONDENSED"
    before_gist = mem.storage.get_node(nid).gist
    # 结算到很晚（进 VESTIGE）
    mem.settle(nid, day=1000 + 55)
    node = mem.storage.get_node(nid)
    assert node.state.value in ("VESTIGE", "DELETED")
    if node.state.value == "VESTIGE":
        assert node.fidelity <= 30
        assert node.gist is not None


def test_note_verbatim_and_reinforce(mem, clock):
    # 带原文记忆：短标题入库，长原文冷存；再次写入同标题 → 强化（不重建）
    text = "张三在北京市海淀区买了三本书"
    r = mem.write_note("买书记录", text)
    nid = r["id"]
    assert mem.storage.get_node(nid).verbatim_ref is not None
    assert mem.storage.get_node(nid).label == "买书记录"
    clock.advance_days(1)
    r2 = mem.write_note("买书记录", text)  # 同标题 → 强化已有节点
    assert r2["id"] == nid and r2["created"] is False
    evs = mem.storage.iter_events(nid)
    assert any(e.event_type.value == "REINFORCE" for e in evs)
    # 原文可从冷存回读
    ref = mem.storage.get_node(nid).verbatim_ref
    assert mem.engine.blob_store.get(ref).decode("utf-8") == text


def test_scan_settles_across_thresholds(mem, clock):
    for w in ["一二三", "四五六", "七八九"]:
        mem.write(w)
    clock.advance_days(120)
    res = mem.scan()
    assert res["scanned"] == 3
    assert res["settled"] >= 1


def test_365_day_accuracy(mem, clock):
    """模拟 365 天：惰性求值与解析解误差 < 0.01（0.01*BP=100bp）。"""
    r = mem.write("一二三")  # 3 字，W0=6.00
    nid = r["id"]
    mem.settle(nid, day=1000)  # 起始结算
    # 逐月推进，检查惰性求值 == 解析解
    max_err = 0
    for day in range(1000, 1000 + 366, 30):
        clock.set_day(day)
        got = mem.get(nid)["weight_bp"]
        expect = decay_bp(int(initial_weight(3) * 10000), 0, day - 1000, P)
        max_err = max(max_err, abs(got - expect))
    assert max_err < 100, f"max_err={max_err}bp"


def test_long_text_allowed_and_low_weight(mem, clock):
    # 字数由 AI 决定，>10 字允许入库，但权重更低（单调下降）
    r = mem.write("今天天气很好我去公园散步")  # 12 字
    assert float(r["weight"]) < 1.00
