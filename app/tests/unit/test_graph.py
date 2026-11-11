"""扩散激活（设计书 5.4.1）。"""
from brainmem.services.graph import spreading_activation


def test_diffusion_spreads_and_decays(mem, clock):
    a = mem.write("数学")["id"]
    b = mem.write("几何")["id"]
    c = mem.write("圆规")["id"]
    mem.link(a, b, "ASSOCIATED", weight=8.0)
    mem.link(b, c, "ASSOCIATED", weight=8.0)
    act = spreading_activation(mem.storage, {a: 1.0}, hops=2, gamma=0.55)
    assert a in act and act[a] >= 1.0
    assert b in act and act[b] > 0          # 1 跳扩散到 b
    assert c in act and 0 < act[c] < act[b]  # 2 跳更弱


def test_hops_limit(mem, clock):
    a = mem.write("甲")["id"]
    b = mem.write("乙")["id"]
    c = mem.write("丙")["id"]
    mem.link(a, b, "ASSOCIATED", weight=8.0)
    mem.link(b, c, "ASSOCIATED", weight=8.0)
    act1 = spreading_activation(mem.storage, {a: 1.0}, hops=1)
    assert b in act1 and c not in act1  # 1 跳够不到 c
