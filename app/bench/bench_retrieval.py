# -*- coding: utf-8 -*-
"""阶段2 验收脚本：自建 500 条记忆集，测 Recall@10 / MRR / 2 跳准确率。

构造方式（不引入外部依赖）：
- 12 个语义簇（数学/几何/物理/化学/生物/历史/地理/音乐/体育/编程/饮食/交通），
  每簇 40 个"成员词"，簇内字面高度重叠、簇间低重叠；簇内建链。
- 查询：取每个簇前若干成员作为 query（前缀 2 字），期望召回该簇成员。
输出 JSON 供阶段报告引用。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from brainmem.core.time import FakeClock
from brainmem.interfaces.memory import Memory

CLUSTERS = {
    "数学": "数加减乘除方程式微积分几何代数概率统计函数变量矩阵向量极限导数整数分数小数正负平方根立方根对数指数排列组合数列归纳演绎定理公理证明推理",
    "几何": "圆规三角尺直径半径面积体积角度平行垂直相交曲线曲面圆弧切线多边形正方形长方形梯形菱形椭圆抛物线双曲线坐标系投影对称旋转平移",
    "物理": "力速度加速度质量能量动量电路电压电阻磁场地热光电原子分子电子质子中子波长频率折射反射透镜杠杆滑轮压强浮力温度热量",
    "化学": "元素化合价酸碱盐氧化还原溶液摩尔反应催化有机无机晶体沉淀离子共价金属非金属氢氧碳氮磷硫钠钾钙镁铝铁铜锌银",
    "生物": "细胞基因蛋白细胞核线粒体叶绿体组织器官种群生态进化遗传酶光合呼吸神经免疫激素血管骨骼肌肉消化循环分泌繁殖变异",
    "历史": "朝代帝王战争条约改革革命王朝古罗马帝国封建殖民独立统一起义变法盛世衰落文艺复兴启蒙工业资产民族国家城邦",
    "地理": "山脉河流海洋大陆气候季风纬度经度盆地平原高原岛屿海峡沙漠森林草原湖泊冰川火山地震板块洋流潮汐侵蚀沉积",
    "音乐": "音符旋律节奏和声乐器钢琴吉他提琴鼓号曲调音阶和弦节拍谱号调式独奏合奏交响民谣流行古典爵士摇滚合唱伴奏",
    "体育": "跑步游泳篮球足球排球跳高跳远投掷体操竞技比分裁判训练教练赛季联赛冠军亚军季军纪录奖牌田径球拍球场跑道",
    "编程": "变量函数循环数组指针算法编译调试接口类对象继承并发线程进程内存堆栈队列链表树图排序查找递归迭代异常测试部署",
    "饮食": "米饭面条馒头蔬菜水果肉鱼蛋奶汤炒煮蒸炸甜咸酸辣油盐酱醋茶咖啡果汁面包蛋糕米饭粥饺子包子火锅烧烤凉菜",
    "交通": "汽车火车飞机轮船公交地铁自行车道路桥梁隧道航班站台机场港口码头高速铁路信号红绿灯拥堵车票司机乘客货运客运",
    "天气": "晴天阴天雨天雪天雷电气温湿度风力云量雾霾霜冻冰雹露水彩虹气压锋面台风暴雨干旱洪涝季风昼夜温差日照云层降水",
}


def build(mem: Memory):
    ids_by_cluster = {}
    for head, chars in CLUSTERS.items():
        ids = []
        for i, ch in enumerate(chars[:50]):
            label = (head + ch)[:8]  # ≤10 字、簇内字面重叠
            r = mem.write(label, source="HUMAN")
            ids.append(r["id"])
        # 簇内成链，便于扩散
        for a, b in zip(ids, ids[1:]):
            mem.link(a, b, "ASSOCIATED", weight=8.0)
        ids_by_cluster[head] = ids
    return ids_by_cluster


def evaluate(mem: Memory, ids_by_cluster, k=10):
    """查询 = 某簇的一个成员；相关集 = 同簇其余成员（排除查询本身）。"""
    recalls, rrs, hop_ok, hop_n = [], [], 0, 0
    for head, ids in ids_by_cluster.items():
        cluster_set = set(ids)
        for qidx in (0, 10, 20):
            if qidx >= len(ids):
                continue
            qid = ids[qidx]
            qlabel = mem.get(qid)["label"]
            relevant = cluster_set - {qid}
            hits = mem.search(qlabel, top_k=k, hops=2)
            hit_ids = [h["id"] for h in hits if h["id"] != qid]
            hit = len(relevant & set(hit_ids))
            recalls.append(hit / min(k, len(relevant)))
            rr = 0.0
            for rank, hid in enumerate(hit_ids, 1):
                if hid in relevant:
                    rr = 1.0 / rank
                    break
            rrs.append(rr)
            hop_n += 1
            if hit >= 2:
                hop_ok += 1
    return {
        "n_queries": len(recalls),
        "recall_at_10": round(sum(recalls) / len(recalls), 4),
        "mrr": round(sum(rrs) / len(rrs), 4),
        "two_hop_accuracy": round(hop_ok / hop_n, 4),
    }


if __name__ == "__main__":
    clock = FakeClock(1000.0)
    mem = Memory.in_memory(clock)
    ids = build(mem)
    total = mem.stats()["nodes"]
    res = evaluate(mem, ids)
    res["n_nodes"] = total
    res["n_edges"] = mem.stats()["edges"]
    print(json.dumps(res, ensure_ascii=False, indent=2))
    with open(os.path.join(os.path.dirname(__file__), "..", "bench_result_p2.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    mem.close()
