"""生成可拖拽旋转的 OpenSees 二维框架 3D 视图 HTML。"""
from __future__ import annotations

import html
import json
import math
import os
import re
from pathlib import Path
from uuid import uuid4

from langchain.tools import tool
from tools.structural_calc import _get_section


# Gateway injects these at tool-load time so the HTML is downloadable through /files/{id}.
ARTIFACT_DIR = Path(os.getenv("STEEL_ARTIFACT_DIR", Path(__file__).parent / "artifacts")).resolve()
PUBLIC_BASE = os.getenv("STEEL_TOOL_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")


def _numbers(value, count, label, default):
    if value is None:
        result = [float(default)] * count
    elif isinstance(value, (float, int)):
        result = [float(value)] * count
    elif isinstance(value, list) and len(value) == count:
        result = [float(item) for item in value]
    else:
        raise ValueError(f"{label} 应为一个数值或长度为 {count} 的数组")
    if any(not math.isfinite(v) or v <= 0 for v in result):
        raise ValueError(f"{label} 必须为有限正数")
    return result


def _normalize(payload):
    data = json.loads(payload) if isinstance(payload, str) else dict(payload)
    # Also accept the complete JSON result returned by opensees_frame_verify.
    if isinstance(data.get("parameters"), dict):
        statuses = data.get("member_checks") or data.get("checks") or []
        data = {**data["parameters"], "member_checks": statuses}
    geometry = data.get("geometry") or data
    bays = int(geometry.get("bays", 1))
    stories = int(geometry.get("stories", 1))
    if not 1 <= bays <= 50 or not 1 <= stories <= 50:
        raise ValueError("跨数和层数范围应为 1 到 50")
    spans = _numbers(geometry.get("bay_widths_m", geometry.get("bay_m")), bays, "bay_widths_m", 6)
    height_data = geometry.get("story_heights_m")
    if height_data is None and geometry.get("height_m") is not None:
        height_data = float(geometry["height_m"]) / stories
    heights = _numbers(height_data, stories, "story_heights_m", 3)
    sec = data.get("sections") or {}
    beam = sec.get("beam", {}) if isinstance(sec, dict) else {}
    column = sec.get("column", {}) if isinstance(sec, dict) else {}
    beam_name = beam.get("name", beam.get("section", "梁")) if isinstance(beam, dict) else str(beam)
    column_name = column.get("name", column.get("section", "柱")) if isinstance(column, dict) else str(column)
    beam_name = data.get("beam_section") or beam_name
    column_name = data.get("column_section") or column_name
    mat = data.get("material") or data.get("materials") or {}
    checks = data.get("member_checks") or data.get("checks") or []
    member_statuses = {str(item.get("member_id")): bool(item.get("passed"))
                       for item in checks if isinstance(item, dict) and item.get("member_id")}
    member_checks = {str(item.get("member_id")): item
                     for item in checks if isinstance(item, dict) and item.get("member_id")}
    sections = data.get("sections") or {}
    beam_def = sections.get("beam") if isinstance(sections.get("beam"), dict) else {}
    column_def = sections.get("column") if isinstance(sections.get("column"), dict) else {}
    beam_shape = _section_shape(beam_def.get("name", beam_name))
    column_shape = _section_shape(column_def.get("name", column_name))
    member_shapes = {}
    for member_id, definition in (data.get("member_sections") or {}).items():
        name = definition.get("name") if isinstance(definition, dict) else str(definition)
        shape = _section_shape(name)
        if shape:
            member_shapes[str(member_id)] = shape
    for member_id, item in member_checks.items():
        section_name = item.get("section")
        shape = _section_shape(section_name) if section_name else None
        if shape:
            member_shapes[member_id] = shape
    return {
        "bays": bays,
        "stories": stories,
        "spans_m": spans,
        "story_heights_m": heights,
        "base_support": geometry.get("base_support", "fixed"),
        "beam_name": str(beam_name),
        "column_name": str(column_name),
        "steel_grade": str(mat.get("name", mat.get("steel_grade", "未指定"))),
        "member_statuses": member_statuses,
        "member_checks": member_checks,
        "beam_shape": beam_shape,
        "column_shape": column_shape,
        "member_shapes": member_shapes,
    }


def _section_shape(name):
    if not name:
        return None
    props = _get_section(str(name))
    if not props or not all(key in props for key in ("h", "b", "tw", "t1")):
        return None
    return {"name": str(name), "h_mm": float(props["h"]), "b_mm": float(props["b"]),
            "tw_mm": float(props["tw"]), "tf_mm": float(props["t1"]),
            "A_mm2": float(props["A"]), "Ix_mm4": float(props["Ix"]), "Iy_mm4": float(props["Iy"])}


@tool
def draw_steel_section(payload: str) -> str:
    """根据型钢截面型号返回可绘制的截面几何与尺寸，支持内置 H/I 型钢及 H:hxbxtwxtf。"""
    try:
        data = json.loads(payload) if isinstance(payload, str) else dict(payload)
        name = data.get("section") or data.get("name") or ""
        shape = _section_shape(name)
        if not shape:
            return json.dumps({"ok": False, "section": name,
                               "message": "该型号没有可用于绘图的 h、b、tw、tf 几何数据；请补充截面尺寸，不会用示意形状代替实际截面。"}, ensure_ascii=False)
        return json.dumps({"ok": True, "profile": "I/H", "units": "mm", "shape": shape}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)


def _build_html(model):
    # JSON is embedded only after escaping HTML-significant characters.
    model_json = json.dumps(model, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SteelMind · OpenSees 框架三维查看器</title>
<style>
:root{color-scheme:dark;--bg:#08131f;--panel:#102234;--line:#294459;--teal:#39d0bd;--gold:#f2a94b;--text:#e8f1f7;--muted:#9eb4c4}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 18% 0,#17334a 0,transparent 42%),var(--bg);font:15px/1.45 "Segoe UI","Microsoft YaHei",sans-serif;color:var(--text);height:100vh;overflow:hidden}
.app{height:100%;display:grid;grid-template-rows:auto 1fr auto;gap:12px;padding:16px 18px}.top{display:flex;align-items:center;justify-content:space-between;gap:16px}.brand{display:flex;gap:12px;align-items:center}.mark{width:38px;height:38px;border-radius:12px;background:linear-gradient(145deg,#42dac2,#248b9b);display:grid;place-items:center;color:#06212a;font-weight:900;font-size:20px}.title{font-size:19px;font-weight:750}.sub{color:var(--muted);font-size:12px;margin-top:2px}.actions{display:flex;gap:8px;flex-wrap:wrap}.btn{border:1px solid #38556c;color:var(--text);background:#142a3b;padding:8px 12px;border-radius:9px;cursor:pointer;font-weight:650}.btn:hover{border-color:var(--teal);color:var(--teal)}
.stage{position:relative;min-height:0;border:1px solid #27445a;border-radius:16px;overflow:hidden;background:linear-gradient(180deg,rgba(15,35,51,.7),rgba(6,17,28,.92));box-shadow:0 18px 60px #0005}canvas{width:100%;height:100%;display:block;touch-action:none;cursor:grab}canvas.dragging{cursor:grabbing}.hud{position:absolute;pointer-events:none;background:#0a1925cc;border:1px solid #355168;border-radius:11px;padding:10px 12px;backdrop-filter:blur(8px)}.stats{top:14px;left:14px;display:flex;gap:14px}.stat b{display:block;font-size:17px;color:#fff}.stat span{font-size:10px;color:var(--muted);letter-spacing:.05em}.legend{right:14px;top:14px;display:grid;gap:8px;font-size:12px}.swatch{display:inline-block;width:17px;height:4px;border-radius:3px;margin-right:7px;vertical-align:middle}.hint{left:14px;bottom:14px;color:#bdd0dc;font-size:12px}.axis{right:14px;bottom:14px;color:#8fa8b8;font-size:11px}.inspector{position:absolute;z-index:3;right:14px;top:128px;bottom:48px;width:min(370px,calc(100% - 28px));overflow:auto;background:#091824f2;border:1px solid #42647b;border-radius:13px;padding:14px;box-shadow:0 15px 45px #0008;display:none}.inspector.open{display:block}.inspector-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.inspector h3{font-size:16px;margin:0;color:#eaf5fa}.inspector-close{border:1px solid #355168;background:#142a3b;color:#dceaf2;border-radius:7px;padding:4px 8px;cursor:pointer}.member-meta{color:#a9c1d0;font-size:12px;line-height:1.65;margin:9px 0 12px}.section-panel{border:1px solid #294458;border-radius:10px;background:#102334;padding:10px;margin:0 0 12px}.section-title{font-size:12px;font-weight:700;color:#e8f1f7;margin:0 0 8px}.section-drawing{width:100%;height:150px;display:block;background:#091824;border-radius:7px}.section-dimensions{color:#a9c1d0;font-size:11px;line-height:1.6;margin-top:7px;white-space:pre-line}.check-list{display:grid;gap:8px}.check-item{border:1px solid #294458;border-radius:9px;padding:9px;background:#102334}.check-item b{display:flex;justify-content:space-between;gap:8px;font-size:12px}.check-item p{color:#bdd0dc;font-size:12px;line-height:1.5;margin:6px 0 0;overflow-wrap:anywhere}.check-pass{color:#44dec5}.check-fail{color:#ff7780}.check-empty{color:#a9c1d0;font-size:13px;line-height:1.6}.foot{display:flex;justify-content:space-between;gap:16px;color:var(--muted);font-size:11px}.badge{padding:5px 9px;border:1px solid #355168;border-radius:99px;color:#b9d0de;white-space:nowrap}
@media(max-width:650px){.app{padding:10px;gap:8px}.sub{display:none}.title{font-size:15px}.stats{gap:8px}.stat b{font-size:14px}.legend{font-size:10px}.foot{font-size:10px}.foot .notice{max-width:70%}.inspector{top:112px;bottom:42px;right:8px;width:min(330px,calc(100% - 16px))}}
</style></head><body><div class="app">
<header class="top"><div class="brand"><div class="mark">S</div><div><div class="title">OpenSees 框架 · 交互式三维查看</div><div class="sub" id="subtitle">SteelMind 参数化模型几何视图</div></div></div><div class="actions"><button class="btn" id="reset">复位视角</button></div></header>
<main class="stage"><canvas id="view" aria-label="可拖拽旋转的钢框架模型，点击梁柱查看验算指标与截面图"></canvas><div class="hud stats" id="stats"></div><div class="hud legend"><div><i class="swatch" style="background:#36d2bf"></i>梁/柱验算通过或未验算</div><div><i class="swatch" style="background:#ff5c67"></i>构件验算未通过</div><div><i class="swatch" style="background:#b5c7d4;height:7px;width:7px;border-radius:50%"></i>节点</div><div id="failedList" style="color:#ff9aa1"></div></div><aside class="inspector" id="memberInspector" aria-live="polite"><div class="inspector-head"><h3 id="inspectorTitle">构件信息</h3><button class="inspector-close" id="inspectorClose" type="button">关闭</button></div><div class="member-meta" id="inspectorMeta"></div><section class="section-panel"><h4 class="section-title">截面形状与尺寸</h4><svg class="section-drawing" id="sectionDrawing" viewBox="0 0 260 150" role="img" aria-label="构件截面示意"></svg><div class="section-dimensions" id="sectionDimensions"></div></section><div class="check-list" id="inspectorChecks"></div></aside><div class="hud hint">点击梁/柱查看截面形状、尺寸及验算指标　·　拖动旋转　·　滚轮缩放　·　Shift/右键拖动平移</div><div class="hud axis">X 跨向　·　Y 竖向　·　Z 面外</div></main>
<footer class="foot"><span class="notice">模型来自二维 OpenSees 分析平面；此处增加三维视角交互，不代表已建立面外构件或空间计算模型。</span><span class="badge" id="support"></span></footer>
</div><script>
const M=__MODEL_JSON__,canvas=document.getElementById('view'),ctx=canvas.getContext('2d');
const xs=[0];for(const v of M.spans_m)xs.push(xs.at(-1)+v);const ys=[0];for(const v of M.story_heights_m)ys.push(ys.at(-1)+v);
const nodes=[];for(let j=0;j<=M.stories;j++)for(let i=0;i<=M.bays;i++)nodes.push([xs[i],ys[j],0]);
let yaw=-.48,pitch=.23,zoom=1,panX=0,panY=0,drag=null,selectedMember=null,pickableMembers=[];
const failedMembers=Object.entries(M.member_statuses||{}).filter(([,passed])=>passed===false).map(([id])=>id);document.getElementById('stats').innerHTML=`<div class="stat"><b>${M.bays}</b><span>跨</span></div><div class="stat"><b>${M.stories}</b><span>层</span></div><div class="stat"><b>${nodes.length}</b><span>节点</span></div><div class="stat"><b>${M.bays*M.stories}</b><span>梁构件</span></div><div class="stat"><b>${(M.bays+1)*M.stories}</b><span>柱构件</span></div><div class="stat"><b style="color:${failedMembers.length?'#ff6974':'#44dec5'}">${failedMembers.length}</b><span>未通过</span></div>`;document.getElementById('failedList').textContent=failedMembers.length?'未通过：'+failedMembers.join('、'):'';
document.getElementById('subtitle').textContent=`${M.beam_name} 梁 · ${M.column_name} 柱 · ${M.steel_grade} · 几何单位 m`;
document.getElementById('support').textContent=`柱脚：${M.base_support==='pinned'?'铰接':'刚接'}`;
function resize(){const dpr=Math.min(devicePixelRatio||1,2),r=canvas.getBoundingClientRect();canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}
function draw(){const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;ctx.clearRect(0,0,w,h);pickableMembers=[];
 const cx=w/2+panX,cy=h*.57+panY,cyaw=Math.cos(yaw),syaw=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);
 const maxX=xs.at(-1),maxY=ys.at(-1),base=Math.min((w-100)/Math.max(maxX,1),(h-130)/Math.max(maxY,1))*zoom;
 function project(p){let x=p[0]-maxX/2,y=p[1]-maxY/2,z=p[2];const xx=x*cyaw+z*syaw,zz=-x*syaw+z*cyaw,yy=y*cp-zz*sp,depth=y*sp+zz*cp;const f=1600/(1600+depth*base);return [cx+xx*base*f,cy-yy*base*f,depth]}
 // subtle ground reference and coordinate triad
 ctx.strokeStyle='#263e50';ctx.lineWidth=1;ctx.setLineDash([4,7]);const g1=project([0,0,0]),g2=project([maxX,0,0]);ctx.beginPath();ctx.moveTo(...g1.slice(0,2));ctx.lineTo(...g2.slice(0,2));ctx.stroke();ctx.setLineDash([]);
 const columns=[],beams=[];for(let i=0;i<=M.bays;i++)for(let j=0;j<M.stories;j++)columns.push({id:`C-S${j+1}-G${i+1}`,pair:[[xs[i],ys[j],0],[xs[i],ys[j+1],0]]});for(let j=1;j<=M.stories;j++)for(let i=0;i<M.bays;i++)beams.push({id:`B-S${j}-G${i+1}`,pair:[[xs[i],ys[j],0],[xs[i+1],ys[j],0]]});
 function member(item,base,width){const pair=item.pair,color=M.member_statuses&&M.member_statuses[item.id]===false?'#ff5c67':base,a=project(pair[0]),b=project(pair[1]);pickableMembers.push({id:item.id,a,b,depth:(a[2]+b[2])/2});ctx.lineCap='round';if(selectedMember===item.id){ctx.strokeStyle='#fff2a8';ctx.lineWidth=width+5;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke()}ctx.strokeStyle=color;ctx.lineWidth=width;ctx.shadowColor=color;ctx.shadowBlur=10;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();ctx.shadowBlur=0;ctx.strokeStyle='#ffffff55';ctx.lineWidth=Math.max(1,width*.24);ctx.beginPath();ctx.moveTo(a[0],a[1]-width*.18);ctx.lineTo(b[0],b[1]-width*.18);ctx.stroke()}
 columns.forEach(p=>member(p,'#f2a94b',6));beams.forEach(p=>member(p,'#36d2bf',5));
 for(const n of nodes){const p=project(n);ctx.fillStyle='#dceaf2';ctx.strokeStyle='#123343';ctx.lineWidth=2;ctx.beginPath();ctx.arc(p[0],p[1],3.5,0,Math.PI*2);ctx.fill();ctx.stroke()}
 ctx.fillStyle='#9eb4c4';ctx.font='12px Segoe UI,Microsoft YaHei';const origin=project([0,0,0]),xend=project([Math.min(maxX,2),0,0]),yend=project([0,Math.min(maxY,2),0]);ctx.fillText('X',xend[0]+6,xend[1]);ctx.fillText('Y',yend[0]+6,yend[1]);ctx.fillText('Z',origin[0]+12,origin[1]+12);
}
function showMember(id){selectedMember=id;const item=M.member_checks?.[id],status=M.member_statuses?.[id],panel=document.getElementById('memberInspector'),checks=document.getElementById('inspectorChecks');document.getElementById('inspectorTitle').textContent=`${id} · ${id.startsWith('B-')?'梁':'柱'}验算`;const values=item?.demands||{},fmt=(v,u)=>Number.isFinite(Number(v))?`${Number(v).toLocaleString('zh-CN',{maximumFractionDigits:3})} ${u}`:'未提供',overall=item?(status?'综合结论：当前提交验算项均通过':'综合结论：至少一项未通过'):'综合结论：未验算';document.getElementById('inspectorMeta').textContent=`${overall}\n截面：${item?.section||'未提供'}　|　钢材：${item?.steel||'未提供'}　|　跨度：${fmt(item?.span_m,'m')}\n轴力 N：${fmt(values.N_kn,'kN')}　弯矩 Mx：${fmt(values.Mx_kNm,'kN·m')}　My：${fmt(values.My_kNm,'kN·m')}\n剪力 V：${fmt(values.V_kn,'kN')}　挠度：${fmt(values.deflection_mm,'mm')}`;checks.replaceChildren();if(!item){const empty=document.createElement('div');empty.className='check-empty';empty.textContent='该构件尚无逐构件验算记录。请先运行完整工作流；仅生成几何模型时不会显示虚构的验算指标。';checks.append(empty)}else if(!Array.isArray(item.checks)||!item.checks.length){const empty=document.createElement('div');empty.className='check-empty';empty.textContent=item.error||item.result||'未返回机器可读验算明细。';checks.append(empty)}else for(const check of item.checks){const card=document.createElement('section'),heading=document.createElement('b'),label=document.createElement('span'),badge=document.createElement('span'),text=document.createElement('p');card.className='check-item';label.textContent=check.item||'验算项';badge.className=check.passed?'check-pass':'check-fail';badge.textContent=check.passed?'通过':'未通过';heading.append(label,badge);text.textContent=check.text||'无详细说明';card.append(heading,text);checks.append(card)}panel.classList.add('open');draw()}
function showSectionForMember(id){const role=id.startsWith('B-')?'梁':'柱',item=M.member_checks?.[id],shape=M.member_shapes?.[id]||(role==='梁'?M.beam_shape:M.column_shape),svg=document.getElementById('sectionDrawing'),dims=document.getElementById('sectionDimensions');svg.replaceChildren();if(!shape){dims.textContent=`${role}截面：${item?.section||M[role==='梁'?'beam_name':'column_name']||'未知'}\n未提供可绘制的 h、b、tw、tf 参数；当前仅显示截面名称，不以示意图冒充实际截面。`;return}const h=shape.h_mm,b=shape.b_mm,tw=shape.tw_mm,tf=shape.tf_mm,pad=14,scale=Math.min((260-pad*2)/b,(150-pad*2)/h),width=b*scale,height=h*scale,x=(260-width)/2,y=(150-height)/2,c=b/2,points=[[0,0],[b,0],[b,tf],[c+tw/2,tf],[c+tw/2,h-tf],[b,h-tf],[b,h],[0,h],[0,h-tf],[c-tw/2,h-tf],[c-tw/2,tf],[0,tf]].map(([px,py])=>`${(x+px*scale).toFixed(2)},${(y+py*scale).toFixed(2)}`).join(' '),polygon=document.createElementNS('http://www.w3.org/2000/svg','polygon');polygon.setAttribute('points',points);polygon.setAttribute('fill','#39d0bd');polygon.setAttribute('stroke','#e8f1f7');polygon.setAttribute('stroke-width','2');svg.append(polygon);dims.textContent=`${shape.name}　单位：mm\nh=${h} · b=${b} · 腹板 tw=${tw} · 翼缘 tf=${tf}\nA=${Number(shape.A_mm2).toFixed(0)} mm² · Ix=${Number(shape.Ix_mm4).toExponential(3)} mm⁴ · Iy=${Number(shape.Iy_mm4).toExponential(3)} mm⁴`}
const showMemberWithSection=showMember;showMember=function(id){showMemberWithSection(id);showSectionForMember(id)};
function distanceToSegment(px,py,item){const dx=item.b[0]-item.a[0],dy=item.b[1]-item.a[1],length=dx*dx+dy*dy,t=length?Math.max(0,Math.min(1,((px-item.a[0])*dx+(py-item.a[1])*dy)/length)):0;return Math.hypot(px-(item.a[0]+t*dx),py-(item.a[1]+t*dy))}
canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,pan:e.shiftKey||e.button===2};canvas.classList.add('dragging');canvas.setPointerCapture(e.pointerId)});
canvas.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;if(drag.pan){panX+=dx;panY+=dy}else{yaw+=dx*.009;pitch=Math.max(-1.35,Math.min(1.35,pitch+dy*.008))}draw()});
canvas.addEventListener('pointerup',e=>{if(drag&&Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)<5&&!drag.pan){const rect=canvas.getBoundingClientRect(),px=e.clientX-rect.left,py=e.clientY-rect.top,hit=pickableMembers.map(item=>({item,d:distanceToSegment(px,py,item)})).filter(x=>x.d<14).sort((a,b)=>a.d-b.d||b.item.depth-a.item.depth)[0];if(hit)showMember(hit.item.id)}drag=null;canvas.classList.remove('dragging')});canvas.addEventListener('pointercancel',()=>{drag=null;canvas.classList.remove('dragging')});canvas.addEventListener('contextmenu',e=>e.preventDefault());document.getElementById('inspectorClose').onclick=()=>{document.getElementById('memberInspector').classList.remove('open');selectedMember=null;draw()};
canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.35,Math.min(3.5,zoom*(e.deltaY<0?1.1:.9)));draw()},{passive:false});
document.getElementById('reset').onclick=()=>{yaw=-.48;pitch=.23;zoom=1;panX=panY=0;draw()};new ResizeObserver(resize).observe(canvas);resize();
</script></body></html>'''.replace("__MODEL_JSON__", model_json)


@tool
def opensees_frame_visualize(payload: str) -> str:
    """从 OpenSees 参数或 opensees_frame_verify 的结果中生成可拖拽旋转的 3D 几何视图。

    输入同 OpenSees 建模参数，也支持直接传入其返回 JSON（含 parameters 字段）。
    输出包含可打开的 HTML URL；鼠标拖动旋转、滚轮缩放、Shift+拖动平移。
    注意底层 OpenSees 工具是二维平面模型，视图只对该分析平面进行三维投影交互。
    """
    try:
        model = _normalize(payload)
        document = _build_html(model)
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"opensees_3d_{uuid4().hex[:12]}.html"
        artifact_id = f"{uuid4().hex}_{filename}"
        path = (ARTIFACT_DIR / artifact_id).resolve()
        if path.parent != ARTIFACT_DIR:
            raise ValueError("非法产物路径")
        path.write_text(document, encoding="utf-8")
        url = f"{PUBLIC_BASE}/files/{artifact_id}"
        return json.dumps({"ok": True, "html_url": url, "file_name": filename,
                           "nodes": (model["bays"] + 1) * (model["stories"] + 1),
                           "beams": model["bays"] * model["stories"],
                           "columns": (model["bays"] + 1) * model["stories"],
                           "interaction": "拖动旋转；滚轮缩放；Shift+拖动平移",
                           "notice": "这是 OpenSees 二维分析平面的交互式三维投影，不包含面外构件。"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
