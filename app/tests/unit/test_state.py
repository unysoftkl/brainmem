"""状态机（UC-12 ~ UC-14）。"""
from brainmem.core.decay import bp
from brainmem.core.enums import State
from brainmem.core.lifecycle import state_of, transition


def test_state_boundaries():
    assert state_of(0) == State.DELETED
    assert state_of(bp(0.5)) == State.VESTIGE
    assert state_of(bp(1.0)) == State.VESTIGE       # <=1.00
    assert state_of(bp(1.5)) == State.CONDENSED
    assert state_of(bp(3.0)) == State.CONDENSED     # <=3.00
    assert state_of(bp(5.0)) == State.NORMAL
    assert state_of(bp(6.0)) == State.NORMAL        # <=6.00
    assert state_of(bp(6.5)) == State.FULL


def test_uc12_state_migration(mem, clock):
    # CONDENSED：3 字节点衰减到 ~2.0
    r = mem.write("一二三")
    res = mem.settle(r["id"], day=1000 + 120)
    assert res["state"] == "CONDENSED"
    # VESTIGE：衰减到 <1.00
    r2 = mem.write("四五六")
    res2 = mem.settle(r2["id"], day=1000 + 165)
    assert res2["state"] == "VESTIGE"
    # DELETED：归零后物理删除
    r3 = mem.write("七八九")
    res3 = mem.settle(r3["id"], day=1000 + 180)
    assert res3["deleted"] is True


def test_uc13_reinforce_restores_state(mem, clock):
    r = mem.write("一二三")
    nid = r["id"]
    mem.settle(nid, day=1000 + 150)  # 压到 CONDENSED
    assert mem.get(nid)["state"] == "CONDENSED"
    # 反复强化把它拉回
    for i in range(40):
        clock.set_day(1000 + 150 + (i + 1) * 2)  # 每次间隔 2 天 > 幂等窗口
        mem.write("一二三")  # 窗口外 → 强化
    got = mem.get(nid)
    assert got["state"] in ("NORMAL", "FULL")
    # 存在 RESTORE 事件
    evs = mem.storage.iter_events(nid)
    assert any(e.event_type.value == "RESTORE" for e in evs)


def test_uc14_state_covers_and_no_overlap():
    seen = set()
    for w in range(0, 200001, 37):
        st = state_of(w)
        assert st in set(State)
    # 五状态并集覆盖：每个状态至少被命中
    for w in [0, bp(0.5), bp(2.0), bp(5.0), bp(10.0)]:
        seen.add(state_of(w))
    assert seen == set(State)


def test_transition_side_effects():
    assert transition(State.NORMAL, State.CONDENSED) == ["compress:condensed"]
    assert transition(State.CONDENSED, State.VESTIGE) == ["compress:vestige"]
    assert transition(State.CONDENSED, State.NORMAL) == ["restore:verbatim"]
    assert transition(State.VESTIGE, State.DELETED) == ["physical_delete"]
