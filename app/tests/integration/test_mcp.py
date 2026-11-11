"""MCP 协议集成测试（阶段5）：通过 FastMCP Client 走真实 MCP 协议调用工具。

写入只有唯一入口 memory_ingest（AI 拆分简写后落库，不建边）；
连接用 memory_link / memory_link_many；整理用 memory_reinforce/simplify/merge/consolidate。
"""
import pytest

fastmcp = pytest.importorskip("fastmcp")
from fastmcp import Client  # noqa: E402

from brainmem.interfaces import mcp_server  # noqa: E402


@pytest.mark.asyncio
async def test_mcp_tools_listed_and_callable():
    from brainmem.interfaces.memory import Memory

    mcp_server._MEM = Memory.in_memory()

    async with Client(mcp_server.mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert set(mcp_server.TOOL_NAMES).issubset(names), names
        assert len(mcp_server.TOOL_NAMES) == 14
        # 拆分/预览类工具已撤下（拆分是 AI 的事）
        for gone in ("memory_write", "memory_write_note", "memory_write_batch",
                     "memory_split_preview"):
            assert gone not in names

        # 写入（AI 已拆好，不建边）
        r = await client.call_tool("memory_ingest", {
            "atoms": ["六点钟起床差点迟到", "吃了两个包子出门"],
            "text": "早上六点半起床差点迟到，吃了两个包子出门。",
            "note_title": "早上",
        })
        rd = r.data if hasattr(r, "data") else r
        assert rd["atom_count"] == 2
        assert rd["note"]["saved"] is True
        st = await client.call_tool("memory_stats", {})
        std = st.data if hasattr(st, "data") else st
        assert std["nodes"] == 3            # 2 原子 + 1 note
        assert std["edges"] == 0            # 不自动建边
        a, b = rd["atoms"][0]["id"], rd["atoms"][1]["id"]

        # >10 字现在允许（字数由 AI 决定，库按字数给权重）
        long_r = await client.call_tool("memory_ingest", {"atoms": ["这是一个超过十个字的原子记忆内容"]})
        lrd = long_r.data if hasattr(long_r, "data") else long_r
        assert lrd["atom_count"] == 1
        assert float(lrd["atoms"][0]["weight"]) < 1.00

        # 连接（AI 决定）
        lk = await client.call_tool("memory_link", {"src": a, "dst": b, "relation": "SEQUENCE"})
        assert (lk.data if hasattr(lk, "data") else lk)["edge_id"]

        # 权重操作
        rf = await client.call_tool("memory_reinforce", {"node_id": a})
        assert (rf.data if hasattr(rf, "data") else rf)["id"] == a
        sm = await client.call_tool("memory_simplify", {"node_id": a, "new_text": "差点迟到"})
        assert (sm.data if hasattr(sm, "data") else sm)["changed"] is True

        # 用进废退：检索/取用自动加权重（不再有睡觉/整理入口）
        for gone in ("memory_curate", "memory_review"):
            assert gone not in names
        w_before = float((await client.call_tool("memory_get", {"node_id": b})).data["weight"])
        await client.call_tool("memory_search", {"query": "包子", "top_k": 3})
        w_after = float((await client.call_tool("memory_get", {"node_id": b})).data["weight"])
        assert w_after > w_before

        # 查询
        g = await client.call_tool("memory_get", {"node_id": a})
        assert (g.data if hasattr(g, "data") else g)["id"] == a
        s = await client.call_tool("memory_search", {"query": "起床", "top_k": 3})
        assert isinstance((s.data if hasattr(s, "data") else s), list)
        ex = await client.call_tool("memory_explain", {"node_id": a})
        assert (ex.data if hasattr(ex, "data") else ex)["id"] == a
        ins = await client.call_tool("memory_inspect", {"node_id": a})
        assert (ins.data if hasattr(ins, "data") else ins)["node"]["id"] == a

        # 反馈 / 删除
        fb = await client.call_tool("memory_feedback", {"node_id": a, "signal": "positive"})
        assert (fb.data if hasattr(fb, "data") else fb)["id"] == a
        fg = await client.call_tool("memory_forget", {"node_id": a, "mode": "hard"})
        assert (fg.data if hasattr(fg, "data") else fg)["deleted"] is True
