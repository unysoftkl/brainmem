"""状态机（规范第 4.4 / 5 节）。"""
from brainmem.core.decay import bp
from brainmem.core.enums import STATE_LEVEL, State
from brainmem.core.params import BP

T_FULL = 6.00
T_SIMPLIFY = 3.00
T_CONDENSE = 1.00


def state_of(wb: int) -> State:
    """由 weight_bp 派生状态（左开右闭，互不重叠）。

    规范 4.4：VESTIGE 为 0 < W ≤ 1.00；CONDENSED 为 1.00 < W ≤ 3.00。
    """
    w = wb / BP
    if wb <= 0:
        return State.DELETED
    if w <= T_CONDENSE:      # ≤ 1.00
        return State.VESTIGE
    if w <= T_SIMPLIFY:      # ≤ 3.00
        return State.CONDENSED
    if w <= T_FULL:          # ≤ 6.00
        return State.NORMAL
    return State.FULL


def transition(old: State, new: State) -> list[str]:
    """返回需要触发的副作用清单，由 engine 执行。"""
    if new == State.DELETED:
        return ["physical_delete"]
    ol, nl = STATE_LEVEL[old], STATE_LEVEL[new]
    if nl < ol:  # 降档
        if new == State.VESTIGE:
            return ["compress:vestige"]
        if new == State.CONDENSED:
            return ["compress:condensed"]
        return ["compress:normal"]
    if nl > ol:  # 升档（强化回升）
        return ["restore:verbatim"]
    return []


def initial_state(w0_bp: int) -> State:
    return state_of(w0_bp)
