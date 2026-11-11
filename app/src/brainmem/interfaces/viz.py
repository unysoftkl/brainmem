# -*- coding: utf-8 -*-
"""关系图可视化：把记忆节点与关联边导出为**单文件交互式 HTML（内嵌 SVG + 少量 JS）**。

零依赖（不需要 matplotlib/JS 库），双击即可用浏览器打开；节点颜色按状态，
节点大小按权重，连线粗细按边权，鼠标悬停显示详情，可拖动、可缩放。
"""
from __future__ import annotations

import html
import json
import math
import os

from brainmem.core.decay import BP, decay_bp, show
from brainmem.core.enums import STATE_LEVEL, State
from brainmem.core.lifecycle import state_of

STATE_COLOR = {
    "FULL": "#2e7d32",       # 绿
    "NORMAL": "#1565c0",     # 蓝
    "CONDENSED": "#ef6c00",  # 橙
    "VESTIGE": "#c62828",    # 红
    "DELETED": "#9e9e9e",
}


def _layout(nodes: list[str], edges: list[dict], width: int, height: int) -> dict[str, tuple[float, float]]:
    """简易力导向布局（纯 Python，固定迭代次数）。degree 越高越靠中心。"""
    n = len(nodes)
    if n == 0:
        return {}
    pos = {}
    # 初始环形
    for i, nid in enumerate(nodes):
        ang = 2 * math.pi * i / n
        pos[nid] = [width / 2 + min(width, height) * 0.35 * math.cos(ang),
                    height / 2 + min(width, height) * 0.35 * math.sin(ang)]
    deg = {nid: 0 for nid in nodes}
    for e in edges:
        if e["src"] in deg:
            deg[e["src"]] += 1
        if e["dst"] in deg:
            deg[e["dst"]] += 1
    k = math.sqrt((width * height) / max(1, n))
    # 力导向迭代
    for _ in range(120):
        disp = {nid: [0.0, 0.0] for nid in nodes}
        # 排斥
        for i in range(n):
            for j in range(i + 1, n):
                a, b = nodes[i], nodes[j]
                dx = pos[a][0] - pos[b][0]
                dy = pos[a][1] - pos[b][1]
                d2 = dx * dx + dy * dy + 0.01
                f = k * k / d2
                disp[a][0] += dx * f
                disp[a][1] += dy * f
                disp[b][0] -= dx * f
                disp[b][1] -= dy * f
        # 吸引
        for e in edges:
            a, b = e["src"], e["dst"]
            if a not in pos or b not in pos:
                continue
            dx = pos[a][0] - pos[b][0]
            dy = pos[a][1] - pos[b][1]
            d = math.sqrt(dx * dx + dy * dy) + 0.01
            f = (d * d) / k
            disp[a][0] -= dx / d * f
            disp[a][1] -= dy / d * f
            disp[b][0] += dx / d * f
            disp[b][1] += dy / d * f
        # 向心力（度高的更靠中）
        for nid in nodes:
            cd = deg.get(nid, 0)
            pull = 0.02 + 0.02 * min(5, cd)
            disp[nid][0] += (width / 2 - pos[nid][0]) * pull
            disp[nid][1] += (height / 2 - pos[nid][1]) * pull
        # 应用，限幅
        for nid in nodes:
            dl = math.sqrt(disp[nid][0] ** 2 + disp[nid][1] ** 2) + 0.01
            lim = 40.0
            pos[nid][0] += disp[nid][0] / dl * min(dl, lim)
            pos[nid][1] += disp[nid][1] / dl * min(dl, lim)
            pos[nid][0] = max(60, min(width - 60, pos[nid][0]))
            pos[nid][1] = max(60, min(height - 60, pos[nid][1]))
    return {nid: (pos[nid][0], pos[nid][1]) for nid in nodes}


def build_graph_data(engine, focus: str | None = None) -> dict:
    tenant = engine.tenant
    now = engine.clock.now_day()
    all_nodes = engine.storage.list_nodes(tenant)
    edges = engine.storage.all_edges(tenant)

    nodes_out = []
    if focus:
        # 子图：focus 及其一跳邻居
        keep = {focus}
        for e in edges:
            if e.src_id == focus:
                keep.add(e.dst_id)
            elif e.dst_id == focus:
                keep.add(e.src_id)
    else:
        keep = {n.id for n in all_nodes}

    for n in all_nodes:
        if n.id not in keep:
            continue
        w = decay_bp(n.weight_bp, n.stability, now - n.last_touch_at, engine.p)
        nodes_out.append({
            "id": n.id, "label": n.label, "weight": show(w),
            "weight_num": round(w / BP, 3), "state": state_of(w).value,
            "kind": n.kind.value, "degree": 0,
        })
    id_set = {x["id"] for x in nodes_out}
    edges_out = []
    for e in edges:
        if e.src_id in id_set and e.dst_id in id_set:
            edges_out.append({
                "src": e.src_id, "dst": e.dst_id, "relation": e.relation.value,
                "weight": round(e.weight_bp / BP, 2), "coact": e.coactivation,
            })
    deg = {x["id"]: 0 for x in nodes_out}
    for e in edges_out:
        deg[e["src"]] += 1
        deg[e["dst"]] += 1
    for x in nodes_out:
        x["degree"] = deg[x["id"]]
    return {"nodes": nodes_out, "edges": edges_out,
            "stats": {"nodes": len(nodes_out), "edges": len(edges_out), "focus": focus}}


def export_graph_html(engine, out_path: str, focus: str | None = None) -> str:
    data = build_graph_data(engine, focus)
    nodes = [x["id"] for x in data["nodes"]]
    W, H = 1400, 900
    pos = _layout(nodes, data["edges"], W, H)
    idx = {x["id"]: x for x in data["nodes"]}

    # 预生成 SVG 片段
    edge_svg = []
    for e in data["edges"]:
        if e["src"] not in pos or e["dst"] not in pos:
            continue
        x1, y1 = pos[e["src"]]
        x2, y2 = pos[e["dst"]]
        # 顶点裁剪，避免压住节点圆
        r1 = 8 + min(14, idx[e["src"]]["degree"] * 2)
        r2 = 8 + min(14, idx[e["dst"]]["degree"] * 2)
        dx, dy = x2 - x1, y2 - y1
        d = math.hypot(dx, dy) or 1
        sx, sy = x1 + dx / d * (r1 + 2), y1 + dy / d * (r1 + 2)
        ex, ey = x2 - dx / d * (r2 + 2), y2 - dy / d * (r2 + 2)
        sw = max(0.6, min(4.0, e["weight"] / 2.5))
        midx, midy = (sx + ex) / 2, (sy + ey) / 2
        edge_svg.append(
            f'<line class="edge" x1="{sx:.1f}" y1="{sy:.1f}" x2="{ex:.1f}" y2="{ey:.1f}" '
            f'stroke="#90a4ae" stroke-width="{sw:.2f}" data-src="{e["src"]}" data-dst="{e["dst"]}" '
            f'data-rel="{html.escape(e["relation"])}" data-w="{e["weight"]}" data-coact="{e["coact"]}"/>'
            f'<text class="elabel" x="{midx:.1f}" y="{midy:.1f}">{html.escape(e["relation"][:6])}·{e["weight"]:.1f}</text>'
        )

    node_svg = []
    for nid in nodes:
        x, y = pos[nid]
        n = idx[nid]
        r = 8 + min(14, n["degree"] * 2)
        color = STATE_COLOR.get(n["state"], "#888")
        node_svg.append(
            f'<g class="node" transform="translate({x:.1f},{y:.1f})" '
            f'data-id="{nid}" data-label="{html.escape(n["label"])}" data-weight="{n["weight"]}" '
            f'data-state="{n["state"]}" data-kind="{n["kind"]}" data-degree="{n["degree"]}">'
            f'<circle r="{r}" fill="{color}" stroke="#fff" stroke-width="1.5"/>'
            f'<text class="nlabel" y="{-(r+6)}">{html.escape(n["label"])}</text>'
            f'</g>'
        )

    legend = " ".join(
        f'<span style="color:{c}">●</span> {s}' for s, c in STATE_COLOR.items()
    )

    doc = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>brainmem 记忆关系图</title>
<style>
  body{{margin:0;font-family:"Microsoft YaHei",system-ui,sans-serif;background:#0f1419;color:#e0e0e0}}
  #bar{{padding:10px 16px;background:#1a2332;border-bottom:1px solid #2a3a4a;font-size:14px}}
  #bar b{{color:#4fc3f7}}
  #legend{{margin-left:18px}} #legend span{{font-size:13px}}
  svg{{display:block;cursor:grab}} svg:active{{cursor:grabbing}}
  .node{{cursor:pointer}}
  .nlabel{{fill:#e8eaed;font-size:11px;text-anchor:middle;pointer-events:none;text-shadow:0 1px 2px #000}}
  .elabel{{fill:#607d8b;font-size:8px;text-anchor:middle;pointer-events:none}}
  .edge{{transition:stroke .1s}}
  .edge.hl{{stroke:#ffca28;stroke-width:4}}
  #tip{{position:fixed;pointer-events:none;background:#1a2332ee;border:1px solid #4fc3f7;
        border-radius:6px;padding:8px 10px;font-size:12px;line-height:1.5;display:none;max-width:340px;z-index:9}}
  #hint{{position:fixed;right:14px;bottom:12px;font-size:11px;color:#546e7a}}
</style></head>
<body>
<div id="bar"><b>brainmem 记忆关系图</b>
  节点 {data['stats']['nodes']} 个 · 关联 {data['stats']['edges']} 条{('<span style="color:#ffca28"> · 聚焦子图</span>' if focus else '')}
  <span id="legend">{legend}</span>
</div>
<svg id="svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <g id="edges">{''.join(edge_svg)}</g>
  <g id="nodes">{''.join(node_svg)}</g>
</svg>
<div id="tip"></div>
<div id="hint">滚轮缩放 · 拖动平移 · 悬停节点高亮相连 · 点击节点复制 id</div>
<script>
const svg=document.getElementById('svg'), gE=document.getElementById('edges'),
      gN=document.getElementById('nodes'), tip=document.getElementById('tip');
let scale=1,tx=0,ty=0,drag=false,lx=0,ly=0;
const vb=svg.getAttribute('viewBox').split(' ').map(Number);
function apply(){{svg.setAttribute('viewBox',[vb[0]-tx/scale,vb[1]-ty/scale,vb[2]/scale,vb[3]/scale].join(' '));}}
svg.addEventListener('wheel',e=>{{e.preventDefault();scale*=e.deltaY<0?1.12:0.89;scale=Math.max(.2,Math.min(4,scale));apply();}},{{passive:false}});
svg.addEventListener('mousedown',e=>{{drag=true;lx=e.clientX;ly=e.clientY;}});
window.addEventListener('mouseup',()=>drag=false);
window.addEventListener('mousemove',e=>{{if(!drag)return;tx-=e.clientX-lx;ty-=e.clientY-ly;lx=e.clientX;ly=e.clientY;apply();}});
function hl(id){{document.querySelectorAll('.edge').forEach(el=>{{
  el.classList.toggle('hl', el.dataset.src===id||el.dataset.dst===id);}});}}
document.querySelectorAll('.node').forEach(nd=>{{
  nd.addEventListener('mouseenter',e=>{{
    const d=nd.dataset;
    tip.innerHTML='<b style="color:#4fc3f7">'+d.label+'</b><br>'+d.id+'<br>权重 <b>'+d.weight+
      '</b> · 状态 <b>'+d.state+'</b><br>类型 '+d.kind+' · 连接 '+d.degree+' 条';
    tip.style.display='block';hl(d.id);
  }});
  nd.addEventListener('mousemove',e=>{{tip.style.left=(e.clientX+14)+'px';tip.style.top=(e.clientY+14)+'px';}});
  nd.addEventListener('mouseleave',()=>{{tip.style.display='none';hl(null);}});
  nd.addEventListener('click',e=>{{navigator.clipboard&&navigator.clipboard.writeText(nd.dataset.id);
    tip.innerHTML='<b style="color:#66bb6a">已复制 id</b><br>'+nd.dataset.id;tip.style.display='block';}});
}});
</script>
</body></html>"""

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc)
    return os.path.abspath(out_path)
