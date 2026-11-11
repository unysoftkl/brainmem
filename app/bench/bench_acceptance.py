# -*- coding: utf-8 -*-
"""阶段1 验收脚本（对应《工程实施计划书》阶段1 验收标准 / UC-16）。

产出：
  1. 10 万事件复算 100 次，每次与在线状态 100% 一致（bit-level）。
  2. 单节点写入 P95（内存 SQLite）。
  3. 事件自洽率。
输出 JSON 供阶段报告引用。
"""
import json
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from brainmem.core.decay import bp
from brainmem.core.enums import EventType
from brainmem.core.models import WeightEvent
from brainmem.core.params import DEFAULT_PARAMS as P
from brainmem.core.weights import reinforce
from brainmem.engine.events import replay
from brainmem.core.time import FakeClock
from brainmem.interfaces.memory import Memory


def gen_events(n: int, seed: int = 42):
    """生成 n 条混合事件（create/reinforce/decay），保证事件自洽。"""
    rnd = random.Random(seed)
    events = []
    cur = bp(6.0)
    s = 0
    peak = cur
    for i in range(n):
        r = rnd.random()
        before = cur
        if r < 0.45:  # reinforce
            cur, s, peak, _ = reinforce(cur, s, peak, days_since=rnd.uniform(0, 20), p=P)
            et = EventType.REINFORCE
        else:  # decay
            cur = max(0, cur - rnd.randint(1, 3000))
            et = EventType.DECAY
        events.append(
            WeightEvent(
                seq=i + 1, entity_kind="NODE", entity_id="bench", event_type=et,
                delta_bp=cur - before, before_bp=before, after_bp=cur,
                reason="bench", actor="sys", at_day=float(i), at_real=i,
            )
        )
    return events


def bench_replay(n_events: int = 100000, rounds: int = 100):
    events = gen_events(n_events)
    truth = events[-1].after_bp
    # 自洽率
    consistent = sum(1 for e in events if e.after_bp == e.before_bp + e.delta_bp)
    t0 = time.perf_counter()
    ok = 0
    for _ in range(rounds):
        if replay(events) == truth:
            ok += 1
    t1 = time.perf_counter()
    return {
        "n_events": n_events,
        "rounds": rounds,
        "consistent_ratio": consistent / n_events,
        "replay_match_rounds": ok,
        "replay_match_ratio": ok / rounds,
        "total_seconds": round(t1 - t0, 3),
        "per_replay_ms": round((t1 - t0) / rounds * 1000, 2),
    }


def bench_write(n: int = 10000):
    clock = FakeClock(1000.0)
    m = Memory.in_memory(clock)
    lat = []
    t_all = time.perf_counter()
    for i in range(n):
        t0 = time.perf_counter()
        m.write(f"记{i}")  # 唯一短标签，走新建
        lat.append((time.perf_counter() - t0) * 1000)
    total = time.perf_counter() - t_all
    m.close()
    lat.sort()
    p = lambda q: lat[min(len(lat) - 1, int(q * len(lat)))]
    return {
        "n": n,
        "p50_ms": round(statistics.median(lat), 3),
        "p95_ms": round(p(0.95), 3),
        "p99_ms": round(p(0.99), 3),
        "throughput_per_s": round(n / total, 1),
    }


if __name__ == "__main__":
    out = {
        "replay": bench_replay(100000, 100),
        "write": bench_write(10000),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    with open(os.path.join(os.path.dirname(__file__), "..", "bench_result.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
