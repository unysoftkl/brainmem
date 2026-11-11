"""边权模型（规范第 6 节边参数；设计书 4.5）。

边与节点用两套参数：节点权重=这条记忆多容易被想起，边权重=两者多容易被一起想起。
dE/dt = -k_e*(1 + H_e/(E+C_e)) / (1 + 0.15*ln(1+n_coact))
"""
import math

from brainmem.core.decay import bp
from brainmem.core.params import BP, WeightParams


def edge_reinforce_bp(eb: int, coact: int, p: WeightParams) -> tuple[int, int]:
    """共激活一次：E <- min(E_MAX, E + g_e*(1 - E/E_MAX))；coact += 1。"""
    e = eb / BP
    new_e = min(p.E_MAX, e + p.g_e * (1.0 - e / p.E_MAX))
    return min(bp(p.E_MAX), bp(new_e)), coact + 1


def edge_instant_rate(eb: int, coact: int, p: WeightParams) -> float:
    """边权瞬时衰减速率（权重/天）。"""
    e = max(eb, 0) / BP
    damping = 1.0 + 0.15 * math.log1p(max(0, coact))
    return p.k_e * (1.0 + p.H_e / (e + p.C_e)) / damping


def edge_decay_bp(eb: int, coact: int, days: float, p: WeightParams, dt: float = 0.05) -> int:
    """边权衰减：对速率做细步数值积分（边权无解析闭式，量小，够用）。"""
    if eb <= 0 or days <= 0:
        return max(0, eb)
    e = eb / BP
    steps = max(1, int(days / dt))
    h = days / steps
    for _ in range(steps):
        rate = p.k_e * (1.0 + p.H_e / (e + p.C_e)) / (1.0 + 0.15 * math.log1p(max(0, coact)))
        e = max(0.0, e - rate * h)
        if e <= 0:
            return 0
    return max(0, bp(e))


def edge_days_to_zero(eb: int, coact: int, p: WeightParams, max_days: float = 40000.0,
                      dt: float = 0.5) -> float:
    """边权从 eb 衰减到 0 需要多少天（数值积分，边权无解析闭式）。"""
    if eb <= 0:
        return 0.0
    e = eb / BP
    day = 0.0
    while day < max_days:
        rate = p.k_e * (1.0 + p.H_e / (e + p.C_e)) / (1.0 + 0.15 * math.log1p(max(0, coact)))
        e -= rate * dt
        day += dt
        if e <= 0:
            return day
    return max_days
