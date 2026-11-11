"""CLI（Typer）。命令与 MCP 工具一一对应，便于本地调试与脚本化。"""
from __future__ import annotations

import json

import typer

from brainmem.interfaces.memory import Memory

app = typer.Typer(help="brainmem · 仿脑记忆数据库 阶段1 记忆内核", no_args_is_help=True)


def _mem(config: str | None) -> Memory:
    return Memory.from_config(config)


@app.command()
def ingest(
    atoms: str = typer.Argument(..., help="逗号分隔的原子列表（每条字数自定，上限见 MAX_LABEL_CHARS=100）"),
    text: str | None = typer.Option(None, help="整段原文（可选，存一条冷存记忆）"),
    note_title: str | None = typer.Option(None, help="原文记忆标题（字数≤100）"),
    config: str | None = typer.Option(None, help="配置文件路径"),
) -> None:
    """写入记忆唯一入口：AI 已拆分简写好的原子批量入库（不建边）。"""
    m = _mem(config)
    atom_list = [a for a in atoms.split(",") if a.strip()]
    typer.echo(json.dumps(
        m.ingest(atom_list, text=text, note_title=note_title), ensure_ascii=False, indent=2))
    m.close()


@app.command()
def reinforce(node_id: str, config: str | None = typer.Option(None)) -> None:
    """给一条记忆加权重。"""
    m = _mem(config)
    typer.echo(json.dumps(m.reinforce(node_id), ensure_ascii=False))
    m.close()


@app.command()
def simplify(node_id: str, new_text: str, config: str | None = typer.Option(None)) -> None:
    """把一条记忆替换为更简写法并加权重。"""
    m = _mem(config)
    typer.echo(json.dumps(m.simplify(node_id, new_text), ensure_ascii=False))
    m.close()


@app.command()
def merge(ids: str, new_text: str, config: str | None = typer.Option(None)) -> None:
    """把多条记忆（逗号分隔 id）合并成一条并加权重。"""
    m = _mem(config)
    id_list = [i for i in ids.split(",") if i.strip()]
    typer.echo(json.dumps(m.merge(id_list, new_text), ensure_ascii=False))
    m.close()


@app.command()
def get(node_id: str, config: str | None = typer.Option(None)) -> None:
    """按 id 查询。"""
    m = _mem(config)
    typer.echo(json.dumps(m.get(node_id, include_verbatim=True), ensure_ascii=False))
    m.close()


@app.command()
def forget(node_id: str, mode: str = typer.Option("hard"), config: str | None = typer.Option(None)) -> None:
    """删除一条记忆。"""
    m = _mem(config)
    typer.echo(json.dumps(m.forget(node_id, mode), ensure_ascii=False))
    m.close()


@app.command()
def explain(node_id: str, config: str | None = typer.Option(None)) -> None:
    """解释一条记忆的权重来历。"""
    m = _mem(config)
    typer.echo(json.dumps(m.explain(node_id), ensure_ascii=False, indent=2))
    m.close()


@app.command()
def stats(config: str | None = typer.Option(None)) -> None:
    """统计信息。"""
    m = _mem(config)
    typer.echo(json.dumps(m.stats(), ensure_ascii=False, indent=2))
    m.close()


@app.command()
def reconcile(sample: float = typer.Option(1.0), config: str | None = typer.Option(None)) -> None:
    """事件复算对账。"""
    m = _mem(config)
    typer.echo(json.dumps(m.reconcile(sample), ensure_ascii=False, indent=2))
    m.close()


@app.command()
def search(
    query: str,
    top_k: int = typer.Option(4),
    hops: int = typer.Option(2),
    config: str | None = typer.Option(None),
) -> None:
    """扩散激活检索。"""
    m = _mem(config)
    typer.echo(json.dumps(m.search(query, top_k=top_k, hops=hops), ensure_ascii=False, indent=2))
    m.close()


@app.command()
def feedback(
    node_id: str,
    signal: str = typer.Option("positive", help="positive/negative"),
    config: str | None = typer.Option(None),
) -> None:
    """告诉系统这条记忆有用/没用（触发强化）。"""
    m = _mem(config)
    typer.echo(json.dumps(m.feedback(node_id, signal), ensure_ascii=False))
    m.close()


@app.command()
def link(
    src: str,
    dst: str,
    relation: str = typer.Option("ASSOCIATED"),
    config: str | None = typer.Option(None),
) -> None:
    """建边（连谁由你判断，权重由记忆库给）。"""
    m = _mem(config)
    typer.echo(json.dumps(m.link(src, dst, relation), ensure_ascii=False))
    m.close()


@app.command()
def inspect(node_id: str, config: str | None = typer.Option(None)) -> None:
    """查看一条记忆的全部数据 + 所有关联边（含对端与边权）。"""
    m = _mem(config)
    typer.echo(json.dumps(m.inspect(node_id), ensure_ascii=False, indent=2))
    m.close()


@app.command(name="list")
def list_nodes(config: str | None = typer.Option(None)) -> None:
    """列出全部记忆（id / 标签 / 权重 / 状态 / 连接数 / 还能活多久）。"""
    m = _mem(config)
    rows = m.list_nodes()
    # 表格化输出
    typer.echo(f"{'id':26} {'标签':14} {'权重':>6} {'状态':10} {'连接':>4} {'剩余天数':>7}")
    typer.echo("-" * 78)
    for r in rows:
        typer.echo(f"{r['id']:26} {r['label']:14} {r['weight']:>6} {r['state']:10} "
                   f"{r['degree']:>4} {r['days_to_zero']:>7}")
    typer.echo(f"\n共 {len(rows)} 条记忆")
    m.close()


@app.command()
def graph(
    out: str = typer.Option("relationship.html", help="输出 HTML 文件路径"),
    focus: str | None = typer.Option(None, help="只显示与某条记忆直接相连的子图"),
    open_browser: bool = typer.Option(False, "--open", help="生成后自动用浏览器打开"),
    view: str = typer.Option("2d", "--view", help="视图：2d（力导向星空）/ 3d（3D 星系）"),
    config: str | None = typer.Option(None),
) -> None:
    """导出记忆可视化（2d 力导向星空 / 3d 三维星图），双击浏览器打开。"""
    import os

    if view == "3d":
        from brainmem.interfaces.viz_3d import export_graph_html
        m = _mem(config)
        path = export_graph_html(m.engine, out, focus)
        m.close()
    elif view == "2d":
        # 2D 视图直接读 SQLite（与 WorkBuddy 版同源），通过环境变量传参
        import sys
        import runpy
        if config:
            import json as _json
            cfg = _json.load(open(config, encoding="utf-8-sig"))
            sp = cfg.get("sqlite_path", "")
            sp = sp.replace("%LOCALAPPDATA%", os.environ.get("LOCALAPPDATA", ""))
            if sp:
                os.environ["BRAINMEM_DB"] = sp
        os.environ["BRAINMEM_OUT"] = out
        os.environ["BRAINMEM_NO_OPEN"] = "1"
        mod_path = os.path.join(os.path.dirname(__file__), "viz_2d.py")
        runpy.run_path(mod_path, run_name="__main__")
        path = os.path.abspath(out)
    else:
        typer.echo(f"未知视图: {view}（可用 2d / 3d）")
        raise typer.Exit(1)

    typer.echo(f"记忆可视化已生成（{view}）: {path}")
    if open_browser:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception:
            pass


@app.command()
def merge_undo(batch_id: str, config: str | None = typer.Option(None)) -> None:
    """按批次一键回滚合并。"""
    m = _mem(config)
    typer.echo(json.dumps(m.merge_undo(batch_id), ensure_ascii=False, indent=2))
    m.close()


@app.command()
def sweep(
    apply: bool = typer.Option(False, "--apply", help="真正执行删除（默认只预览 dry-run）"),
    config: str | None = typer.Option(None),
) -> None:
    """归零清理：把权重已衰减到 0 的记忆物理删除（连边、清冷存）。默认只预览。"""
    m = _mem(config)
    res = m.sweep_expired(dry_run=not apply)
    mode = "真删" if apply else "预览(dry-run)"
    typer.echo(f"[{mode}] 扫描 {res['scanned']} 条，已归零 {res['expired']} 条，本次删除 {res['deleted']} 条")
    for it in res["items"]:
        typer.echo(f"  - {it['label'][:30]}  (w_bp={it['weight_bp']}, 静置 {it['days_since_touch']} 天, 原文{'有' if it['has_verbatim'] else '无'})")
    if not apply and res["expired"]:
        typer.echo("（以上为预览，加 --apply 才真正删除）")
    m.close()


# 注：原 `normalize` 命令（全局乘性归一）已移除，见 engine/consolidation.py 顶部说明。


if __name__ == "__main__":
    app()
