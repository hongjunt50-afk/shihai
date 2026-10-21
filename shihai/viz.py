# -*- coding: utf-8 -*-
r"""Viz —— 识海可视化: 把"看不见的性格演化"变成能看的图。

为什么要可视化(而不只是 htop 式的数字):
    性格图谱、人格漂移、记忆衰减这三件事的本质都是**随时间缓慢变化的结构**,
    用数字读不出来, 用图一眼就看出来 —— 哪条支点最粗、哪些日子在发光、
    哪些记忆正在淡出。

产物: **单文件 HTML**, 零依赖(不联网、不引 CDN、不带图标库)。
    打开即看, 可以直接发给别人, 也可以扔进 wiki/ 当归档。

六个视图:
    1. 概览      名字/类型/健康度/好感/自由模式状态
    2. 性格图谱   核心记忆(支点) → 性格倾向 → 编织, 力导向布局
    3. 特质雷达   七维 trait 雷达图
    4. 人格漂移   历次 persona_snapshot 的 trait 折线
    5. 记忆衰减   事件年龄 × 强度散点, 核心高亮, 沉寂变灰
    6. 日记热力   按日期的活跃度日历 + 自我知识可塑性条
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone

from .store import utcnow


def _age_days(ts):
    try:
        t = datetime.fromisoformat(ts)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - t).total_seconds() / 86400.0)
    except Exception:
        return 0.0


def collect(store, persona_engine=None, typology_engine=None, kb=None, diary=None):
    """把要画的东西一次性抽成 JSON 友好的结构。"""
    c = store.conn

    # 概览
    events = c.execute("SELECT * FROM events").fetchall()
    core_n = sum(1 for r in events if r["core"])
    dormant_n = sum(1 for r in events if r["dormant"])
    overview = {
        "events": len(events), "core": core_n, "dormant": dormant_n,
        "nodes": c.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        "edges": c.execute("SELECT COUNT(*) FROM edges").fetchone()[0],
        "semantic": c.execute("SELECT COUNT(*) FROM semantic").fetchone()[0],
        "recalls": c.execute("SELECT COUNT(*) FROM recall_log").fetchone()[0],
        "diaries": c.execute("SELECT COUNT(*) FROM diary").fetchone()[0],
        "warmth": store.warmth_total(),
        "selfkb": c.execute("SELECT COUNT(*) FROM self_knowledge").fetchone()[0],
    }

    # 类型 / 特质
    typology, traits, card = {}, {}, ""
    if persona_engine is not None:
        pc = persona_engine.refresh()
        traits = pc.traits
        card = pc.card
        typology = pc.typology
        overview["name"] = persona_engine.name
    elif typology_engine is not None:
        p = typology_engine.infer(persist=False)
        typology = p.to_dict()

    # 性格图谱: 支点 + 编织
    graph = {"fulcrums": [], "braids": [], "tensions": [], "summary": ""}
    if persona_engine is not None and hasattr(persona_engine, "graph_engine"):
        g = persona_engine.graph_engine.weave()
        graph = g.to_dict()

    # 人格漂移: 历次快照的 trait
    history = []
    for r in c.execute("SELECT ts, traits FROM persona_snapshot ORDER BY id"):
        try:
            d = json.loads(r["traits"])
        except Exception:
            continue
        d["ts"] = r["ts"]
        history.append(d)

    # 记忆: 年龄 × 强度
    mem = []
    for r in events:
        mem.append({
            "id": r["id"], "summary": (r["summary"] or "")[:40],
            "age": round(_age_days(r["ts"]), 1),
            "strength": round(float(r["strength"]), 3),
            "core": bool(r["core"]), "dormant": bool(r["dormant"]),
            "valence": round(float(r["valence"]), 2),
            "arousal": round(float(r["arousal"]), 2),
            "emotion": r["emotion"] or "",
        })

    # 日记热力
    days = []
    for r in c.execute("SELECT day, mood, warmth FROM diary ORDER BY day"):
        days.append({"day": r["day"], "mood": r["mood"] or "",
                     "warmth": round(float(r["warmth"] or 0), 2)})

    # 自我知识可塑性
    selfkb = []
    for r in c.execute("SELECT kind, text, plasticity, uses, wins, losses "
                       "FROM self_knowledge ORDER BY plasticity DESC"):
        selfkb.append({"kind": r["kind"], "text": r["text"],
                       "plasticity": round(float(r["plasticity"]), 2),
                       "uses": r["uses"], "wins": r["wins"], "losses": r["losses"]})

    return {"overview": overview, "typology": typology, "traits": traits,
            "card": card, "graph": graph, "history": history, "memories": mem,
            "days": days, "selfkb": selfkb, "generated": utcnow()}


HTML = r"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>识海 · __NAME__</title>
<style>
:root{--bg:#0e1116;--panel:#161b23;--line:#242c38;--txt:#d7dee8;--dim:#7b8798;
--acc:#7aa2f7;--acc2:#bb9af7;--warm:#e0af68;--good:#9ece6a;--bad:#f7768e}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.6 -apple-system,"Segoe UI",system-ui,sans-serif}
header{padding:22px 28px 10px;border-bottom:1px solid var(--line)}
h1{margin:0;font-size:20px;font-weight:600;letter-spacing:.5px}
h1 small{color:var(--dim);font-weight:400;font-size:13px;margin-left:10px}
.kpis{display:flex;gap:26px;flex-wrap:wrap;margin-top:14px}
.kpi{min-width:78px}
.kpi b{display:block;font-size:20px;font-weight:600;font-variant-numeric:tabular-nums}
.kpi span{color:var(--dim);font-size:12px}
main{padding:20px 28px 60px;display:grid;gap:18px;
grid-template-columns:repeat(auto-fit,minmax(420px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.card h2{margin:0 0 4px;font-size:13px;font-weight:600;color:var(--acc);letter-spacing:.6px;text-transform:uppercase}
.card p.hint{margin:0 0 12px;color:var(--dim);font-size:12px}
.wide{grid-column:1/-1}
svg{display:block;width:100%;overflow:visible}
.node text{font-size:10px;fill:var(--txt)}
.link{stroke-linecap:round}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:8px;font-size:11px;color:var(--dim)}
.legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px}
ul.self{list-style:none;padding:0;margin:0}
ul.self li{display:flex;gap:10px;align-items:center;padding:5px 0;border-bottom:1px dashed var(--line);font-size:12.5px}
ul.self li:last-child{border:0}
.bar{height:6px;border-radius:3px;background:#222a36;flex:0 0 90px;overflow:hidden}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--acc),var(--acc2))}
.tag{font-size:10.5px;color:var(--dim);border:1px solid var(--line);padding:0 5px;border-radius:4px}
pre.card-text{white-space:pre-wrap;font:12.5px/1.65 ui-monospace,Consolas,monospace;color:var(--txt);margin:0;max-height:300px;overflow:auto}
.heat{display:flex;gap:3px}
.heat .d{width:12px;height:12px;border-radius:2px;background:#1d242f}
footer{color:var(--dim);font-size:11px;padding:0 28px 28px}
</style></head><body>
<header>
  <h1>识海 <small>__SUB__</small></h1>
  <div class="kpis" id="kpis"></div>
</header>
<main>
  <section class="card wide"><h2>性格图谱</h2>
    <p class="hint">核心记忆是支点, 撑起性格倾向; 同向互相加固, 反向形成张力。</p>
    <svg id="graph" viewBox="0 0 900 460"></svg>
    <div class="legend" id="glegend"></div>
  </section>
  <section class="card"><h2>特质雷达</h2><p class="hint">七维 trait, 从性格图谱上读出。</p>
    <svg id="radar" viewBox="0 0 320 300"></svg></section>
  <section class="card"><h2>人格漂移</h2><p class="hint">历次人格快照的维度变化 —— 性格是被经历推着走的。</p>
    <svg id="drift" viewBox="0 0 460 280"></svg><div class="legend" id="dlegend"></div></section>
  <section class="card wide"><h2>记忆衰减</h2>
    <p class="hint">横轴时间(天), 纵轴剩余强度。核心记忆豁免衰减(高亮), 沉寂变灰。</p>
    <svg id="decay" viewBox="0 0 900 300"></svg>
    <div class="legend"><span><i style="background:#e0af68"></i>核心记忆</span>
      <span><i style="background:#7aa2f7"></i>普通记忆</span>
      <span><i style="background:#3b4350"></i>已沉寂</span></div></section>
  <section class="card"><h2>日记与好感</h2><p class="hint">有记录的日子着色越暖 = 当天好感越高。</p>
    <div class="heat" id="heat"></div>
    <div class="legend" id="hlegend"></div></section>
  <section class="card"><h2>自我知识可塑性</h2><p class="hint">条越长越稳固; 用了会变硬, 错多了会淡出。</p>
    <ul class="self" id="selfkb"></ul></section>
  <section class="card wide"><h2>人格卡</h2><pre class="card-text" id="card"></pre></section>
</main>
<footer>生成于 __GEN__ · 识海 shihai</footer>
<script>
const D = __DATA__;
const NS="http://www.w3.org/2000/svg";
const el=(n,a={})=>{const e=document.createElementNS(NS,n);for(const k in a)e.setAttribute(k,a[k]);return e;};
const $=s=>document.querySelector(s);

/* ---- 概览 ---- */
(function(){
  const o=D.overview, k=[
    ["事件",o.events],["核心",o.core],["沉寂",o.dormant],["节点",o.nodes],
    ["边",o.edges],["语义",o.semantic],["召回",o.recalls],["日记",o.diaries],
    ["好感",(o.warmth>0?"+":"")+o.warmth.toFixed(1)],["自我知识",o.selfkb]];
  $("#kpis").innerHTML=k.map(([a,b])=>`<div class="kpi"><b>${b}</b><span>${a}</span></div>`).join("");
})();

/* ---- 性格图谱: 中心 → trait → 事件 ---- */
(function(){
  const svg=$("#graph"), W=900,H=460, cx=W/2, cy=H/2;
  const g=D.graph, fulcrums=g.fulcrums||[], braids=g.braids||[];
  if(!fulcrums.length){svg.appendChild(el("text",{x:cx,y:cy,"text-anchor":"middle",fill:"#7b8798",
    "font-size":"13"})).textContent="还没有核心记忆, 性格图谱还是白纸。";return;}
  // 按 trait 聚合
  const byT={};
  fulcrums.forEach(f=>{(byT[f.trait]=byT[f.trait]||[]).push(f)});
  const traits=Object.keys(byT);
  const R=150, pos={};
  traits.forEach((t,i)=>{
    const a=-Math.PI/2+i*2*Math.PI/traits.length;
    pos[t]={x:cx+R*Math.cos(a),y:cy+R*Math.sin(a),a};
  });
  // 编织线(先画, 压在节点下)
  braids.forEach(b=>{
    const A=pos[b.a],B=pos[b.b]; if(!A||!B)return;
    svg.appendChild(el("line",{x1:A.x,y1:A.y,x2:B.x,y2:B.y,
      stroke:b.kind==="reinforce"?"#7aa2f7":"#f7768e",
      "stroke-width":Math.min(4,1+b.weight*1.6),"stroke-opacity":.55,"class":"link"}));
  });
  // 支点(事件)围着对应 trait 散开
  fulcrums.forEach(f=>{
    const p=pos[f.trait]; if(!p)return;
    const sibs=byT[f.trait], idx=sibs.indexOf(f), n=sibs.length;
    const spread=0.55, ang=p.a+(idx-(n-1)/2)*(spread/Math.max(1,n-1||1));
    const rr=R*0.52+f.strength*26;
    const x=cx+rr*Math.cos(ang), y=cy+rr*Math.sin(ang);
    const c=el("circle",{cx:x,cy:y,r:3+5*f.strength,
      fill:f.direction>0?"#bb9af7":"#f7768e","fill-opacity":.85});
    c.appendChild(el("title")).textContent=`事件#${f.event_id} ${f.note} (强度 ${f.strength})`;
    svg.appendChild(c);
    svg.appendChild(el("line",{x1:x,y1:y,x2:p.x,y2:p.y,stroke:"#2f3a4b","stroke-width":.8}));
  });
  // trait 节点
  const TL={caution:"谨慎",warmth:"亲和",assertiveness:"主张",curiosity:"好奇",
    persistence:"坚韧",guardedness:"封闭",self_blame:"自责"};
  traits.forEach(t=>{
    const p=pos[t], sum=byT[t].reduce((a,f)=>a+f.strength*f.direction,0);
    const r=10+Math.min(10,Math.abs(sum)*7);
    svg.appendChild(el("circle",{cx:p.x,cy:p.y,r:r,
      fill:sum>=0?"#7aa2f7":"#f7768e","fill-opacity":.22,stroke:sum>=0?"#7aa2f7":"#f7768e",
      "stroke-width":1.5}));
    const tx=el("text",{x:p.x,y:p.y+3,"text-anchor":"middle","font-size":"10.5",fill:"#d7dee8"});
    tx.textContent=TL[t]||t; svg.appendChild(tx);
  });
  // 中心
  svg.appendChild(el("circle",{cx:cx,cy:cy,r:26,fill:"#1b2431",stroke:"#2f3a4b"}));
  const ct=el("text",{x:cx,y:cy+4,"text-anchor":"middle","font-size":"11",fill:"#7b8798"});
  ct.textContent="我"; svg.appendChild(ct);
  const ge=$("#glegend");
  ge.innerHTML=`<span><i style="background:#7aa2f7"></i>同向加固 ${braids.filter(b=>b.kind==="reinforce").length}</span>
    <span><i style="background:#f7768e"></i>张力 ${braids.filter(b=>b.kind==="tension").length}</span>
    <span><i style="background:#bb9af7"></i>正向支点</span><span><i style="background:#f7768e"></i>反向支点</span>
    <span>${g.summary||""}</span>`;
})();

/* ---- 雷达 ---- */
(function(){
  const svg=$("#radar"), cx=160, cy=150, R=110;
  const LAB={caution:"谨慎",warmth:"亲和",assertiveness:"主张",curiosity:"好奇",
    persistence:"坚韧",guardedness:"封闭",self_blame:"自责"};
  const keys=Object.keys(LAB), t=D.traits||{};
  for(let ring=1;ring<=4;ring++){
    const r=R*ring/4, pts=keys.map((_,i)=>{
      const a=-Math.PI/2+i*2*Math.PI/keys.length;
      return `${cx+r*Math.cos(a)},${cy+r*Math.sin(a)}`;}).join(" ");
    svg.appendChild(el("polygon",{points:pts,fill:"none",stroke:"#242c38"}));
  }
  keys.forEach((k,i)=>{
    const a=-Math.PI/2+i*2*Math.PI/keys.length;
    svg.appendChild(el("line",{x1:cx,y1:cy,x2:cx+R*Math.cos(a),y2:cy+R*Math.sin(a),
      stroke:"#242c38"}));
    const tx=el("text",{x:cx+(R+16)*Math.cos(a),y:cy+(R+16)*Math.sin(a)+4,
      "text-anchor":"middle","font-size":"10.5",fill:"#7b8798"});
    tx.textContent=LAB[k]; svg.appendChild(tx);
  });
  if(Object.keys(t).length){
    const pts=keys.map((k,i)=>{
      const a=-Math.PI/2+i*2*Math.PI/keys.length, v=t[k]||0;
      return `${cx+R*v*Math.cos(a)},${cy+R*v*Math.sin(a)}`;}).join(" ");
    svg.appendChild(el("polygon",{points:pts,fill:"#7aa2f7","fill-opacity":.22,
      stroke:"#7aa2f7","stroke-width":1.6}));
  }
})();

/* ---- 漂移折线 ---- */
(function(){
  const svg=$("#drift"), W=460,H=280, L=36,B=28,T=12,Rr=10;
  const hist=D.history||[];
  const colors={caution:"#e0af68",warmth:"#9ece6a",assertiveness:"#f7768e",
    curiosity:"#7dcfff",persistence:"#bb9af7",guardedness:"#c0caf5",self_blame:"#ff9e64"};
  if(hist.length<2){
    const tx=el("text",{x:W/2,y:H/2,"text-anchor":"middle",fill:"#7b8798","font-size":"12"});
    tx.textContent=hist.length?"只有 1 次快照, 再跑几次 tick 就能看漂移。":"还没有人格快照。";
    svg.appendChild(tx);return;}
  const keys=Object.keys(colors);
  keys.forEach(k=>{
    const pts=hist.map((h,i)=>{
      const x=L+(W-L-Rr)*(i/(hist.length-1));
      const y=T+(H-T-B)*(1-(h[k]||0));
      return `${x},${y}`;}).join(" ");
    svg.appendChild(el("polyline",{points:pts,fill:"none",stroke:colors[k],
      "stroke-width":1.6,"stroke-opacity":.9}));
  });
  [0,.25,.5,.75,1].forEach(v=>{
    const y=T+(H-T-B)*(1-v);
    svg.appendChild(el("line",{x1:L,y1:y,x2:W-Rr,y2:y,stroke:"#1d242f"}));
    const tx=el("text",{x:L-6,y:y+3,"text-anchor":"end","font-size":"9",fill:"#7b8798"});
    tx.textContent=v; svg.appendChild(tx);
  });
  const TL2={caution:"谨慎",warmth:"亲和",assertiveness:"主张",curiosity:"好奇",
    persistence:"坚韧",guardedness:"封闭",self_blame:"自责"};
  $("#dlegend").innerHTML=keys.map(k=>
    `<span><i style="background:${colors[k]}"></i>${TL2[k]||k}</span>`).join("");
})();

/* ---- 记忆衰减散点 ---- */
(function(){
  const svg=$("#decay"), W=900,H=300, L=40,B=34,T=12,Rr=14;
  const mem=D.memories||[], maxAge=Math.max(1,...mem.map(m=>m.age));
  [0,.5,1].forEach(v=>{
    const y=T+(H-T-B)*(1-v);
    svg.appendChild(el("line",{x1:L,y1:y,x2:W-Rr,y2:y,stroke:"#1d242f"}));
    const tx=el("text",{x:L-6,y:y+3,"text-anchor":"end","font-size":"9",fill:"#7b8798"});
    tx.textContent=v.toFixed(1); svg.appendChild(tx);
  });
  mem.forEach(m=>{
    const x=L+(W-L-Rr)*(m.age/maxAge), y=T+(H-T-B)*(1-m.strength);
    const c=el("circle",{cx:x,cy:y,r:m.core?6:4,
      fill:m.dormant?"#3b4350":(m.core?"#e0af68":"#7aa2f7"),
      "fill-opacity":m.dormant?.6:.85});
    c.appendChild(el("title")).textContent=
      `#${m.id} ${m.summary}\n${m.age} 天前 · 强度 ${m.strength}${m.core?" · 核心":""}`;
    svg.appendChild(c);
  });
  ["0",Math.round(maxAge/2)+"天",maxAge+"天"].forEach((lab,i,arr)=>{
    const x=L+(W-L-Rr)*(i/2);
    const tx=el("text",{x:x,y:H-B+16,"text-anchor":i===0?"start":i===2?"end":"middle",
      "font-size":"10",fill:"#7b8798"});
    tx.textContent=lab; svg.appendChild(tx);
  });
})();

/* ---- 日记热力 ---- */
(function(){
  const box=$("#heat"), days=D.days||[];
  if(!days.length){box.innerHTML='<span class="hint">还没有日记。</span>';return;}
  const map={}; days.forEach(d=>map[d.day]=d);
  const first=new Date(days[0].day), last=new Date(days[days.length-1].day);
  const start=new Date(first); start.setDate(start.getDate()-start.getDay());
  const cells=[];
  for(let d=new Date(start); d<=last; d.setDate(d.getDate()+1)){
    const key=d.toISOString().slice(0,10), rec=map[key];
    const alpha=rec?Math.min(1,.25+Math.abs(rec.warmth)):.0;
    const col=rec?(rec.warmth>=0?"224,175,104":"247,118,142"):"29,36,47";
    cells.push(`<div class="d" title="${key}${rec?" · "+rec.mood+" · 好感 "+(rec.warmth>0?"+":"")+rec.warmth:""}"
      style="background:rgba(${col},${rec?alpha:1})"></div>`);
    if(d.getDay()===6)cells.push('<div style="width:100%"></div>');
  }
  box.style.flexWrap="wrap"; box.style.maxWidth="420px";
  box.innerHTML=cells.join("");
  $("#hlegend").innerHTML=`<span>共 ${days.length} 天有记录</span>`;
})();

/* ---- 自我知识 ---- */
(function(){
  const ul=$("#selfkb"), rows=D.selfkb||[];
  if(!rows.length){ul.innerHTML='<li class="hint">还没有自我知识。</li>';return;}
  ul.innerHTML=rows.map(r=>`<li><span class="tag">${r.kind}</span>
    <span style="flex:1">${r.text}</span>
    <span class="bar"><i style="width:${Math.round(r.plasticity*100)}%"></i></span>
    <span style="color:#7b8798;font-size:11px">${r.plasticity.toFixed(2)}</span></li>`).join("");
})();

$("#card").textContent = D.card || "(人格卡尚未生成)";
</script></body></html>"""


def render(store, path=None, *, persona_engine=None, typology_engine=None):
    """生成单文件 HTML 仪表盘。返回 (路径, 字节数)。"""
    data = collect(store, persona_engine=persona_engine,
                   typology_engine=typology_engine)
    name = data["overview"].get("name") or "agent"
    t = data["typology"] or {}
    sub = ""
    if t:
        sub = "荣格主导 %s · 九型 %sd%d · 健康 %.2f" % (
            t.get("jung_dominant", "?"), t.get("ennea_type", 0),
            t.get("ennea_wing", 0), t.get("health", 0))
    html = (HTML
            .replace("__NAME__", name)
            .replace("__SUB__", sub)
            .replace("__GEN__", data["generated"])
            .replace("__DATA__", json.dumps(data, ensure_ascii=False)))
    if path is None:
        path = os.path.join(os.getcwd(), "shihai-viz.html")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path, len(html.encode("utf-8"))
