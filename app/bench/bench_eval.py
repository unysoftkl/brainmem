# -*- coding: utf-8 -*-
"""阶段5 评测（bench/bench_eval.py）：

1) ForgettingBench：构造 1000 条（重要200/一次性300/干扰500），模拟 365 天，
   检验重要记忆召回率 ≥90%、一次性记忆残留率 ≤10%、干扰项不挤占上下文。
2) LoCoMo 风格多跳问答（自建合成集）：单跳/多跳准确率与 F1。
3) LongMemEval 风格多会话推理：跨会话事实召回准确率。
4) 端到端检索延迟：让出 top_k=4 的 P95 < 200ms。

输出 JSON 供阶段报告引用。
"""
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from brainmem.core.time import FakeClock
from brainmem.interfaces.memory import Memory

DIRECTIONS = "东西南北中上下左右前后"
OBJECTS = "书笔纸墨琴棋书画花草木石水火土金木"


def _uniq(i, n=3):
    """生成 i 对应的唯一短标签（≤6 字）。"""
    d = DIRECTIONS[i % len(DIRECTIONS)]
    o = OBJECTS[(i // len(DIRECTIONS)) % len(OBJECTS)]
    return f"{d}{o}{i}"[:6]


def forgetting_bench():
    """365 天模拟：重要记忆在一年中反复出现（每 30 天复习一次），
    一次性记忆随机某天写一次，干扰项随机写入；检验重要召回/一次性残留/干扰占用。"""
    clock = FakeClock(1000.0)
    m = Memory.in_memory(clock)
    imp, once, dist = [], [], []

    # 第 0 天：写入 200 条重要记忆
    for i in range(200):
        t = "要" + _uniq(i)
        imp.append((m.write(t)["id"], t))
    # 第 0 天：一次性 + 干扰也先写入一部分
    for i in range(300):
        once.append((m.write("次" + _uniq(i))["id"], "次" + _uniq(i)))
    for i in range(500):
        dist.append((m.write("扰" + _uniq(i))["id"], "扰" + _uniq(i)))

    # 一年中每 30 天复习一次重要记忆（模拟"反复出现"）
    for month in range(12):
        clock.advance_days(30)
        for (_, t) in imp:
            m.write(t)  # 窗口外 → 强化

    clock.advance_days(5)  # 到第 365 天
    m.scan()  # 结算，归零者删除

    def alive(items):
        return [t for (i, t) in items if m.storage.get_node(i) is not None]

    def is_dist(hid):
        return any(hid == i for (i, _) in dist)

    imp_recall = 0
    for (i, t) in imp:
        if m.storage.get_node(i) is None:
            continue
        hits = m.search(t, top_k=4, hops=1)
        if any(h["id"] == i for h in hits):
            imp_recall += 1
    imp_recall_rate = imp_recall / len(imp)
    once_residue_rate = len(alive(once)) / len(once)

    occ = 0
    checked = 0
    for (i, t) in imp[:20]:
        if m.storage.get_node(i) is None:
            continue
        hits = m.search(t, top_k=4, hops=1)
        occ += sum(1 for h in hits if is_dist(h["id"]))
        checked += 1
    distraction_occ = occ / (checked * 4) if checked else 0.0
    n_final = m.stats()["nodes"]
    m.close()
    return {
        "important_recall": round(imp_recall_rate, 4),
        "one_time_residue": round(once_residue_rate, 4),
        "distraction_occupancy": round(distraction_occ, 4),
        "n_nodes_final": n_final,
    }


def locomo_style():
    """单跳/多跳合成问答：簇内成员 + 跨簇链。"""
    clock = FakeClock(1000.0)
    m = Memory.in_memory(clock)
    # 3 跳事实链：A-B-C-D 关联，问 A 应能经扩散召回 D
    a = m.write("起点")["id"]
    b = m.write("中转")["id"]
    c = m.write("终点")["id"]
    m.link(a, b, "ASSOCIATED", weight=9.0)
    m.link(b, c, "ASSOCIATED", weight=9.0)
    for _ in range(5):
        m.link(a, b, "ASSOCIATED", weight=1.0)
        m.link(b, c, "ASSOCIATED", weight=1.0)
    # 单跳：同义近邻
    x = m.write("数学")["id"]
    y = m.write("算术")["id"]
    m.link(x, y, "ASSOCIATED", weight=8.0)

    # 单跳问答：query=数学，期望命中数学
    s1 = m.search("数学", top_k=4)
    single = 1.0 if s1 and s1[0]["id"] == x else 0.0
    # 多跳：query=起点，期望命中终点（2 跳）
    s2 = m.search("起点", top_k=4, hops=2)
    multi = 1.0 if any(h["id"] == c for h in s2) else 0.0
    # F1 近似：命中集合与期望集合的 F1（这里每次 1 个期望）
    f1 = (2 * single * 1) / (single + 1) if single else 0.0
    m.close()
    return {"single_hop_accuracy": single, "multi_hop_accuracy": multi, "f1": round(f1, 4)}


def longmemeval_style():
    """多会话推理：会话1写入事实，隔多日后会话2按其检索。"""
    clock = FakeClock(1000.0)
    m = Memory.in_memory(clock)
    facts = []
    for i in range(50):
        t = "事" + _uniq(i)
        r = m.write(t)
        facts.append((r["id"], t))
    # 模拟多会话间隔
    clock.advance_days(30)
    hit = 0
    for (i, t) in facts:
        if m.storage.get_node(i) is None:
            continue
        res = m.search(t, top_k=4, hops=1)
        if any(h["id"] == i for h in res):
            hit += 1
    return {"multi_session_accuracy": round(hit / len(facts), 4)}


def latency_p95(n=300):
    clock = FakeClock(1000.0)
    m = Memory.in_memory(clock)
    for i in range(1000):
        m.write("记" + _uniq(i))
    lat = []
    for i in range(n):
        t = "记" + _uniq(i % 1000)
        t0 = time.perf_counter()
        m.search(t, top_k=4, hops=2)
        lat.append((time.perf_counter() - t0) * 1000)
    m.close()
    lat.sort()
    return {
        "n": n,
        "p50_ms": round(statistics.median(lat), 3),
        "p95_ms": round(lat[int(0.95 * len(lat))], 3),
        "p99_ms": round(lat[int(0.99 * len(lat))], 3),
    }


if __name__ == "__main__":
    out = {
        "forgetting_bench": forgetting_bench(),
        "locomo_style": locomo_style(),
        "longmemeval_style": longmemeval_style(),
        "latency": latency_p95(),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    with open(os.path.join(os.path.dirname(__file__), "..", "bench_result_p5.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
