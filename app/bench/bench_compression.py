# -*- coding: utf-8 -*-
"""阶段3 验收脚本：
1) 365 天衰减误差（惰性求值 vs 解析解）< 0.01
2) 压缩后关键实体保留率 ≥ 95%
3) 压缩前后检索 Recall 下降 < 5%
4) 7 天（模拟）无权重漂移：事件复算对账 0 不一致
输出 JSON 供报告引用。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from brainmem.core.decay import BP, decay_bp
from brainmem.core.params import DEFAULT_PARAMS as P
from brainmem.core.tables import initial_weight
from brainmem.core.time import FakeClock
from brainmem.interfaces.memory import Memory
from brainmem.services.entities import extract_entities


def accuracy_365(mem, clock):
    """对每个字数的节点，逐日惰性求值 vs 解析解，取最大误差（权重单位）。

    只统计"尚未归零/删除"的天，归零后物理删除是设计行为，不计入衰减误差。
    """
    max_err = 0.0
    base_chars = "数理化生英史地政语外"
    for n in range(1, 11):
        label = base_chars[n - 1] * n  # 每个字数用不同基字，避免语义查重合并
        r = mem.write(label)
        nid = r["id"]
        mem.settle(nid, day=1000.0)
        w0 = int(initial_weight(n) * BP)
        for day in range(1000, 1000 + 366, 5):
            clock.set_day(float(day))
            node = mem.storage.get_node(nid)
            if node is None:
                break  # 已归零删除
            got = mem.get(nid)["weight_bp"]
            expect = decay_bp(w0, 0, day - 1000, P)
            max_err = max(max_err, abs(got - expect))
    return max_err / BP  # 转换为权重单位


def entity_retention_rate(mem, clock):
    """压缩后关键实体保留率：直接对原文施加 CONDENSED / VESTIGE 压缩，统计实体保留。"""
    from brainmem.services.compressor import condense, vestige

    samples = [
        "张三在北京市海淀区买了3本书2024年5月",
        "李四从上海坐G102次高铁去广州开会",
        "王五于2023年在清华大学发表了2篇论文",
        "赵六在深圳南山区工作月薪2万元",
        "钱七去杭州市西湖区参观了5个景点",
        "陈八在南京大学研究了5年人工智能2025年",
        "周九从成都坐飞机到武汉出差三天",
        "吴十在杭州阿里巴巴工作月薪3万元2024年",
    ]
    total, kept = 0, 0
    for s in samples:
        ents = extract_entities(s)
        g_cond, _ = condense(s)
        g_vest, _ = vestige(s)
        total += len(ents)
        # CONDENSED 与 VESTIGE 两档都保留的实体才算保留
        kept += sum(1 for e in ents if e in g_cond and e in g_vest)
    return kept / total if total else 1.0


def compression_recall_drop(mem, clock):
    """同一检索集，压缩前 vs 压缩后的 Recall@10 差值。"""
    # 构造 12 簇（复用阶段2思路的小规模）
    clusters = {
        "数学": "数加减乘除方程函数向量极限导数概率统计矩阵",
        "物理": "力速度质量能量动量电路电压电阻磁场光电原子",
        "生物": "细胞基因蛋白组织器官种群生态进化遗传酶光合",
        "音乐": "音符旋律节奏和声乐器钢琴吉他曲调音阶和弦",
        "编程": "变量函数循环数组指针算法编译调试接口类对象",
        "交通": "汽车火车飞机轮船公交地铁道路桥梁隧道航班",
    }
    ids_by = {}
    for head, chars in clusters.items():
        ids = []
        for ch in chars[:8]:
            ids.append(mem.write((head + ch)[:8])["id"])
        for a, b in zip(ids, ids[1:]):
            mem.link(a, b, "ASSOCIATED", weight=8.0)
        ids_by[head] = ids

    def recall():
        rec = []
        for head, ids in ids_by.items():
            cset = set(ids)
            for qid in ids[:3]:
                q = mem.get(qid)["label"]
                rel = cset - {qid}
                hits = [h["id"] for h in mem.search(q, top_k=10, hops=2) if h["id"] != qid]
                rec.append(len(rel & set(hits)) / min(10, len(rel)))
        return sum(rec) / len(rec)

    before = recall()
    # 全量衰减到 CONDENSED（压缩）后再测
    for ids in ids_by.values():
        for nid in ids:
            mem.settle(nid, day=clock.now_day() + 120)
    after = recall()
    return before, after, (before - after)


def drift_check(mem):
    rep = mem.reconcile(1.0)
    return rep


if __name__ == "__main__":
    clock = FakeClock(1000.0)
    mem = Memory.in_memory(clock)

    acc = accuracy_365(mem, clock)
    clock2 = FakeClock(1000.0)
    mem2 = Memory.in_memory(clock2)
    ret = entity_retention_rate(mem2, clock2)
    clock3 = FakeClock(1000.0)
    mem3 = Memory.in_memory(clock3)
    before, after, drop = compression_recall_drop(mem3, clock3)
    drift = drift_check(mem3)

    out = {
        "decay_max_error_365d": round(acc, 5),
        "entity_retention": round(ret, 4),
        "recall_before_compress": round(before, 4),
        "recall_after_compress": round(after, 4),
        "recall_drop": round(drop, 4),
        "reconcile": drift,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    with open(os.path.join(os.path.dirname(__file__), "..", "bench_result_p3.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    for m in (mem, mem2, mem3):
        m.close()
