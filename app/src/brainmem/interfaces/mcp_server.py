"""MCP Server（阶段5）：把 brainmem 暴露为一组 MCP 工具。

上传记忆只有唯一入口 memory_ingest（强制走拆分简写流程）；其余为检索/维护工具。
- stdio：`python -m brainmem.interfaces.mcp_server`
- SSE/HTTP：`python -m brainmem.interfaces.mcp_server --transport http --port 8770`
每个工具只做协议翻译，业务全部走 Memory 门面。
"""
from __future__ import annotations

import os

from fastmcp import FastMCP

from brainmem.config import load_config
from brainmem.interfaces.memory import Memory

mcp = FastMCP("brainmem")

_MEM: Memory | None = None


def _mem() -> Memory:
    global _MEM
    if _MEM is None:
        cfg_path = os.environ.get("BRAINMEM_CONFIG")
        _MEM = Memory.from_config(cfg_path)
    return _MEM


# ----------------------------------------------------- 唯一写入入口 + 查询/维护
@mcp.tool
def memory_ingest(
    atoms: list[str],
    text: str | None = None,
    note_title: str | None = None,
    source: str = "AI",
    max_chars: int | None = None,
) -> dict:
    """**写入记忆的唯一入口（AI 上传必走此工具）。**

    职责边界：**拆分 / 简写 / 建连接全部由你（AI）完成**，本工具只负责入库与权重。
    - atoms：你重组好的原子列表。**每条写多长由你自己决定**（不强制 10 字；上限见系统默认
      MAX_LABEL_CHARS）。库按字数给初始权重：字数越少权重越高、越难忘，字数越多权重越低、越易忘。
      保序去重后写入；重复写入同一条 = 强化（加权重）。
    - text：可选。整段原文；给了就额外存一条冷存记忆（标题用 note_title，否则取首条原子）。
    - 本工具**不建任何边**：连接请你另调 memory_link / memory_link_many。

    拆分简写原则见 skill brainmem-upload：删元叙述/纯感想、并碎句成整句、每条留可降级内核。
    """
    return _mem().ingest(atoms, text=text, note_title=note_title,
                         source=source, max_chars=max_chars)


@mcp.tool
def memory_reinforce(node_id: str, source: str = "AI") -> dict:
    """给一条记忆加权重（重复录入/回顾/有用）。库只算权重。"""
    return _mem().reinforce(node_id, source=source)


@mcp.tool
def memory_simplify(node_id: str, new_text: str, source: str = "AI") -> dict:
    """把一条记忆替换为更简写法并加权重（AI 主动压缩时用）。
    记忆变糊后压成更短内核（如「六点钟起床差点迟到」→「差点迟到」）。"""
    return _mem().simplify(node_id, new_text, source=source)


@mcp.tool
def memory_merge(node_ids: list[str], new_text: str, source: str = "AI",
                 mode: str = "soft") -> dict:
    """把多条记忆合并成一个**更概括的父记忆**（标题 ≤100 字）并加权重。

    **软合并**：新建父记忆（标题=new_text），用 MEMBER_OF 边把原记忆全部挂在父节点下——
    **成员一条不删、原文不丢、它们之间的连接原样都在**。检索命中父标题后可展开看到
    "原来几条记忆连在一起的样子"及各自完整原文；可用返回的 batch_id 做 merge_undo 回滚。
    这是记忆长文本/可复原的正道。（硬合并已移除——它会删成员、丢原文。）

    前置条件（计划书 6.3）：待合并记忆之间必须已由「强连接」连通——边权≥8.00、
    共激活≥5、且该连接自身寿命≥365 天，否则拒绝。先 memory_link 反复加强，够了再合并。"""
    return _mem().merge(node_ids, new_text, source=source, mode=mode)


@mcp.tool
def memory_search(query: str, top_k: int = 4, hops: int = 2, min_weight: float = 0.0,
                  use: bool = True) -> list[dict]:
    """扩散激活检索：返回含 label/gist/weight/state/score 的记忆。

    **用进废退**：`use=True`（默认）时，检索命中的记忆各 +权重、检索走过的连接也 +权重并记一次共激活
    ——即"每次调用记忆/用到连接就增加权重"。`use=False` 只读（对账/纯查询用）。"""
    return _mem().search(query, top_k=top_k, hops=hops, min_weight=min_weight, use=use)


@mcp.tool
def memory_get(node_id: str, include_verbatim: bool = False, use: bool = False) -> dict:
    """按 id 取记忆详情与版本数。
    `use=True` 表示这条记忆被实际取用 → 自动给它加权重（用进废退）。"""
    if use:
        _mem().feedback(node_id, signal="positive", context="use:get")
    return _mem().get(node_id, include_verbatim=include_verbatim)


@mcp.tool
def memory_feedback(node_id: str, signal: str = "positive", context: str = "") -> dict:
    """告诉系统这条记忆有用/没用（positive 触发强化与共激活）。"""
    return _mem().feedback(node_id, signal=signal, context=context)


@mcp.tool
def memory_link(src: str, dst: str, relation: str = "ASSOCIATED") -> dict:
    """在两条记忆之间建立连接。**连谁由你（AI）判断，权重由记忆库决定**——
    你只需给出两端 id 和关系类型，不要传权重。已存在的边会按同关系累加并计共激活。
    relation 可选：ASSOCIATED / CAUSES / PART_OF / SEQUENCE 等。
    """
    return _mem().link(src, dst, relation=relation)


@mcp.tool
def memory_link_many(pairs: list[dict]) -> list[dict]:
    """批量建边。pairs 为 [{"src": id, "dst": id, "relation": "ASSOCIATED"?}, ...]。
    同样：连谁由你判断，权重全部由记忆库给。
    """
    return _mem().link_many(pairs)


@mcp.tool
def memory_forget(node_id: str, mode: str = "hard") -> dict:
    """删除一条记忆（hard=物理删除，soft=仅调试）。"""
    return _mem().forget(node_id, mode=mode)


@mcp.tool
def memory_stats(tenant: str | None = None) -> dict:
    """统计：节点/边数、平均权重、状态分布。"""
    return _mem().stats(tenant)


@mcp.tool
def memory_explain(node_id: str) -> dict:
    """解释一条记忆的权重来历（事件摘要 + 衰减计算过程）。"""
    return _mem().explain(node_id)


@mcp.tool
def memory_inspect(node_id: str) -> dict:
    """查看一条记忆的全部数据：字段、权重、状态、可解释、全部事件、所有关联边（含对端）。"""
    return _mem().inspect(node_id)


TOOL_NAMES = [
    "memory_ingest", "memory_reinforce", "memory_simplify", "memory_merge",
    "memory_search", "memory_get", "memory_feedback", "memory_link",
    "memory_link_many", "memory_forget", "memory_stats", "memory_explain",
    "memory_inspect",
]


def main() -> None:
    import sys

    transport = "stdio"
    if "--transport" in sys.argv:
        transport = sys.argv[sys.argv.index("--transport") + 1]
    if transport in ("http", "sse", "streamable-http"):
        mcp.run(transport="http", host="127.0.0.1", port=8770)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
