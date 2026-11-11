"""3D 记忆星图（v3 · 参考 tideglass 的 3D-Force-Graph 方案）

- 3D 球状星系：记忆节点按权重/时间分布在三维空间
- 流光粒子：连线带流动粒子，展示关系方向
- 时间轴回溯：拖动滑块，看某个时间点的记忆网络
- 点击节点：相机飞向该节点并显示详情
- 离线可用：把 3d-force-graph 库内嵌进 HTML，不依赖外网

生成：brainmem graph --out xxx.html --view 3d
"""
from __future__ import annotations

import json
import os
import time

from brainmem.core.decay import BP, decay_bp, show
from brainmem.core.lifecycle import state_of

STATE_COLOR = {
    "FULL": "#8CFFB0",
    "NORMAL": "#5EC8FF",
    "CONDENSED": "#FFC24B",
    "VESTIGE": "#FF7B7B",
    "DELETED": "#666666",
}
REL_COLOR = {
    "ASSOCIATED": "#8FB4FF",
    "SEQUENCE": "#5EE0C8",
    "CAUSES": "#FF9F43",
    "PART_OF": "#C792EA",
}
HERE = os.path.dirname(os.path.abspath(__file__))
VENDOR_JS = os.path.join(HERE, "_vendor", "3d-force-graph.min.js")


def build_graph_data(engine, focus: str | None = None) -> dict:
    tenant = engine.tenant
    now = engine.clock.now_day()
    all_nodes = engine.storage.list_nodes(tenant)
    edges = engine.storage.all_edges(tenant)
    if focus:
        keep = {focus}
        for e in edges:
            if e.src_id == focus:
                keep.add(e.dst_id)
            elif e.dst_id == focus:
                keep.add(e.src_id)
    else:
        keep = {n.id for n in all_nodes}
    nodes_out = []
    for n in all_nodes:
        if n.id not in keep:
            continue
        w = decay_bp(n.weight_bp, n.stability, now - n.last_touch_at, engine.p)
        nodes_out.append({
            "id": n.id, "label": n.label, "weight": show(w),
            "weight_num": round(w / BP, 3), "state": state_of(w).value,
            "kind": n.kind.value, "degree": 0,
            "born_at": float(n.born_at), "last_touch_at": float(n.last_touch_at),
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


def export_graph_html(engine, out_path: str, focus: str | None = None, view: str = "3d") -> str:
    data = build_graph_data(engine, focus)
    doc = _render3d(data, focus)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return os.path.abspath(out_path)


def _render3d(data: dict, focus: str | None) -> str:
    lib = ""
    if os.path.exists(VENDOR_JS):
        with open(VENDOR_JS, "r", encoding="utf-8") as fh:
            lib = fh.read()
    nodes = data["nodes"]
    edges = data["edges"]
    n = len(nodes)
    days = [x["born_at"] for x in nodes]
    d_min = min(days) if days else 0.0
    d_max = max(days) if days else 1.0

    def fmt_day(ts):
        return time.strftime("%Y-%m-%d", time.localtime(ts * 86400.0))

    # 给节点算三维位置：按时间分球壳半径（新的在内，旧的在外），角度按 id 散列
    payload_nodes = []
    for x in nodes:
        payload_nodes.append({
            "id": x["id"], "label": x["label"], "group": x["state"],
            "val": 1 + x["weight_num"] * 3,  # 节点大小
            "born_at": x["born_at"], "degree": x["degree"],
            "weight_num": x["weight_num"], "state": x["state"],
        })
    payload_links = [{"source": e["src"], "target": e["dst"], "rel": e["relation"],
                      "w": e["weight"]} for e in edges]
    payload = json.dumps({"nodes": payload_nodes, "links": payload_links,
                          "colors": STATE_COLOR, "relColors": REL_COLOR,
                          "dmin": d_min, "dmax": d_max}, ensure_ascii=False)

    status_count = {}
    for x in nodes:
        status_count[x["state"]] = status_count.get(x["state"], 0) + 1
    legend = "".join(
        f'<div class="lg"><i style="background:{STATE_COLOR[s]}"></i>{s} {c}</div>'
        for s, c in sorted(status_count.items(), key=lambda kv: -kv[1]))

    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>brainmem · 3D 记忆星图</title>
<style>
  *{{box-sizing:border-box}}
  html,body{{margin:0;height:100%;overflow:hidden;background:#050810;color:#dfe9ff;
    font-family:-apple-system,"Segoe UI","Microsoft YaHei",system-ui,sans-serif}}
  #graph{{position:absolute;inset:0}}
  #hud{{position:absolute;left:20px;top:18px;pointer-events:none;z-index:10}}
  #hud h1{{font-size:18px;margin:0 0 4px;font-weight:600}}
  #hud h1 b{{color:#6ee7ff}}
  #hud .sub{{font-size:12px;color:#7f92b5}}
  #panel{{position:absolute;left:20px;bottom:20px;z-index:10;background:rgba(10,16,30,.82);
    border:1px solid #1e2a44;border-radius:12px;padding:14px 16px;width:270px;backdrop-filter:blur(8px)}}
  #panel h3{{font-size:12px;color:#6ee7ff;margin:0 0 8px;font-weight:600}}
  #panel input[type=range]{{width:100%;accent-color:#6ee7ff}}
  #panel .row{{display:flex;justify-content:space-between;font-size:11.5px;color:#8fa3c8;margin:4px 0}}
  #legend{{margin-top:10px;display:flex;flex-wrap:wrap;gap:8px}}
  .lg{{display:flex;align-items:center;gap:5px;font-size:11px;color:#8fa3c8}}
  .lg i{{width:8px;height:8px;border-radius:50%;display:inline-block}}
  #detail{{position:absolute;right:20px;top:20px;z-index:10;width:240px;background:rgba(10,16,30,.86);
    border:1px solid #1e2a44;border-radius:12px;padding:14px 16px;display:none;backdrop-filter:blur(8px)}}
  #detail .t{{font-size:14px;color:#fff;margin-bottom:8px;word-break:break-all}}
  #detail .row{{font-size:12px;color:#8fa3c8;margin:4px 0}}
  #detail .row b{{color:#dfe9ff;font-weight:500}}
  #stats{{position:absolute;right:20px;bottom:20px;z-index:10;background:rgba(10,16,30,.72);
    border:1px solid #1e2a44;border-radius:12px;padding:10px 14px;font-size:11.5px;color:#8fa3c8}}
  #stats b{{color:#6ee7ff}}
  #hint{{position:absolute;left:50%;bottom:16px;transform:translateX(-50%);z-index:10;font-size:11px;color:#5f7297}}
</style></head>
<body>
<div id="graph"></div>
<div id="hud"><h1>brainmem · <b>3D 记忆星图</b></h1>
  <div class="sub">{n} 个记忆 · {len(edges)} 条关联 · {fmt_day(d_min)} ~ {fmt_day(d_max)}</div></div>
<div id="panel">
  <h3>⏳ 时间轴回溯</h3>
  <input id="time" type="range" min="0" max="100" value="100" />
  <div class="row"><span id="tlabel">全部</span><span>拖动回看记忆生长</span></div>
  <div id="legend">{legend}</div>
</div>
<div id="detail"></div>
<div id="stats">记忆 <b>{n}</b> · 关联 <b>{len(edges)}</b></div>
<div id="hint">拖动旋转 · 滚轮缩放 · 点击节点飞向详情 · 拖动时间轴回溯</div>
<script>{lib}</script>
<script>
const DATA = {payload};
const COLORS = DATA.colors;
const dmin = DATA.dmin, dmax = DATA.dmax;
const gEl = document.getElementById('graph');

// 按时间分配到三个球壳：新→内壳，旧→外壳
const NN = DATA.nodes.length;
const order = [...DATA.nodes].sort((a,b)=>a.born_at-b.born_at); // 旧→新
const rank = {{}}; order.forEach((nd,i)=>rank[nd.id]=i/Math.max(1,NN-1)); // 0旧 1新
function hash01(s){{ let h=2166136261; for(const c of s){{h=(h^c.charCodeAt(0))*16777619>>>0;}} return (h%1000003)/1000003; }}

const NODES = DATA.nodes.map(nd=>{{
  const r0 = 1 - (rank[nd.id]||0); // 0新 1旧
  const shell = 18 + 110 * Math.pow(r0, 0.8);   // 旧=外壳（收紧，避免出屏）
  const th = hash01(nd.id)*Math.PI*2;
  const ph = Math.acos(2*hash01(nd.id+'p')-1);
  const rr = shell * (0.88 + 0.22*hash01(nd.id+'r'));
  return {{
    id: nd.id, label: nd.label, group: nd.state, val: nd.val, born_at: nd.born_at,
    degree: nd.degree, weight_num: nd.weight_num, state: nd.state,
    x: rr*Math.sin(ph)*Math.cos(th), y: rr*Math.cos(ph)*0.8, z: rr*Math.sin(ph)*Math.sin(th)
  }};
}});
const LINKS = DATA.links.map(l=>({{source:l.source, target:l.target, rel:l.rel, w:l.w}}));

const Graph = ForceGraph3D()(gEl)
  .backgroundColor('#050810')
  .graphData({{nodes:NODES, links:LINKS}})
  .nodeVal(n=>n.val)
  .nodeRelSize(5.5)
  .nodeResolution(14)
  .nodeColor(n=>COLORS[n.state]||'#8FB4FF')
  .nodeLabel(n=>`<div style="padding:6px 9px;background:rgba(0,0,0,.85);border-radius:6px;font-size:12px">${{n.label}}<br><span style="color:#8fa3c8">${{n.state}} · 权重${{n.weight_num}}</span></div>`)
  .nodeOpacity(0.92)
  .linkColor(l=>DATA.relColors[l.rel]||'rgba(143,180,255,0.25)')
  .linkWidth(l=>Math.max(0.3, 0.2 + (l.w||0)*0.4))
  .linkOpacity(0.35)
  .linkDirectionalParticles(2)
  .linkDirectionalParticleWidth(1.1)
  .linkDirectionalParticleSpeed(0.006)
  .linkDirectionalParticleColor(()=>'#bfe3ff')
  .enableNodeDrag(true)
  .onNodeClick(n=>{{
    const dist = 90;
    const r = Math.hypot(n.x,n.y,n.z)||1;
    Graph.cameraPosition({{x:n.x*dist/r, y:n.y*dist/r, z:n.z*dist/r}}, n, 1500);
    showDetail(n);
  }})
  .onNodeHover(n=>{{ gEl.style.cursor = n?'pointer':'grab'; if(n) showDetail(n); }});

// 让力导向快速稳定，然后自动适配视野 + 缓慢自动环绕
Graph.d3AlphaDecay(0.04).cooldownTicks(80);
setTimeout(()=>{{
  Graph.zoomToFit(900, 60);
  const ctrls = Graph.controls();
  ctrls.autoRotate = true;
  ctrls.autoRotateSpeed = 0.55;
}}, 1200);

function showDetail(n){{
  const d=document.getElementById('detail');
  const nowDays=Date.now()/1000/86400; const daysAgo=Math.max(0,Math.round(nowDays-n.born_at));
  d.style.display='block';
  d.innerHTML='<div class="t">'+esc(n.label)+'</div>'
    +'<div class="row">状态 <b>'+n.state+'</b></div>'
    +'<div class="row">权重 <b>'+n.weight_num+'</b></div>'
    +'<div class="row">关联 <b>'+n.degree+'</b> 条</div>'
    +'<div class="row">诞生 <b>'+daysAgo+'</b> 天前</div>';
}}
function esc(s){{return String(s).replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c]));}}

// 时间轴：只显示 born_at <= 阈值 的节点
const slider = document.getElementById('time');
const tlabel = document.getElementById('tlabel');
slider.addEventListener('input', ()=>{{
  const p = +slider.value/100;
  const th = dmin + (dmax-dmin)*p;
  const vis = NODES.filter(n=>n.born_at <= th);
  const visIds = new Set(vis.map(n=>n.id));
  const links = LINKS.filter(l=>{{
    const sid = typeof l.source==='object'?l.source.id:l.source;
    const tid = typeof l.target==='object'?l.target.id:l.target;
    return visIds.has(sid) && visIds.has(tid);
  }});
  Graph.graphData({{nodes:vis, links:links}});
  tlabel.textContent = p>=0.999 ? '全部' : new Date(th*86400*1000).toLocaleDateString('zh-CN');
}});
</script>
</body></html>"""
