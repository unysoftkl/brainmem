"""权重参数（规范第 6 节）。纯数据，无 IO。"""
from dataclasses import dataclass

BP = 10000


@dataclass(frozen=True)
class WeightParams:
    k: float = 0.016
    H: float = 3.0
    C: float = 0.10
    S0: float = 8.0
    W_MAX: float = 20.0
    G0: float = 2.00
    beta: float = 1.20
    gamma: float = 0.80
    S_MAX: int = 24
    k_e: float = 0.004
    H_e: float = 1.5
    C_e: float = 0.10
    E_MAX: float = 10.0
    g_e: float = 1.20
    link_init: float = 5.0   # AI 建边时，记忆库给出的初始边权（AI 不传权重）
    merge_edge: float = 8.0  # 合并前置：边权下限
    merge_coact: int = 5     # 合并前置：共激活次数下限
    merge_edge_min_days: float = 365.0  # 合并前置：边自身须能撑这么久不遗忘（1 年）
    # —— 用进废退：检索/使用即强化 ——
    use_boost: float = 0.5        # 每次“使用”（检索命中/被取用）给节点加多少权重
    walk_edge_boost: float = 0.3  # 每次检索走过一条连接，给该边加多少权重（共激活+1）
    use_boost_cap: float = 20.0   # 使用强化后权重上限（= W_MAX）

    @property
    def W_MAX_BP(self) -> int:
        return int(self.W_MAX * BP + 0.5)


DEFAULT_PARAMS = WeightParams()
