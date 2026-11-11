# -*- coding: utf-8 -*-
"""阶段1 端到端演示：写入 → 衰减/结算 → 状态迁移 → 强化回升 → 解释 → 统计 → 对账。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from brainmem.core.time import FakeClock
from brainmem.interfaces.memory import Memory


def main():
    clock = FakeClock(1000.0)
    m = Memory.in_memory(clock)

    print("== 1. 写入（不同字数，验证初始权重阶梯）==")
    a = m.write("数学")          # 2 字 -> 7.00
    b = m.write("几何")          # 2 字
    c = m.write("一二三四五六七八")  # 8 字 -> 3.00 CONDENSED 保真度 85
    for r in (a, b, c):
        print("  ", r)
    print("  c 详情:", m.get(c["id"]))

    print("\n== 2. 幂等（窗口内重复写）==")
    print("  ", m.write("数学"))  # deduped=True

    print("\n== 3. 衰减 90 天并结算 a ==")
    clock.advance_days(90)
    print("  get a（惰性求值）:", m.get(a["id"])["weight"])
    print("  settle a:", m.settle(a["id"]))

    print("\n== 4. 强化回升（间隔 2 天反复录入）==")
    for i in range(20):
        clock.advance_days(2)
        m.write("数学")
    print("  a 现状:", m.get(a["id"]))

    print("\n== 5. 解释 a 的权重来历 ==")
    ex = m.explain(a["id"])
    print("  current:", ex["current_weight"], "state:", ex["state"])
    print("  事件数:", len(ex["events"]), " decay_math:", ex["decay_math"])

    print("\n== 6. 统计 ==")
    print("  ", m.stats())

    print("\n== 7. 事件复算对账 ==")
    print("  ", m.reconcile(1.0))

    m.close()


if __name__ == "__main__":
    main()
