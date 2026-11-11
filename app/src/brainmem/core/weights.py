"""强化模型（规范第 4.3 节）。"""
from brainmem.core.decay import bp
from brainmem.core.params import BP, WeightParams


def reinforce(
    wb: int, s: int, peak_bp: int, days_since: float, p: WeightParams
) -> tuple[int, int, int, int]:
    """一次强化。返回 (新权重bp, 新稳固度, 新峰值bp, 稳固度增量)。"""
    w = wb / BP
    r = min(1.0, wb / max(peak_bp, 1))            # 可提取度 R
    difficulty = 1.0 + p.beta * (1.0 - r)          # 越接近遗忘收益越大
    spacing = 1.0 + p.gamma * min(1.0, max(0.0, days_since) / 14.0)
    gain = p.G0 * difficulty * spacing * (1.0 - w / p.W_MAX) / (1.0 + 0.10 * s)
    new_wb = min(bp(p.W_MAX), wb + bp(max(0.0, gain)))
    ds = 1 + min(2, int(max(0.0, days_since) // 10))
    new_s = min(p.S_MAX, s + ds)
    return new_wb, new_s, max(peak_bp, new_wb), ds


def fidelity_after_reinforce(fidelity: int) -> int:
    """强化使保真度 +5，上限 100。"""
    return min(100, fidelity + 5)
