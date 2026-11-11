# -*- coding: utf-8 -*-
"""brainmem 2D 星图视图（力导向星空）。只读导出 brainmem.db 生成自包含 HTML。

由 WorkBuddy 为小穗生成、小穗本人收进项目作为 2D 视图。
调用：设置环境变量 BRAINMEM_DB（库路径）、BRAINMEM_OUT（输出 html 路径），运行本脚本。
"""
import sqlite3, json, datetime, os, math, random, shutil, sys, tempfile, time
sys.dont_write_bytecode = True  # 避免在工具目录留下 __pycache__

SRC = os.environ.get('BRAINMEM_DB') or r'C:\Users\Administrator\AppData\Local\brainmem\data\brainmem.db'
BASE = os.path.dirname(os.path.abspath(__file__))
REPORT_DIR = os.path.dirname(BASE)
OUT = os.environ.get('BRAINMEM_OUT') or os.path.join(REPORT_DIR, 'brainmem星图.html')
HISTORY = os.path.join(REPORT_DIR, '星图历史')
MAX_BACKUPS = 10
NO_OPEN = '--no-open' in sys.argv or os.environ.get('BRAINMEM_NO_OPEN') == '1'
TZ = datetime.timezone(datetime.timedelta(hours=8))
W, H, CX, CY = 1200, 780, 600, 390
WORK = os.path.join(tempfile.gettempdir(), 'brainmem_starmap_ro')
SNAPSHOT = os.path.join(WORK, 'snapshot.db')
REQUIRED_TABLES = ('memory_node', 'memory_edge', 'weight_event', 'schema_meta')


def day_str(x):
    return datetime.datetime.fromtimestamp(float(x) * 86400, TZ).strftime('%m-%d %H:%M:%S') if x else ''


def sec_str(x):
    return datetime.datetime.fromtimestamp(float(x), TZ).strftime('%m-%d %H:%M:%S') if x else ''


# ---- 只读副本读取：原库 + WAL 复制到临时目录，绝不写 brainmem 数据目录 ----
def make_snapshot():
    os.makedirs(WORK, exist_ok=True)
    shutil.copyfile(SRC, SNAPSHOT)
    if os.path.exists(SRC + '-wal'):
        shutil.copyfile(SRC + '-wal', SNAPSHOT + '-wal')
    elif os.path.exists(SNAPSHOT + '-wal'):
        os.remove(SNAPSHOT + '-wal')
    for extra in ('-shm', '-journal'):
        p = SNAPSHOT + extra
        if os.path.exists(p):
            os.remove(p)


def probe():
    """在副本上做完整性校验并读出全部数据，返回 (签名, 数据)。"""
    make_snapshot()
    con = sqlite3.connect('file:' + SNAPSHOT.replace('\\', '/') + '?mode=ro', uri=True)
    try:
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA query_only=ON')
        chk = con.execute('PRAGMA quick_check').fetchone()[0]
        if chk != 'ok':
            raise RuntimeError('副本完整性检查未通过: %s' % chk)
        names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        missing = [t for t in REQUIRED_TABLES if t not in names]
        if missing:
            raise RuntimeError('副本缺少表: %s' % ', '.join(missing))
        get = lambda q: [{k: r[k] for k in r.keys()} for r in con.execute(q)]
        nodes = get('select * from memory_node order by born_at, id')
        edges = get('select * from memory_edge order by created_at, id')
        events = get('select * from weight_event order by seq')
        metas = get('select * from schema_meta')
        if not nodes:
            raise RuntimeError('副本中没有记忆节点，可能读到写入中途的状态')
        seq = int(con.execute('select coalesce(max(seq),0) from weight_event').fetchone()[0])
        return (len(nodes), len(edges), len(events), seq), dict(
            nodes=nodes, edges=edges, events=events, metas=metas)
    finally:
        con.close()


def read_consistent():
    """连续两次副本签名一致才采用；库持续写入时重试，仍不一致则放弃本次刷新。"""
    last = None
    for _ in range(4):
        sig, data = probe()
        if last is not None and sig == last[0]:
            return sig, data
        last = (sig, data)
        time.sleep(.4)
    raise RuntimeError('记忆库持续写入，连续读取不一致（最后签名 %s）' % (last[0],))


def on_error(exc_type, exc, tb):
    print('[刷新失败] 已保留上一次的星图：%s' % exc)
    if not NO_OPEN and os.path.exists(OUT):
        try:
            os.startfile(OUT)
        except Exception:
            pass


sys.excepthook = on_error

sig, _data = read_consistent()
nodes = _data['nodes']
edges = _data['edges']
events = _data['events']
metas = _data['metas']
print('[只读副本] 记忆 %d / 边 %d / 事件 %d / 最大 seq %d，连续两次一致' % sig)

idx = {n['id']: i for i, n in enumerate(nodes)}
for i, n in enumerate(nodes):
    n['no'] = i + 1
    n['w'] = round(n['weight_bp'] / 10000.0, 4)
    n['born_str'] = day_str(n['born_at'])
    n['degree'] = 0
    n['ev_count'] = 0
    n['r'] = round(5.6 + n['w'] * 2.0, 1)

E = []
for e in edges:
    if e['src_id'] not in idx or e['dst_id'] not in idx:
        continue
    i, j = idx[e['src_id']], idx[e['dst_id']]
    w = round(e['weight_bp'] / 10000.0, 4)
    E.append((i, j, w))
    nodes[i]['degree'] += 1
    nodes[j]['degree'] += 1
    e.update({'i': i, 'j': j, 'w': w,
              'src': nodes[i]['label'], 'dst': nodes[j]['label'],
              'created_str': day_str(e['created_at'])})
edges = [e for e in edges if 'i' in e]

for v in events:
    if v['entity_id'] in idx:
        nodes[idx[v['entity_id']]]['ev_count'] += 1

# ---- 力导向布局（Fruchterman-Reingold 变体，强边吸得更紧） ----
random.seed(20261109)
N = len(nodes)
pos = [[CX + (26 + 19 * math.sqrt(i)) * math.cos(i * 2.399963),
        CY + (26 + 19 * math.sqrt(i)) * math.sin(i * 2.399963)] for i in range(N)]
k, temp = 118.0, 92.0
for it in range(430):
    disp = [[0.0, 0.0] for _ in range(N)]
    for i in range(N):
        for j in range(i + 1, N):
            dx, dy = pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]
            d = math.hypot(dx, dy) + .01
            f = k * k / d
            ux, uy = dx / d, dy / d
            disp[i][0] += ux * f; disp[i][1] += uy * f
            disp[j][0] -= ux * f; disp[j][1] -= uy * f
    for i, j, w in E:
        dx, dy = pos[j][0] - pos[i][0], pos[j][1] - pos[i][1]
        d = math.hypot(dx, dy) + .01
        f = (d * d / k) * (0.55 + w / 12.0)
        ux, uy = dx / d, dy / d
        disp[i][0] += ux * f; disp[i][1] += uy * f
        disp[j][0] -= ux * f; disp[j][1] -= uy * f
    for i in range(N):
        disp[i][0] += (CX - pos[i][0]) * 0.055
        disp[i][1] += (CY - pos[i][1]) * 0.055
    for i in range(N):
        l = math.hypot(disp[i][0], disp[i][1])
        if l > 0:
            s = min(l, temp) / l
            pos[i][0] += disp[i][0] * s
            pos[i][1] += disp[i][1] * s
    temp = max(1.1, temp * 0.985)

xs, ys = [p[0] for p in pos], [p[1] for p in pos]
scale = min(760 / (max(xs) - min(xs)), 620 / (max(ys) - min(ys)), 1.55)
mx, my = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
pos = [[CX + (p[0] - mx) * scale * 1.32, CY + (p[1] - my) * scale] for p in pos]

# 最小间距松弛，避免星星与标签重叠
for _ in range(70):
    for i in range(N):
        for j in range(i + 1, N):
            dx, dy = pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]
            d = math.hypot(dx, dy) + .01
            mind = nodes[i]['r'] + nodes[j]['r'] + 26
            if d < mind:
                push = (mind - d) / 2
                ux, uy = dx / d, dy / d
                pos[i][0] += ux * push; pos[i][1] += uy * push
                pos[j][0] -= ux * push; pos[j][1] -= uy * push

for i, n in enumerate(nodes):
    n['x'], n['y'] = round(pos[i][0], 1), round(pos[i][1], 1)
    n['short'] = n['label'][:8] + ('…' if len(n['label']) > 8 else '')

# 标签：朝圆心外侧放置 + 同侧垂直避让（字号变大，间隔同步放宽）
for side in (1, -1):
    group = [(n['y'], n) for n in nodes if (n['x'] >= CX) == (side > 0)]
    group.sort(key=lambda t: t[0])
    last_y, last_x = -1e9, 0
    for _, n in group:
        n['lx'] = round(n['x'] + side * (n['r'] + 10), 1)
        n['ly'] = round(n['y'] + 5, 1)
        n['anchor'] = 'start' if side > 0 else 'end'
        if abs(n['ly'] - last_y) < 26 and abs(n['lx'] - last_x) < 170:
            n['ly'] = round(last_y + 26, 1)
        last_y, last_x = n['ly'], n['lx']

# 背景星
stars = [{'x': round(random.uniform(8, W - 8), 1),
          'y': round(random.uniform(8, H - 8), 1),
          'r': random.choice([.5, .7, .9, 1.2, 1.5]),
          'o': round(random.uniform(.12, .55), 2)} for _ in range(230)]

hubs = sorted(nodes, key=lambda n: (-n['degree'], -n['w']))[:8]
state_counts = {}
for n in nodes:
    state_counts[n['state']] = state_counts.get(n['state'], 0) + 1
rel_counts = {}
for e in edges:
    rel_counts[e['relation']] = rel_counts.get(e['relation'], 0) + 1

meta = {
    'db_path': SRC, 'read_mode': '只读副本（含 WAL）',
    'generated_at': datetime.datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S'),
    'n_nodes': len(nodes), 'n_edges': len(edges), 'n_events': len(events),
    'state_counts': state_counts, 'rel_counts': rel_counts,
    'schema_version': (metas[0]['value'] if metas else ''),
    'first_node': nodes[0]['born_str'], 'last_node': nodes[-1]['born_str'],
    'date_span': nodes[0]['born_str'][:5] + ('' if nodes[0]['born_str'][:5] == nodes[-1]['born_str'][:5]
                                             else '~' + nodes[-1]['born_str'][:5]),
    'min_gap': round(min(math.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1])
                         for i in range(N) for j in range(i + 1, N)), 1),
    'span_x': round(max(p[0] for p in pos) - min(p[0] for p in pos), 1),
    'span_y': round(max(p[1] for p in pos) - min(p[1] for p in pos), 1),
}
data = {'meta': meta, 'nodes': nodes, 'edges': edges, 'stars': stars,
        'hubs': [n['id'] for n in hubs]}
payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c')

TPL = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>brainmem 记忆星图</title>
<style>
*{box-sizing:border-box}
body{margin:0;font:14px/1.6 system-ui,-apple-system,"Microsoft YaHei",sans-serif;
 --bg:#080d1c;--panel:rgba(15,23,45,.86);--tx:#e9edf9;--mut:#96a2c0;--line:rgba(255,255,255,.13);
 --normal:#7fb6ff;--condensed:#ffc861;--vestige:#8b93a8;--full:#6fe3c4;
 --assoc:#6fa8ff;--causes:#ffab5e;--seq:#5fd8bd;--part:#c79bff;--star:#ffffff;
 background:radial-gradient(ellipse at 50% 32%,#131d3a 0%,#0a1022 55%,#060a16 100%);color:var(--tx);min-height:100vh}
body.day{--bg:#f4f6fc;--panel:rgba(255,255,255,.92);--tx:#20201e;--mut:#6b7285;--line:rgba(0,0,0,.12);
 --normal:#185FA5;--condensed:#BA7517;--vestige:#7c8290;--full:#0F6E56;
 --assoc:#3b7fd0;--causes:#c9772a;--seq:#168f78;--part:#8257b5;--star:#a9b3c9;
 background:radial-gradient(ellipse at 50% 32%,#ffffff 0%,#f0f3fa 60%,#e8ecf6 100%)}
.app{max-width:1600px;margin:0 auto;padding:20px 20px 34px}
header{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:12px}
h1{font-size:21px;font-weight:600;margin:0;letter-spacing:.5px}
.sub{font-size:12px;color:var(--mut)}
.toolbar{display:flex;gap:9px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.toolbar input,.toolbar select,.toolbar button,.toolbar label{font:13px system-ui,"Microsoft YaHei",sans-serif;
 border:1px solid var(--line);border-radius:9px;background:var(--panel);color:var(--tx);padding:7px 11px}
.toolbar input{min-width:210px;flex:1;max-width:330px}
.toolbar button{cursor:pointer}
.toolbar button:hover{border-color:var(--assoc)}
.toolbar label{display:flex;align-items:center;gap:6px;cursor:pointer;user-select:none}
.toolbar input[type=checkbox]{min-width:0;width:auto;flex:none;margin:0}
.hits{font-size:12px;color:var(--mut);margin-left:auto}
.main{display:flex;gap:14px;align-items:stretch;flex-wrap:wrap}
.sky{position:relative;flex:1 1 760px;min-width:340px;border:1px solid var(--line);border-radius:16px;
 overflow:hidden;background:rgba(0,0,0,.10);height:clamp(520px,72vh,760px)}
body.day .sky{background:rgba(255,255,255,.35)}
svg{display:block;width:100%;height:100%;min-height:520px;cursor:grab}
svg.dragging{cursor:grabbing}
.bgstar{fill:var(--star)}
.edge{fill:none;stroke-linecap:round;transition:stroke-opacity .18s,stroke-width .18s}
.rel-ASSOCIATED{stroke:var(--assoc)}.rel-CAUSES{stroke:var(--causes)}
.rel-SEQUENCE{stroke:var(--seq)}.rel-PART_OF{stroke:var(--part)}
.edge.dim{stroke-opacity:.045!important}
.edge.hi{stroke-opacity:1;filter:url(#glow)}
.edge.hide{stroke-opacity:.025!important}
.ar-ASSOCIATED{fill:var(--assoc)}.ar-CAUSES{fill:var(--causes)}
.ar-SEQUENCE{fill:var(--seq)}.ar-PART_OF{fill:var(--part)}
.node{cursor:pointer;transition:opacity .18s}
.st-NORMAL{--nc:var(--normal)}.st-CONDENSED{--nc:var(--condensed)}
.st-VESTIGE{--nc:var(--vestige)}.st-FULL{--nc:var(--full)}
.halo{fill:var(--nc);opacity:.16;transition:opacity .18s}
.core{fill:var(--nc)}
.spark{fill:#ffffff;opacity:.85}
.node.dim{opacity:.14}
.node.hi .halo{opacity:.5}
.node.hi .core{filter:url(#glow2)}
.labels{position:absolute;inset:0;z-index:5;pointer-events:none;overflow:hidden}
.lbl{position:absolute;white-space:nowrap;font-size:12px;line-height:1.35;letter-spacing:.2px;
 color:var(--tx);background:rgba(8,13,28,.78);border:1px solid rgba(255,255,255,.13);
 padding:2px 7px;border-radius:6px;transform:translateY(-50%);
 pointer-events:none;transition:opacity .18s,background .18s;box-shadow:0 2px 8px rgba(0,0,0,.28)}
body.day .lbl{background:rgba(255,255,255,.9);border-color:rgba(0,0,0,.13);box-shadow:0 2px 8px rgba(0,0,0,.08)}
.lbl.rgt{transform:translate(-100%,-50%)}
.lbl.dim{opacity:.12}
.lbl.hidden{display:none}
.lbl.hi{color:#fff;background:rgba(43,96,190,.94);border-color:rgba(127,182,255,.7);font-weight:600}
body.day .lbl.hi{color:#fff;background:#185FA5;border-color:#185FA5}
.zoomtag{position:absolute;right:14px;top:12px;z-index:6;font-size:11px;color:var(--mut);
 background:var(--panel);border:1px solid var(--line);border-radius:20px;padding:3px 10px;pointer-events:none}
.pulse{fill:none;stroke:var(--nc);stroke-width:1;transform-box:fill-box;transform-origin:center;
 animation:pulse 3.4s ease-out infinite;pointer-events:none}
@keyframes pulse{0%{transform:scale(.5);opacity:.55}100%{transform:scale(2.6);opacity:0}}
.tip{position:absolute;pointer-events:none;z-index:8;display:none;background:rgba(8,13,28,.94);
 color:#eef2ff;font-size:12px;padding:7px 11px;border-radius:8px;border:1px solid rgba(255,255,255,.18);
 white-space:nowrap;box-shadow:0 6px 20px rgba(0,0,0,.35)}
body.day .tip{background:rgba(255,255,255,.97);color:#20201e;border-color:rgba(0,0,0,.15)}
.hint{position:absolute;left:14px;bottom:12px;font-size:11px;color:var(--mut);pointer-events:none}
aside{flex:0 1 310px;min-width:270px;background:var(--panel);border:1px solid var(--line);
 border-radius:16px;padding:16px 17px;max-height:760px;overflow:auto}
aside h2{font-size:14px;font-weight:600;margin:0 0 10px}
.k{font-size:12px;color:var(--mut)}
.big{font-size:19px;font-weight:600;margin:3px 0 8px;line-height:1.35}
.badge{display:inline-block;padding:2px 9px;border-radius:20px;font-size:11px;font-weight:500}
.badge.NORMAL{background:rgba(127,182,255,.18);color:var(--normal)}
.badge.CONDENSED{background:rgba(255,200,97,.18);color:var(--condensed)}
.badge.VESTIGE{background:rgba(139,147,168,.2);color:var(--vestige)}
.badge.FULL{background:rgba(111,227,196,.18);color:var(--full)}
.stat{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:12px 0}
.stat div{background:rgba(127,182,255,.07);border-radius:9px;padding:7px 10px;font-size:12px;color:var(--mut)}
.stat b{display:block;font-size:16px;color:var(--tx);font-weight:600}
.sec{font-size:12px;font-weight:600;margin:16px 0 7px;color:var(--mut);letter-spacing:.4px}
.link{display:block;width:100%;text-align:left;background:rgba(127,182,255,.06);border:1px solid var(--line);
 border-radius:9px;padding:7px 9px;margin-bottom:6px;color:var(--tx);font-size:12px;cursor:pointer;
 font-family:inherit;line-height:1.5}
.link:hover{border-color:var(--assoc)}
.link .dir{color:var(--mut);margin-right:5px}
.rel{font-size:10px;padding:1px 5px;border-radius:5px;border:1px solid var(--line);margin-left:4px}
.rel-ASSOCIATED{color:var(--assoc)}.rel-CAUSES{color:var(--causes)}
.rel-SEQUENCE{color:var(--seq)}.rel-PART_OF{color:var(--part)}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:11px;color:var(--mut);margin-top:6px}
.legend i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px;vertical-align:middle}
.linekey{display:inline-block;width:16px;height:2px;vertical-align:middle;margin-right:5px}
.foot{font-size:11px;color:var(--mut);margin-top:14px;line-height:1.9;border-top:1px solid var(--line);padding-top:10px}
@media(max-width:1050px){.sky{flex-basis:100%;height:62vh;min-height:400px}svg{min-height:400px}aside{flex-basis:100%;max-height:430px}}
</style>
</head>
<body>
<div class="app">
<header>
  <h1>brainmem 记忆星图</h1>
  <span class="sub" id="sub"></span>
</header>
<div class="toolbar">
  <input id="q" type="search" placeholder="搜一颗星：输入标签即高亮…">
  <select id="state"><option value="">全部状态</option><option>NORMAL</option><option>CONDENSED</option><option>VESTIGE</option><option>FULL</option></select>
  <select id="rel"><option value="">全部连线</option><option>ASSOCIATED</option><option>CAUSES</option><option>SEQUENCE</option><option>PART_OF</option></select>
  <select id="labels"><option value="smart">标签 · 智能</option><option value="all">标签 · 全部</option><option value="off">标签 · 关闭</option></select>
  <button id="theme">切换日间</button>
  <button id="reset">重置视角</button>
  <span class="hits" id="hits"></span>
</div>
<div class="main">
  <div class="sky" id="sky">
    <svg id="net" viewBox="0 0 1200 780" role="img" aria-label="brainmem 记忆星图：节点为记忆，连线为关联"></svg>
    <div class="labels" id="labelLayer"></div>
    <div class="zoomtag" id="zoom">100%</div>
    <div class="tip" id="tip"></div>
    <div class="hint">默认只显示枢纽星标签 · 悬停点亮该星与邻居 · 标签不随缩放变大 · 滚轮缩放 / 拖拽平移 / 点击锁定 · 「重置视角」可复原</div>
  </div>
  <aside id="side"></aside>
</div>
</div>
<script>
const D = __DATA__;
const M = D.meta;
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const f4 = v => Number(v || 0).toFixed(4);
const RELCN = {ASSOCIATED:'关联',CAUSES:'因果',SEQUENCE:'先后',PART_OF:'组成'};
const STCN = {NORMAL:'记得牢',CONDENSED:'已压缩',VESTIGE:'将遗忘',FULL:'很牢固'};
const byId = {};
D.nodes.forEach(n => byId[n.id] = n);
const adj = {};
D.nodes.forEach(n => adj[n.id] = []);
D.edges.forEach((e, i) => {
  adj[e.src_id].push({other:e.dst_id, rel:e.relation, w:e.w, co:e.coactivation, dir:'out', i:i});
  adj[e.dst_id].push({other:e.src_id, rel:e.relation, w:e.w, co:e.coactivation, dir:'in', i:i});
});
const S = {selected:null, hover:null, q:'', state:'', rel:'', labelMode:'smart',
           view:{x:0,y:0,w:1200,h:780}, drag:null, lastSide:''};
const DEFAULT_LABELS = new Set(D.hubs.concat(
  D.nodes.slice().sort((a,b)=>b.w-a.w).slice(0,6).map(n=>n.id)));

function pathD(e, i){
  const a = D.nodes[e.i], b = D.nodes[e.j];
  let dx = b.x-a.x, dy = b.y-a.y;
  const d = Math.hypot(dx,dy) || 1;
  const ux = dx/d, uy = dy/d;
  const arrow = e.relation !== 'ASSOCIATED';
  const o1 = 7 + a.r*.55, o2 = 8 + b.r*.55 + (arrow ? 7 : 0);
  const x1 = a.x+ux*o1, y1 = a.y+uy*o1, x2 = b.x-ux*o2, y2 = b.y-uy*o2;
  const mx = (x1+x2)/2, my = (y1+y2)/2;
  const bend = (i%2 ? 1 : -1) * Math.min(24, d*.075);
  const cx = mx - uy*bend, cy = my + ux*bend;
  return 'M '+x1.toFixed(1)+' '+y1.toFixed(1)+' Q '+cx.toFixed(1)+' '+cy.toFixed(1)+' '+x2.toFixed(1)+' '+y2.toFixed(1);
}

function build(){
  const defs = '<defs>' +
    '<filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>' +
    '<filter id="glow2" x="-80%" y="-80%" width="260%" height="260%"><feGaussianBlur stdDeviation="3.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>' +
    ['ASSOCIATED','CAUSES','SEQUENCE','PART_OF'].map(r =>
      '<marker id="ar-'+r+'" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path class="ar-'+r+'" d="M0 0 L10 5 L0 10 z"/></marker>').join('') + '</defs>';
  const bg = '<g id="bgstars">' + D.stars.map(s =>
    '<circle class="bgstar" cx="'+s.x+'" cy="'+s.y+'" r="'+s.r+'" opacity="'+s.o+'"/>').join('') + '</g>';
  const paths = '<g id="edges">' + D.edges.map((e,i) =>
    '<path class="edge rel-'+e.relation+'" data-i="'+i+'" data-a="'+esc(e.src_id)+'" data-b="'+esc(e.dst_id)+'" '+
    'stroke-width="'+Math.max(.8,Math.min(2.6,.7+e.w*.22)).toFixed(2)+'" stroke-opacity="'+(.30+Math.min(.30,e.w*.03)).toFixed(2)+'" '+
    (e.relation !== 'ASSOCIATED' ? 'marker-end="url(#ar-'+e.relation+')" ' : '') +
    'd="'+pathD(e,i)+'"/>').join('') + '</g>';
  const nodes = '<g id="nodes">' + D.nodes.map(n => {
    const pulse = D.hubs.indexOf(n.id) >= 0
      ? '<circle class="pulse" cx="'+n.x+'" cy="'+n.y+'" r="'+(n.r+3)+'"/>' : '';
    return '<g class="node st-'+n.state+'" data-id="'+esc(n.id)+'">' +
      '<circle class="halo" cx="'+n.x+'" cy="'+n.y+'" r="'+(n.r*2.7).toFixed(1)+'"/>' + pulse +
      '<circle class="core" cx="'+n.x+'" cy="'+n.y+'" r="'+n.r+'"/>' +
      '<circle class="spark" cx="'+(n.x-n.r*.28).toFixed(1)+'" cy="'+(n.y-n.r*.28).toFixed(1)+'" r="'+Math.max(.8,n.r*.22).toFixed(1)+'"/>' +
      '</g>';
  }).join('') + '</g>';
  $('#net').innerHTML = defs + bg + paths + nodes;
  $('#labelLayer').innerHTML = D.nodes.map(n =>
    '<span class="lbl'+(n.anchor === 'end' ? ' rgt' : '')+'" data-id="'+esc(n.id)+'">'+esc(n.short)+'</span>').join('');
  $('#sub').textContent = M.n_nodes + ' 颗记忆星 · ' + M.n_edges + ' 条星座连线 · ' + M.n_events + ' 次权重事件 · 数据截止 ' + M.generated_at + ' · 用「打开星图.cmd」打开即刷新';
  side(null);
  applyView();
}

function focus(id){
  const active = id || S.selected;
  const near = {};
  if(active){
    near[active] = true;
    (adj[active]||[]).forEach(a => near[a.other] = true);
  }
  const q = S.q.trim().toLowerCase();
  const match = {};
  let hits = 0;
  D.nodes.forEach(n => {
    const okQ = !q || n.label.toLowerCase().indexOf(q) >= 0 || n.id.toLowerCase().indexOf(q) >= 0;
    const okS = !S.state || n.state === S.state;
    match[n.id] = okQ && okS;
    if(okQ && !S.state) hits++;
  });
  $('#hits').textContent = q ? ('匹配 ' + hits + ' 颗星') : (S.rel ? '仅显示 ' + (RELCN[S.rel]||S.rel) + ' 连线' : '');
  document.querySelectorAll('.node').forEach(g => {
    const nid = g.dataset.id;
    const dim = (active && !near[nid]) || !match[nid];
    g.classList.toggle('dim', dim);
    g.classList.toggle('hi', !!active && nid === active);
  });
  document.querySelectorAll('.lbl').forEach(t => {
    const nid = t.dataset.id;
    const show = S.labelMode === 'all' || (S.labelMode === 'smart' && (
      active ? !!near[nid] : (DEFAULT_LABELS.has(nid) || (!!q && match[nid]))));
    t.classList.toggle('hidden', !show);
    t.classList.toggle('dim', show && ((active && !near[nid]) || !match[nid]));
    t.classList.toggle('hi', show && !!active && nid === active);
  });
  document.querySelectorAll('.edge').forEach(p => {
    const i = +p.dataset.i, e = D.edges[i];
    const incident = active && (e.src_id === active || e.dst_id === active);
    const relOk = !S.rel || e.relation === S.rel;
    p.classList.toggle('hi', !!incident && relOk);
    p.classList.toggle('dim', (!!active && !incident) || !relOk || !match[e.src_id] || !match[e.dst_id]);
  });
  if(S.lastSide !== (active || '')){ side(active); S.lastSide = active || ''; }
}

function side(id){
  const box = $('#side');
  if(!id){
    box.innerHTML = '<h2>星图导览</h2>' +
      '<div class="k">有连接的记忆会被吸成星座。默认只标出枢纽星；<b>悬停任意一颗星</b>，它和它所有邻居的标签会一起点亮，其余变暗——这样最容易看清谁连着谁。</div>' +
      '<div class="stat"><div>记忆星<b>'+M.n_nodes+'</b></div><div>星座连线<b>'+M.n_edges+'</b></div>' +
      '<div>记忆写入<b style="font-size:14px">'+M.date_span+'</b></div><div>最强边权<b>'+f4(Math.max.apply(null,D.edges.map(e=>e.w)))+'</b></div></div>' +
      '<div class="sec">状态（星点颜色）</div><div class="legend">' +
      Object.keys(M.state_counts).map(k => '<span><i style="background:var(--'+k.toLowerCase()+')"></i>'+k+' '+M.state_counts[k]+'</span>').join('') + '</div>' +
      '<div class="sec">关系（连线颜色）</div><div class="legend">' +
      Object.keys(M.rel_counts).map(k => '<span><i class="linekey" style="background:var(--'+({'ASSOCIATED':'assoc','CAUSES':'causes','SEQUENCE':'seq','PART_OF':'part'}[k])+')"></i>'+k+' · '+RELCN[k]+' '+M.rel_counts[k]+'</span>').join('') + '</div>' +
      '<div class="sec">枢纽星 · 连接最多</div>' +
      D.hubs.map(nid => {const n=byId[nid];return '<button class="link" data-goto="'+esc(nid)+'"><span class="dir">#'+n.no+'</span>'+esc(n.label)+' <span class="k">· '+n.degree+' 条连接</span></button>';}).join('') +
      '<div class="foot">悬停任意一颗星，只有它和它的邻居保持明亮；点击可锁定，右侧会列出它和谁相连、什么关系、边权多少。<br>箭头表示有方向的因果 / 先后 / 组成关系。<br>本页为只读快照，数据来自不可变 SQLite 连接，未触发任何自动加权。</div>';
    return;
  }
  const n = byId[id]; if(!n) return;
  const links = (adj[id]||[]).slice().sort((a,b)=>b.w-a.w || b.co-a.co);
  box.innerHTML = '<div class="k">#'+n.no+' · '+n.born_str+' 写入</div>' +
    '<div class="big">'+esc(n.label)+'</div>' +
    '<div><span class="badge '+n.state+'">'+n.state+' · '+STCN[n.state]+'</span></div>' +
    '<div class="stat"><div>权重 W<b>'+f4(n.w)+'</b></div><div>连接数<b>'+n.degree+'</b></div>' +
    '<div>字数<b>'+n.char_len+'</b></div><div>关联事件<b>'+n.ev_count+'</b></div></div>' +
    '<div class="sec">与它相连的星（'+links.length+' 条）</div>' +
    (links.length ? links.map(a => {
      const o = byId[a.other];
      return '<button class="link" data-goto="'+esc(o.id)+'"><span class="dir">'+(a.dir==='out'?'→':'←')+'</span>' +
        esc(o.label) + '<span class="rel rel-'+a.rel+'">'+a.rel+' · '+RELCN[a.rel]+'</span>' +
        '<span class="k" style="display:block">边权 '+f4(a.w)+' · 共激活 '+a.co+' · W '+f4(o.w)+'</span></button>';
    }).join('') : '<div class="k">这颗星暂时没有连线。</div>') +
    '<div class="foot">点列表里的任意一颗星可跳转过去；点空白处取消锁定。<br>ID <span style="font-family:monospace">'+esc(n.id)+'</span></div>';
  box.querySelectorAll('[data-goto]').forEach(b => b.addEventListener('click', () => {
    S.selected = b.dataset.goto; centerOn(byId[S.selected]); focus(S.selected);
  }));
}

function centerOn(n){
  S.view.x = n.x - S.view.w/2;
  S.view.y = n.y - S.view.h/2;
  applyView();
}
function applyView(){
  const v = S.view;
  $('#net').setAttribute('viewBox', v.x.toFixed(1)+' '+v.y.toFixed(1)+' '+v.w.toFixed(1)+' '+v.h.toFixed(1));
  const z = $('#zoom'); if(z) z.textContent = Math.round(1200 / v.w * 100) + '%';
  positionLabels();
}
// 标签是屏幕层元素：位置随视角换算，字号永远固定，缩放不会把字放大成黑块
function positionLabels(){
  const r = svg.getBoundingClientRect();
  const v = S.view;
  if(!r.width || !r.height) return;
  const k = Math.min(r.width / v.w, r.height / v.h);
  const ox = (r.width - v.w * k) / 2, oy = (r.height - v.h * k) / 2;
  const zk = v.w / 1200;
  document.querySelectorAll('.lbl').forEach(t => {
    const n = byId[t.dataset.id];
    if(!n) return;
    const ux = n.x + (n.lx - n.x) * zk;
    const uy = n.y + (n.ly - n.y) * zk;
    t.style.left = ((ux - v.x) * k + ox).toFixed(1) + 'px';
    t.style.top  = ((uy - v.y) * k + oy).toFixed(1) + 'px';
  });
}
window.addEventListener('resize', positionLabels);

const svg = $('#net'), sky = $('#sky'), tip = $('#tip');
svg.addEventListener('mousemove', ev => {
  if(S.drag){
    if(Math.abs(ev.clientX-S.drag.x)>3 || Math.abs(ev.clientY-S.drag.y)>3) S.drag.moved = true;
    const r = sky.getBoundingClientRect();
    S.view.x = S.drag.vx - (ev.clientX - S.drag.x) / r.width * S.view.w;
    S.view.y = S.drag.vy - (ev.clientY - S.drag.y) / r.height * S.view.h;
    applyView();
    return;
  }
  const g = ev.target.closest('.node');
  const p = ev.target.closest('.edge');
  if(g){
    const id = g.dataset.id; S.hover = id; focus(id);
    const n = byId[id];
    tip.innerHTML = '<b>#'+n.no+' '+esc(n.label)+'</b><br>'+n.state+' · W '+f4(n.w)+' · '+n.degree+' 条连接';
  }else if(p){
    const e = D.edges[+p.dataset.i];
    tip.innerHTML = '<b>'+esc(e.src)+'</b> '+(RELCN[e.relation]||e.relation)+' <b>'+esc(e.dst)+'</b><br>边权 '+f4(e.w)+' · 共激活 '+e.coactivation;
  }else{
    S.hover = null; tip.style.display='none'; focus(null); return;
  }
  tip.style.display='block';
  const r = sky.getBoundingClientRect();
  tip.style.left = Math.min(r.width-250, Math.max(6, ev.clientX-r.left+14))+'px';
  tip.style.top = Math.min(r.height-60, Math.max(6, ev.clientY-r.top+14))+'px';
});
svg.addEventListener('mouseleave', () => {S.hover=null; tip.style.display='none'; focus(null);});
let dragMoved = false;
svg.addEventListener('click', ev => {
  const g = ev.target.closest('.node');
  if(g){ S.selected = (S.selected === g.dataset.id ? null : g.dataset.id); focus(S.selected); }
  else if(!dragMoved){ S.selected = null; focus(null); }
  dragMoved = false;
});
svg.addEventListener('mousedown', ev => {
  if(ev.target.closest('.node')) return;
  S.drag = {x:ev.clientX, y:ev.clientY, vx:S.view.x, vy:S.view.y, moved:false};
  svg.classList.add('dragging');
});
window.addEventListener('mouseup', () => {
  if(S.drag) dragMoved = S.drag.moved;
  S.drag = null; svg.classList.remove('dragging');
});
svg.addEventListener('wheel', ev => {
  ev.preventDefault();
  const r = sky.getBoundingClientRect();
  const px = (ev.clientX-r.left)/r.width, py = (ev.clientY-r.top)/r.height;
  const f = ev.deltaY > 0 ? 1.12 : 1/1.12;
  const nw = Math.max(300, Math.min(2400, S.view.w*f));
  const nh = nw/S.view.w*S.view.h;
  S.view.x += (S.view.w-nw)*px; S.view.y += (S.view.h-nh)*py;
  S.view.w = nw; S.view.h = nh;
  applyView();
}, {passive:false});

$('#q').addEventListener('input', ev => {S.q=ev.target.value; focus(S.selected);});
$('#state').addEventListener('change', ev => {S.state=ev.target.value; focus(S.selected);});
$('#rel').addEventListener('change', ev => {S.rel=ev.target.value; focus(S.selected);});
$('#labels').addEventListener('change', ev => {S.labelMode=ev.target.value; focus(S.selected);});
$('#theme').addEventListener('click', () => {
  const day = document.body.classList.toggle('day');
  $('#theme').textContent = day ? '切换夜空' : '切换日间';
});
$('#reset').addEventListener('click', () => {
  S.view = {x:0,y:0,w:1200,h:780}; S.selected=null; S.q=''; S.state=''; S.rel=''; S.labelMode='smart';
  $('#q').value=''; $('#state').value=''; $('#rel').value=''; $('#labels').value='smart';
  applyView(); focus(null);
});
build(); focus(null);
</script>
</body>
</html>
"""

html = TPL.replace('__DATA__', payload)

# 生成结果自检：结构完整、占位符已替换、内嵌数据条数与只读副本一致
assert html.startswith('<!DOCTYPE html>') and html.rstrip().endswith('</html>'), 'HTML 结构不完整'
assert '__DATA__' not in html, '模板占位符未替换'
chk = json.loads(payload)
assert len(chk['nodes']) == len(nodes) and len(chk['edges']) == len(edges)
assert chk['meta']['n_events'] == len(events)

# 覆盖前备份上一版，只保留最近 MAX_BACKUPS 份
os.makedirs(REPORT_DIR, exist_ok=True)
os.makedirs(HISTORY, exist_ok=True)
stamp = datetime.datetime.now(TZ).strftime('%Y%m%d-%H%M%S')
if os.path.exists(OUT):
    shutil.copyfile(OUT, os.path.join(HISTORY, 'brainmem星图_%s.html' % stamp))
    old = sorted(f for f in os.listdir(HISTORY)
                 if f.startswith('brainmem星图_') and f.endswith('.html'))
    for f in old[:-MAX_BACKUPS]:
        os.remove(os.path.join(HISTORY, f))

# 原子写入：先写 .tmp 再 replace，中途失败不会留下半个文件
tmp = OUT + '.tmp'
with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
    f.write(html)
os.replace(tmp, OUT)

print('OK', OUT, os.path.getsize(OUT), 'bytes')
print('数据截止:', meta['generated_at'], '| 记忆 %d / 边 %d / 事件 %d' % (len(nodes), len(edges), len(events)))
print('layout: span_x=%.1f span_y=%.1f min_gap=%.1f' % (meta['span_x'], meta['span_y'], meta['min_gap']))
print('x range %.1f..%.1f  y range %.1f..%.1f' % (
    min(n['x'] for n in nodes), max(n['x'] for n in nodes),
    min(n['y'] for n in nodes), max(n['y'] for n in nodes)))
print('hubs:', [(n['label'], n['degree']) for n in hubs])

