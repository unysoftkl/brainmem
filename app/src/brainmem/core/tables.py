"""初始权重阶梯与保真度表（规范第 4.1 节，查表 + 内插）。

字数不必 ≤10：AI 自行决定简写到几个字，记忆库只按字数给权重 W0=f(n)。
- 1–10 字：沿用冻结表（短=强，核心概念耐用）。
- >10 字：单调继续下降，尾公式 W = max(WEIGHT_FLOOR, (10/n)^0.3)（“A 缓”方案），
  即越长越弱（细节易逝）。最大字数见 MAX_LABEL_CHARS。
"""
import math

# 1..10 字的初始权重（已补全 1/2/4/6 字）——冻结表，不变
W0_TABLE: dict[int, float] = {
    1: 8.0, 2: 7.0, 3: 6.0, 4: 5.5, 5: 5.0,
    6: 4.5, 7: 4.0, 8: 3.0, 9: 2.0, 10: 1.0,
}
# 入库保真度
FIDELITY_TABLE: dict[int, int] = {
    1: 100, 2: 100, 3: 100, 4: 100, 5: 100,
    6: 100, 7: 100, 8: 85, 9: 75, 10: 65,
}

MAX_LABEL_CHARS = 100     # 标签字数上限（防小作文撑爆）
WEIGHT_FLOOR = 0.10       # >10 字时的权重地板
TAIL_EXP = 0.30           # 尾公式指数（A 缓：(10/n)^0.3）


def initial_weight(char_len: int) -> float:
    """按字符数返回初始权重 W0=f(n)。1–10 查冻结表；>10 按单调尾公式下降。"""
    if char_len < 1:
        raise ValueError("char_len must be >= 1")
    if char_len <= MAX_LABEL_CHARS and char_len in W0_TABLE:
        return W0_TABLE[char_len]
    if char_len <= 10:
        # 理论上表已覆盖 1..10，这里兜底线性内插
        lo = max(k for k in W0_TABLE if k <= char_len)
        hi = min(k for k in W0_TABLE if k >= char_len)
        if lo == hi:
            return W0_TABLE[lo]
        t = (char_len - lo) / (hi - lo)
        return W0_TABLE[lo] + t * (W0_TABLE[hi] - W0_TABLE[lo])
    # >10：从 (10, 1.00) 继续单调下降
    return max(WEIGHT_FLOOR, (10.0 / char_len) ** TAIL_EXP)


def fidelity_pct(char_len: int) -> int:
    if char_len < 1:
        raise ValueError("char_len must be >= 1")
    # 1–10 用表；>10 保真度继续下探（下限 40）
    if char_len <= 10:
        return FIDELITY_TABLE[max(1, char_len)]
    base = 65
    extra = int(round(25.0 / (1.0 + (char_len - 10) / 20.0)))
    return max(40, base - (25 - extra))

