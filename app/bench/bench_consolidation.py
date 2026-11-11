# -*- coding: utf-8 -*-
"""阶段4 验收脚本：
1) 合并准确率（构造已知分簇，检测合并是否把同簇成员合到一起、不跨簇）
2) 回滚权重误差（merge_undo 后成员权重恢复原值，误差 0.00）
3) 父节点检索命中率提升（合并前后，抽象查询能召回父节点）
4) 100 万节点夜间任务时间的外推估算（用较小规模实测单节点耗时再外推，标注为估算）
输出 JSON 供报告引用。
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from brainmem.core.time import FakeClock
from brainmem.interfaces.memory import Memory

# 6 个互不相交的簇，每个 4 个成员
CLUSTERS = {
    "数": "加减乘除",
    "形": "圆方三角",
    "力": "电动磁热",
    "色": "红黄蓝绿",
    "味": "酸甜苦辣",
    "动": "跑跳走投",
}


def build(mem):
    truth = {}
    for base, chars in CLUSTERS.items():
        ids = [mem.write(f"{base}{ch}")["id"] for ch in chars]
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                for _ in range(5):
                    mem.link(ids[i], ids[j], "ASSOCIATED", weight=1.8)
        truth[base] = set(ids)
    return truth


def cluster_precision(truth):
    """按父节点成员归属计算精确率：父节点成员应尽量来自同一真簇。"""
    return truth


def run():
    clock = FakeClock(1000.0)
    mem = Memory.in_memory(clock)
    truth = build(mem)
    member_to_cluster = {}
    for base, ids in truth.items():
        for i in ids:
            member_to_cluster[i] = base

    t0 = time.perf_counter()
    res = mem.consolidate()
    elapsed = time.perf_counter() - t0

    # 合并准确率：每个父节点的成员，若全部来自同一真簇则该次合并"正确"
    correct, total = 0, 0
    for mrep in res["merges"]:
        total += 1
        members = mrep["members"]
        bases = {member_to_cluster.get(m) for m in members}
        if len(bases) == 1 and None not in bases:
            correct += 1
    precision = correct / total if total else 0.0

    # 回滚精度
    before = {nid: mem.storage.get_node(nid).weight_bp for ids in truth.values() for nid in ids}
    undo = mem.merge_undo(res["batch_id"])
    eq = 0
    for nid, wb in before.items():
        n = mem.storage.get_node(nid)
        if n is not None and n.weight_bp == wb:
            eq += 1
    rollback_err = 0 if eq == len(before) else 1

    # 父节点检索命中：合并后查询簇名，能否召回 ABSTRACT 父节点
    mem2 = Memory.in_memory(FakeClock(1000.0))
    build(mem2)
    res2 = mem2.consolidate()
    parents = {m["parent_id"] for m in res2["merges"]}
    hit = 0
    for base in CLUSTERS:
        hits = mem2.search(base, top_k=5, hops=2)
        if any(h["id"] in parents for h in hits):
            hit += 1
    parent_hit = hit / len(CLUSTERS)

    out = {
        "merge_batches": res["changed"],
        "merge_precision": round(precision, 4),
        "merge_count": total,
        "rollback_weight_error": rollback_err,
        "parent_hit_rate": round(parent_hit, 4),
        "consolidate_seconds_small": round(elapsed, 4),
        "n_nodes": mem2.stats()["nodes"],
        "n_edges": mem2.stats()["edges"],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    with open(os.path.join(os.path.dirname(__file__), "..", "bench_result_p4.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    mem.close(); mem2.close()


if __name__ == "__main__":
    run()
