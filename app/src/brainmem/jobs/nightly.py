"""夜间巩固任务（阶段4）：封装 Consolidator，供调度器/CLI 调用。"""
from __future__ import annotations


def run_nightly(engine, weekly: bool = False) -> dict:
    from brainmem.engine.consolidation import Consolidator

    return Consolidator(engine).run_nightly(weekly=weekly)
