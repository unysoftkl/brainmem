"""阶段2 验收（自动化版）：小规模簇集上断言 Recall@10 / MRR / 2 跳。"""
from brainmem.interfaces.memory import Memory

CLUSTERS = {
    "数学": "数加减乘除方程式微积分几何代数概率统计函数变量矩阵向量极限导数",
    "物理": "力速度加速度质量能量动量电路电压电阻磁场地热光电原子分子波长",
    "生物": "细胞基因蛋白细胞核线粒体叶绿体组织器官种群生态进化遗传酶光合",
    "音乐": "音符旋律节奏和声乐器钢琴吉他提琴鼓号曲调音阶和弦节拍谱号调式",
    "编程": "变量函数循环数组指针算法编译调试接口类对象继承并发线程进程内存",
    "交通": "汽车火车飞机轮船公交地铁自行车道路桥梁隧道航班站台机场港口码头",
}


def _build(mem):
    ids_by_cluster = {}
    for head, chars in CLUSTERS.items():
        ids = []
        for ch in chars[:12]:
            r = mem.write((head + ch)[:8])
            ids.append(r["id"])
        for a, b in zip(ids, ids[1:]):
            mem.link(a, b, "ASSOCIATED", weight=8.0)
        ids_by_cluster[head] = ids
    return ids_by_cluster


def test_acceptance_recall_mrr_2hop(mem, clock):
    ids_by_cluster = _build(mem)
    recalls, rrs, hop_ok, hop_n = [], [], 0, 0
    for head, ids in ids_by_cluster.items():
        cluster_set = set(ids)
        for qidx in (0, 5):
            qid = ids[qidx]
            qlabel = mem.get(qid)["label"]
            relevant = cluster_set - {qid}
            hits = mem.search(qlabel, top_k=10, hops=2)
            hit_ids = [h["id"] for h in hits if h["id"] != qid]
            hit = len(relevant & set(hit_ids))
            recalls.append(hit / min(10, len(relevant)))
            rr = 0.0
            for rank, hid in enumerate(hit_ids, 1):
                if hid in relevant:
                    rr = 1.0 / rank
                    break
            rrs.append(rr)
            hop_n += 1
            if hit >= 2:
                hop_ok += 1
    recall = sum(recalls) / len(recalls)
    mrr = sum(rrs) / len(rrs)
    two_hop = hop_ok / hop_n
    assert recall >= 0.85, f"Recall@10={recall}"
    assert mrr >= 0.70, f"MRR={mrr}"
    assert two_hop >= 0.80, f"2hop={two_hop}"
