"""事件复算对账（UC-15/16 的集成版）：混合操作后对账必须 0 不一致。"""
from brainmem.core.decay import show


def test_reconcile_after_mixed_ops(mem, clock):
    leads = "甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉"
    seconds = "零一二三四五六七八九"
    ids = []
    for i in range(200):
        label = leads[i // 10] + seconds[i % 10] + "记"  # 200 个互不相同、彼此低相似的 3 字标签
        r = mem.write(label)
        ids.append(r["id"])
    # 推进时间：一部分结算（衰减），一部分重复录入（强化）
    clock.advance_days(30)
    for nid in ids[:100]:
        mem.settle(nid)
    clock.advance_days(1)
    for nid in ids[100:]:
        node = mem.storage.get_node(nid)
        mem.write(node.label)  # 窗口外 → 强化
    rep = mem.reconcile(1.0)
    assert rep["checked"] == 200
    assert rep["mismatched"] == 0, rep["mismatches"]


def test_replay_matches_get_weight(mem, clock):
    r = mem.write("一二三")
    nid = r["id"]
    clock.advance_days(50)
    mem.settle(nid)
    clock.advance_days(10)
    # 库内权重（结算后）应与事件重放一致
    node = mem.storage.get_node(nid)
    assert mem.engine.replay_events(nid) == node.weight_bp
