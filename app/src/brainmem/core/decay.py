"""衰减解析解（规范第 4.2 节）。全部整数 bp 运算，浮点只在中间计算。

连续方程:  dW/dt = -k*(1 + H/(W+C)) / (1 + S/S0)
解析解:    令 u = W+C, k' = k/(1+S/S0)
           u - H*ln(u+H) = u0 - H*ln(u0+H) - k'*t
用二分法反解 u，O(log) 得到任意时刻权重。
"""
import math

from brainmem.core.params import BP, WeightParams


def bp(x: float) -> int:
    """权重(float) -> 万分位整数（half-up）。全系统唯一取整入口。"""
    return int(x * BP + 0.5)


def to_float(wb: int) -> float:
    return wb / BP


def show(wb: int) -> str:
    """显示用两位小数。"""
    return f"{wb / BP:.2f}"


def _f(u: float, H: float) -> float:
    return u - H * math.log(u + H)


def decay_bp(wb: int, s: int, days: float, p: WeightParams) -> int:
    """解析解：经过 days 天后剩余权重（bp）。days 可为小数。"""
    if wb <= 0:
        return 0
    if days <= 0:
        return wb
    kp = p.k / (1.0 + s / p.S0)
    u0 = wb / BP + p.C
    rhs = _f(u0, p.H) - kp * days
    lo, hi = 1e-9 + p.C, u0
    for _ in range(120):
        mid = (lo + hi) / 2.0
        if _f(mid, p.H) > rhs:
            hi = mid
        else:
            lo = mid
    u = (lo + hi) / 2.0
    return max(0, bp(u - p.C))


def days_to(wb: int, s: int, target_w: float, p: WeightParams) -> float:
    """解析解：从当前权重衰减到 target_w 需要多少天。"""
    if wb <= bp(target_w):
        return 0.0
    kp = p.k / (1.0 + s / p.S0)
    u0 = wb / BP + p.C
    ut = target_w + p.C
    return (_f(u0, p.H) - _f(ut, p.H)) / kp


def lambda_at(wb: int, s: int, p: WeightParams) -> float:
    """瞬时衰减速率 λ(W)（权重/天），严格随 W 递减。"""
    w = max(wb, 0) / BP
    return p.k * (1.0 + p.H / (w + p.C)) / (1.0 + s / p.S0)


def days_to_zero(wb: int, s: int, p: WeightParams) -> float:
    return days_to(wb, s, 0.0, p)
