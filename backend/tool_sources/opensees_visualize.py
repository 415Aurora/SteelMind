"""生成双向跨距参数化的钢框架空间几何交互视图 HTML。"""
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
    if isinstance(data.get("payload"), dict) and len(data) == 1:
        data = data["payload"]
    # Also accept the complete JSON result returned by opensees_frame_verify.
    if isinstance(data.get("parameters"), dict):
        statuses = data.get("member_checks") or data.get("checks") or []
        data = {**data["parameters"], "member_checks": statuses,
                "analysis_results": data.get("results") or data.get("analysis_results") or {},
                "member_check_csv_url": data.get("member_check_csv_url", ""),
                "member_check_csv_text": data.get("member_check_csv_text", ""),
                "member_check_run_id": data.get("member_check_run_id", "")}
    geometry = data.get("geometry") or data
    bays_x = int(geometry.get("bays_x", geometry.get("bays", 1)))
    bays_z = int(geometry.get("bays_z", 1))
    stories = int(geometry.get("stories", 1))
    if not 1 <= bays_x <= 50 or not 1 <= bays_z <= 50 or not 1 <= stories <= 50:
        raise ValueError("X/Z 方向跨数和层数范围应为 1 到 50")
    node_count = (bays_x + 1) * (bays_z + 1) * (stories + 1)
    member_count = stories * ((bays_x + 1) * (bays_z + 1) + bays_x * (bays_z + 1) + bays_z * (bays_x + 1))
    if node_count > 4000 or member_count > 8000:
        raise ValueError("模型规模过大，三维展示限制为不超过 4000 个节点和 8000 根构件")
    spans_x = _numbers(geometry.get("bay_widths_x_m", geometry.get("bay_widths_m", geometry.get("bay_m"))),
                       bays_x, "bay_widths_x_m", 6)
    spans_z = _numbers(geometry.get("bay_widths_z_m", geometry.get("bay_depth_m")),
                       bays_z, "bay_widths_z_m", 6)
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
    results = data.get("analysis_results") or data.get("results") or {}
    analysis_members = {str(item.get("member_id")): item for item in results.get("members", [])
                        if isinstance(item, dict) and item.get("member_id")}
    supplied_checks = {str(item.get("member_id")): item for item in checks
                       if isinstance(item, dict) and item.get("member_id")}
    member_checks = {}
    for member_id in set(analysis_members) | set(supplied_checks):
        member_checks[member_id] = {**analysis_members.get(member_id, {}),
                                    **supplied_checks.get(member_id, {})}
        if not member_checks[member_id].get("demands"):
            source = member_checks[member_id]
            member_checks[member_id]["demands"] = source.get("analysis_demands") or {
                key: source[key] for key in ("N_kn", "Mx_kNm", "My_kNm", "V_kn", "Vy_kn", "Vz_kn", "T_kNm", "deflection_mm")
                if key in source
            }
    member_statuses = {member_id: item.get("passed") for member_id, item in member_checks.items()}
    member_utilizations = {}
    for member_id, item in member_checks.items():
        values = item.get("utilization_components") or {}
        candidates = [float(value) for value in values.values()
                      if isinstance(value, (int, float)) and math.isfinite(float(value))]
        if isinstance(item.get("utilization"), (int, float)) and math.isfinite(float(item["utilization"])):
            candidates.append(float(item["utilization"]))
        if candidates:
            member_utilizations[member_id] = max(candidates)
    node_displacements = [
        {"x_m": float(item["x_m"]), "y_m": float(item["y_m"]), "z_m": float(item.get("z_m", 0.0)),
         "ux_mm": float(item.get("ux_mm", 0.0)), "uy_mm": float(item.get("uy_mm", 0.0)),
         "uz_mm": float(item.get("uz_mm", 0.0))}
        for item in results.get("model_nodes", [])
        if isinstance(item, dict) and all(key in item for key in ("x_m", "y_m"))
    ]
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
        "bays_x": bays_x,
        "bays_z": bays_z,
        "stories": stories,
        "spans_x_m": spans_x,
        "spans_z_m": spans_z,
        "story_heights_m": heights,
        "base_support": geometry.get("base_support", "fixed"),
        "beam_name": str(beam_name),
        "column_name": str(column_name),
        "steel_grade": str(mat.get("name", mat.get("steel_grade", "未指定"))),
        "member_statuses": member_statuses,
        "member_checks": member_checks,
        "member_utilizations": member_utilizations,
        "node_displacements": node_displacements,
        "beam_shape": beam_shape,
        "column_shape": column_shape,
        "member_shapes": member_shapes,
        "member_check_csv_url": data.get("member_check_csv_url", ""),
        "member_check_csv_text": data.get("member_check_csv_text", ""),
        "member_check_run_id": data.get("member_check_run_id", ""),
    }


def _section_shape(name):
    if not name:
        return None
    props = _get_section(str(name))
    if not props or not all(key in props for key in ("h", "b", "tw", "t1")):
        return None
    return {"name": props["name"], "h_mm": float(props["h"]), "b_mm": float(props["b"]),
            "tw_mm": float(props["tw"]), "tf_mm": float(props["t1"]),
            "root_radius_mm": float(props["root_radius_mm"]),
            "catalog_standard": props["catalog_standard"], "catalog_id": props["catalog_id"],
            "A_mm2": float(props["A"]), "Ix_mm4": float(props["Ix"]), "Iy_mm4": float(props["Iy"])}


@tool
def draw_steel_section(payload: str) -> str:
    """根据本地合并截面库中的型号返回尺寸与截面特性；WH-前缀表示焊接Q235截面。"""
    try:
        data = json.loads(payload) if isinstance(payload, str) else dict(payload)
        name = data.get("section") or data.get("name") or ""
        shape = _section_shape(name)
        if not shape:
            return json.dumps({"ok": False, "section": name,
                               "message": "该型号不在本地合并截面库中；请选择热轧H型钢或WH-前缀焊接Q235截面，不接受自定义几何。"}, ensure_ascii=False)
        return json.dumps({"ok": True, "profile": "H", "units": "mm", "source": "GB/T 11263-2024 附录A 表A.1",
                           "shape": shape}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)


def _build_html_base(model):
    # JSON is embedded only after escaping HTML-significant characters.
    model_json = json.dumps(model, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SteelMind · OpenSees 框架三维查看器</title>
<style>
:root{color-scheme:dark;--bg:#08131f;--panel:#102234;--line:#294459;--teal:#39d0bd;--gold:#f2a94b;--text:#e8f1f7;--muted:#9eb4c4}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 18% 0,#17334a 0,transparent 42%),var(--bg);font:15px/1.45 "Segoe UI","Microsoft YaHei",sans-serif;color:var(--text);height:100vh;overflow:hidden}
.app{height:100%;display:grid;grid-template-rows:auto 1fr auto;gap:12px;padding:16px 18px}.top{display:flex;align-items:center;justify-content:space-between;gap:16px}.brand{display:flex;gap:12px;align-items:center}.mark{width:38px;height:38px;border-radius:12px;background:linear-gradient(145deg,#42dac2,#248b9b);display:grid;place-items:center;color:#06212a;font-weight:900;font-size:20px}.title{font-size:19px;font-weight:750}.sub{color:var(--muted);font-size:12px;margin-top:2px}.actions{display:flex;gap:8px;flex-wrap:wrap}.btn{border:1px solid #38556c;color:var(--text);background:#142a3b;padding:8px 12px;border-radius:9px;cursor:pointer;font-weight:650}.btn:hover{border-color:var(--teal);color:var(--teal)}
.stage{position:relative;min-height:0;border:1px solid #27445a;border-radius:16px;overflow:hidden;background:linear-gradient(180deg,rgba(15,35,51,.7),rgba(6,17,28,.92));box-shadow:0 18px 60px #0005}canvas{width:100%;height:100%;display:block;touch-action:none;cursor:grab}canvas.dragging{cursor:grabbing}.hud{position:absolute;pointer-events:none;background:#0a1925cc;border:1px solid #355168;border-radius:11px;padding:10px 12px;backdrop-filter:blur(8px)}.stats{top:14px;left:14px;display:flex;flex-wrap:wrap;gap:7px 14px;max-width:calc(100% - 190px)}.stat b{display:block;font-size:17px;color:#fff}.stat span{font-size:10px;color:var(--muted);letter-spacing:.05em}.legend{right:14px;top:14px;display:grid;gap:8px;font-size:12px}.swatch{display:inline-block;width:17px;height:4px;border-radius:3px;margin-right:7px;vertical-align:middle}.hint{left:14px;bottom:14px;color:#bdd0dc;font-size:12px}.axis{right:14px;bottom:14px;color:#8fa8b8;font-size:11px}.inspector{position:absolute;z-index:3;right:14px;top:128px;bottom:48px;width:min(370px,calc(100% - 28px));overflow:auto;background:#091824f2;border:1px solid #42647b;border-radius:13px;padding:14px;box-shadow:0 15px 45px #0008;display:none}.inspector.open{display:block}.inspector-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.inspector h3{font-size:16px;margin:0;color:#eaf5fa}.inspector-close{border:1px solid #355168;background:#142a3b;color:#dceaf2;border-radius:7px;padding:4px 8px;cursor:pointer}.member-meta{color:#a9c1d0;font-size:12px;line-height:1.65;margin:9px 0 12px}.section-panel{border:1px solid #294458;border-radius:10px;background:#102334;padding:10px;margin:0 0 12px}.section-title{font-size:12px;font-weight:700;color:#e8f1f7;margin:0 0 8px}.section-drawing{width:100%;height:150px;display:block;background:#091824;border-radius:7px}.section-dimensions{color:#a9c1d0;font-size:11px;line-height:1.6;margin-top:7px;white-space:pre-line}.check-list{display:grid;gap:8px}.check-item{border:1px solid #294458;border-radius:9px;padding:9px;background:#102334}.check-item b{display:flex;justify-content:space-between;gap:8px;font-size:12px}.check-item p{color:#bdd0dc;font-size:12px;line-height:1.5;margin:6px 0 0;overflow-wrap:anywhere}.check-pass{color:#44dec5}.check-fail{color:#ff7780}.check-empty{color:#a9c1d0;font-size:13px;line-height:1.6}.foot{display:flex;justify-content:space-between;gap:16px;color:var(--muted);font-size:11px}.badge{padding:5px 9px;border:1px solid #355168;border-radius:99px;color:#b9d0de;white-space:nowrap}
@media(max-width:650px){.app{padding:10px;gap:8px}.top{align-items:flex-start}.actions{gap:5px}.btn{padding:6px 8px}.sub{display:none}.title{font-size:15px}.stats{gap:6px 8px;max-width:calc(100% - 150px)}.stat b{font-size:14px}.legend{font-size:10px}.foot{font-size:10px}.foot .notice{max-width:70%}.inspector{top:112px;bottom:42px;right:8px;width:min(330px,calc(100% - 16px))}}
</style></head><body><div class="app">
<header class="top"><div class="brand"><div class="mark">S</div><div><div class="title">OpenSees 框架 · 交互式三维查看</div><div class="sub" id="subtitle">SteelMind 双向柱网空间几何视图</div></div></div><div class="actions"><button class="btn" id="loadValidationCsv" type="button">读取验算 CSV</button><input id="validationCsvFile" type="file" accept=".csv,text/csv" hidden><button class="btn" id="viewIso">轴测</button><button class="btn" id="viewX">X 向立面</button><button class="btn" id="viewZ">Z 向立面</button><button class="btn" id="reset">复位视角</button></div></header>
<main class="stage"><canvas id="view" aria-label="可拖拽旋转的双向钢框架空间几何模型，点击梁柱查看验算指标与截面图"></canvas><div class="hud stats" id="stats"></div><div class="hud legend"><div><i class="swatch" style="background:#39d0bd"></i>梁构件 · 未验算</div><div><i class="swatch" style="background:#f2a94b"></i>柱构件 · 未验算</div><div><i class="swatch" style="background:#ff5c67"></i>验算未通过</div><div><i class="swatch" style="background:#44dec5"></i>验算通过</div><div><i class="swatch" style="background:#b5c7d4;height:7px;width:7px;border-radius:50%"></i>节点</div><div id="failedList" style="color:#ff9aa1"></div></div><aside class="inspector" id="memberInspector" aria-live="polite"><div class="inspector-head"><h3 id="inspectorTitle">构件信息</h3><button class="inspector-close" id="inspectorClose" type="button">关闭</button></div><div class="member-meta" id="inspectorMeta"></div><section class="section-panel"><h4 class="section-title">截面形状与尺寸</h4><svg class="section-drawing" id="sectionDrawing" viewBox="0 0 260 150" role="img" aria-label="构件截面示意"></svg><div class="section-dimensions" id="sectionDimensions"></div></section><div class="check-list" id="inspectorChecks"></div></aside><div class="hud hint">点击构件查看截面与已有验算数据　·　拖动旋转　·　滚轮缩放　·　Shift/右键拖动平移</div><div class="hud axis">X/Z 双向柱网　·　Y 竖向</div></main>
<footer class="foot"><span class="notice">展示 X-Z 双向空间框架；验算结果按完整构件编号匹配，未匹配记录的构件保持未验算。</span><span class="badge" id="csvStatus">验算 CSV 尚未载入</span><span class="badge" id="support"></span></footer>
</div><script>
const M=__MODEL_JSON__,canvas=document.getElementById('view'),ctx=canvas.getContext('2d');
const xs=[0];for(const v of M.spans_x_m)xs.push(xs.at(-1)+v);const zs=[0];for(const v of M.spans_z_m)zs.push(zs.at(-1)+v);const ys=[0];for(const v of M.story_heights_m)ys.push(ys.at(-1)+v);
const nodes=[];for(let j=0;j<=M.stories;j++)for(let k=0;k<=M.bays_z;k++)for(let i=0;i<=M.bays_x;i++)nodes.push([xs[i],ys[j],zs[k]]);
let yaw=-.58,pitch=.28,zoom=1,panX=0,panY=0,drag=null,selectedMember=null,pickableMembers=[];
function refreshValidationSummary(){const failedMembers=Object.entries(M.member_statuses||{}).filter(([,passed])=>passed===false).map(([id])=>id),beamCount=M.stories*(M.bays_x*(M.bays_z+1)+M.bays_z*(M.bays_x+1)),columnCount=(M.bays_x+1)*(M.bays_z+1)*M.stories;document.getElementById('stats').innerHTML=`<div class="stat"><b>${M.bays_x} × ${M.bays_z}</b><span>X/Z 向跨数</span></div><div class="stat"><b>${M.stories}</b><span>层</span></div><div class="stat"><b>${nodes.length}</b><span>节点</span></div><div class="stat"><b>${beamCount}</b><span>梁</span></div><div class="stat"><b>${columnCount}</b><span>柱</span></div><div class="stat"><b style="color:${failedMembers.length?'#ff6974':'#44dec5'}">${failedMembers.length}</b><span>未通过</span></div>`;const failedList=document.getElementById('failedList');if(failedList)failedList.textContent=failedMembers.length?'未通过：'+failedMembers.join('、'):''}refreshValidationSummary();
const totalX=M.spans_x_m.reduce((a,b)=>a+b,0),totalZ=M.spans_z_m.reduce((a,b)=>a+b,0);document.getElementById('subtitle').textContent=`X 向 ${M.bays_x} 跨 / ${totalX} m · Z 向 ${M.bays_z} 跨 / ${totalZ} m · ${M.stories} 层 · ${M.beam_name} / ${M.column_name} · ${M.steel_grade}`;
document.getElementById('support').textContent=`柱脚：${M.base_support==='pinned'?'铰接':'刚接'}`;
function resize(){const dpr=Math.min(devicePixelRatio||1,2),r=canvas.getBoundingClientRect();canvas.width=Math.round(r.width*dpr);canvas.height=Math.round(r.height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}
function draw(){const w=canvas.clientWidth,h=canvas.clientHeight;if(!w||!h)return;ctx.clearRect(0,0,w,h);pickableMembers=[];
 const maxX=xs.at(-1),maxY=ys.at(-1),maxZ=zs.at(-1),cx=w/2+panX,cy=h*.55+panY,cyaw=Math.cos(yaw),syaw=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch);
 const projectedWidth=Math.abs(cyaw)*maxX+Math.abs(syaw)*maxZ,projectedHeight=maxY*Math.abs(cp)+(Math.abs(syaw)*maxX+Math.abs(cyaw)*maxZ)*Math.abs(sp),base=Math.min((w-210)/Math.max(projectedWidth,1),(h-180)/Math.max(projectedHeight,1))*zoom;
 function project(p){const x=p[0]-maxX/2,y=p[1]-maxY/2,z=p[2]-maxZ/2,xx=x*cyaw+z*syaw,zz=-x*syaw+z*cyaw,yy=y*cp-zz*sp,depth=y*sp+zz*cp;const f=1800/(1800+depth*base);return [cx+xx*base*f,cy-yy*base*f,depth]}
 // Plan grid and faint floor reference.
 ctx.strokeStyle='#233a4b';ctx.lineWidth=1;ctx.setLineDash([3,7]);for(const x of xs){const a=project([x,0,0]),b=project([x,0,maxZ]);ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke()}for(const z of zs){const a=project([0,0,z]),b=project([maxX,0,z]);ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke()}ctx.setLineDash([]);
 const columns=[],beams=[];for(let i=0;i<=M.bays_x;i++)for(let k=0;k<=M.bays_z;k++)for(let j=0;j<M.stories;j++){const id=`C-S${j+1}-X${i+1}-Z${k+1}`;columns.push({id,checkId:id,kind:'column',pair:[[xs[i],ys[j],zs[k]],[xs[i],ys[j+1],zs[k]]]})}for(let j=1;j<=M.stories;j++){for(let k=0;k<=M.bays_z;k++)for(let i=0;i<M.bays_x;i++){const id=`BX-S${j}-Z${k+1}-G${i+1}`;beams.push({id,checkId:id,kind:'beam',pair:[[xs[i],ys[j],zs[k]],[xs[i+1],ys[j],zs[k]]]})}for(let i=0;i<=M.bays_x;i++)for(let k=0;k<M.bays_z;k++){const id=`BZ-S${j}-X${i+1}-G${k+1}`;beams.push({id,checkId:id,kind:'beam',pair:[[xs[i],ys[j],zs[k]],[xs[i],ys[j],zs[k+1]]]})}}
 const allMembers=[...columns,...beams].map(item=>{const a=project(item.pair[0]),b=project(item.pair[1]);return{...item,a,b,depth:(a[2]+b[2])/2}}).sort((a,b)=>b.depth-a.depth);
 function member(item){const width=item.kind==='column'?6:5,baseColor=item.kind==='column'?'#f2a94b':'#39d0bd',status=M.member_statuses?.[item.checkId],color=status===false?'#ff5c67':status===true?'#44dec5':baseColor,{a,b}=item;pickableMembers.push(item);ctx.lineCap='round';if(selectedMember===item.id){ctx.strokeStyle='#fff2a8';ctx.lineWidth=width+5;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke()}ctx.strokeStyle=color;ctx.lineWidth=width;ctx.shadowColor=color;ctx.shadowBlur=7;ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();ctx.shadowBlur=0;ctx.strokeStyle='#ffffff66';ctx.lineWidth=Math.max(1,width*.22);ctx.beginPath();ctx.moveTo(a[0],a[1]-width*.18);ctx.lineTo(b[0],b[1]-width*.18);ctx.stroke()}
 allMembers.forEach(member);
 for(const n of nodes){const p=project(n);ctx.fillStyle='#e4eef4';ctx.strokeStyle='#143243';ctx.lineWidth=2;ctx.beginPath();ctx.arc(p[0],p[1],3.2,0,Math.PI*2);ctx.fill();ctx.stroke()}
 ctx.fillStyle='#9eb4c4';ctx.font='12px Segoe UI,Microsoft YaHei';const origin=project([0,0,0]),xend=project([Math.min(maxX,2),0,0]),yend=project([0,Math.min(maxY,2),0]),zend=project([0,0,Math.min(maxZ,2)]);ctx.fillText('X',xend[0]+6,xend[1]);ctx.fillText('Y',yend[0]+6,yend[1]);ctx.fillText('Z',zend[0]+6,zend[1]);
}
function showMember(id,checkId=id){selectedMember=id;const item=M.member_checks?.[checkId],status=M.member_statuses?.[checkId],isBeam=id.startsWith('B'),panel=document.getElementById('memberInspector'),checks=document.getElementById('inspectorChecks');document.getElementById('inspectorTitle').textContent=`${id} · ${isBeam?'梁':'柱'}验算`;const values=item?.demands||{},fmt=(v,u)=>v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v))?`${legendNumber(v)} ${u}`:'未提供',overall=item?(status?'综合结论：当前提交验算项均通过':status===false?'综合结论：至少一项未通过':'综合结论：有验算记录，状态未明确'):'综合结论：该空间构件未验算';document.getElementById('inspectorMeta').textContent=`${overall}\n截面：${item?.section||'未提供'}　|　钢材：${item?.steel||'未提供'}　|　跨度：${fmt(item?.span_m,'m')}\n轴力 N：${fmt(values.N_kn,'kN')}　弯矩 Mx：${fmt(values.Mx_kNm,'kN·m')}　My：${fmt(values.My_kNm,'kN·m')}\n剪力 Vy：${fmt(values.Vy_kn,'kN')}　Vz：${fmt(values.Vz_kn,'kN')}　扭矩 T：${fmt(values.T_kNm,'kN·m')}\n挠度：${fmt(values.deflection_mm,'mm')}`;checks.replaceChildren();if(!item){const empty=document.createElement('div');empty.className='check-empty';empty.textContent='该构件未包含在本次 OpenSees 三维分析结果中。请确认 CSV 与当前模型为同一次运行。';checks.append(empty)}else if(!Array.isArray(item.checks)||!item.checks.length){const empty=document.createElement('div');empty.className='check-empty';empty.textContent=item.error||item.result||'未返回机器可读验算明细。';checks.append(empty)}else for(const check of item.checks){const card=document.createElement('section'),heading=document.createElement('b'),label=document.createElement('span'),badge=document.createElement('span'),text=document.createElement('p');card.className='check-item';label.textContent=check.item||'验算项';badge.className=check.passed?'check-pass':'check-fail';badge.textContent=check.passed?'通过':'未通过';heading.append(label,badge);text.textContent=check.text||'无详细说明';card.append(heading,text);checks.append(card)}panel.classList.add('open');draw()}
function showSectionForMember(id,checkId=id){const role=id.startsWith('B')?'梁':'柱',item=M.member_checks?.[checkId],shape=M.member_shapes?.[checkId]||(role==='梁'?M.beam_shape:M.column_shape),svg=document.getElementById('sectionDrawing'),dims=document.getElementById('sectionDimensions');svg.replaceChildren();if(!shape){dims.textContent=`${role}截面：${item?.section||M[role==='梁'?'beam_name':'column_name']||'未知'}\n未提供可绘制的 h、b、tw、tf 参数；当前仅显示截面名称，不以示意图冒充实际截面。`;return}const h=shape.h_mm,b=shape.b_mm,tw=shape.tw_mm,tf=shape.tf_mm,pad=14,scale=Math.min((260-pad*2)/b,(150-pad*2)/h),width=b*scale,height=h*scale,x=(260-width)/2,y=(150-height)/2,c=b/2,points=[[0,0],[b,0],[b,tf],[c+tw/2,tf],[c+tw/2,h-tf],[b,h-tf],[b,h],[0,h],[0,h-tf],[c-tw/2,h-tf],[c-tw/2,tf],[0,tf]].map(([px,py])=>`${(x+px*scale).toFixed(2)},${(y+py*scale).toFixed(2)}`).join(' '),polygon=document.createElementNS('http://www.w3.org/2000/svg','polygon');polygon.setAttribute('points',points);polygon.setAttribute('fill','#39d0bd');polygon.setAttribute('stroke','#e8f1f7');polygon.setAttribute('stroke-width','2');svg.append(polygon);dims.textContent=`${shape.name}　单位：mm\nh=${h} · b=${b} · 腹板 tw=${tw} · 翼缘 tf=${tf}\nA=${Number(shape.A_mm2).toFixed(0)} mm² · Ix=${Number(shape.Ix_mm4).toExponential(3)} mm⁴ · Iy=${Number(shape.Iy_mm4).toExponential(3)} mm⁴\nr=${shape.root_radius_mm} mm · Source: ${shape.catalog_standard} ${shape.catalog_id} (schematic omits fillets)`}
const showMemberWithSection=showMember;showMember=function(id,checkId=id){showMemberWithSection(id,checkId);showSectionForMember(id,checkId);const item=M.member_checks?.[checkId],meta=document.getElementById('inspectorMeta'),fmtMetric=(value,unit)=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value))?`${legendNumber(value)} ${unit}`:'未提供';if(item){meta.textContent+=`\n计算长度：${fmtMetric(item.calculation_length_m,'m')}　|　最大应力：${fmtMetric(item.max_stress_N_mm2,'N/mm²')}`}else{meta.textContent+='\n当前模型结果中没有此构件编号的分析与验算记录；请核对是否载入了同一次运行的结果。'}};
function parseValidationCsv(text){const rows=[];let row=[],cell='',quoted=false;for(let i=0;i<text.length;i++){const ch=text[i];if(quoted){if(ch==='"'&&text[i+1]==='"'){cell+='"';i++}else if(ch==='"')quoted=false;else cell+=ch}else if(ch==='"')quoted=true;else if(ch===','){row.push(cell);cell=''}else if(ch==='\n'){row.push(cell.replace(/\r$/,''));rows.push(row);row=[];cell=''}else cell+=ch}if(cell.length||row.length){row.push(cell.replace(/\r$/,''));rows.push(row)}if(!rows.length)return[];const headers=rows.shift().map((value,index)=>index===0?value.replace(/^\uFEFF/,''):value);return rows.filter(values=>values.some(value=>value!=='')).map(values=>Object.fromEntries(headers.map((header,index)=>[header,values[index]??''])))}
function numberOrNull(value){if(value===undefined||value===null||value==='')return null;const result=Number(value);return Number.isFinite(result)?result:null}
function applyValidationCsv(text){const rows=parseValidationCsv(text),statusValue=value=>value==='通过'||value==='是'||value==='true'?true:value==='未通过'||value==='否'||value==='false'?false:null;if(!rows.length)throw new Error('CSV 中没有构件验算记录');let loaded=0;for(const row of rows){const id=String(row.member_id||'').trim();if(!id)continue;let checks=[];try{checks=JSON.parse(row.check_details||'[]')}catch{}const passed=statusValue(row.overall_passed),demands={N_kn:numberOrNull(row.N_kN),Mx_kNm:numberOrNull(row.Mx_kNm),My_kNm:numberOrNull(row.My_kNm),V_kn:numberOrNull(row.V_kN),Vy_kn:numberOrNull(row.Vy_kN),Vz_kn:numberOrNull(row.Vz_kN),T_kNm:numberOrNull(row.T_kNm),deflection_mm:numberOrNull(row.deflection_mm)};M.member_checks[id]={...(M.member_checks?.[id]||{}),member_id:id,member_type:row.member_type,section:row.section,steel:row.steel,passed,demands,checks,calculation_length_m:numberOrNull(row.calculation_length_m),max_stress_N_mm2:numberOrNull(row.max_stress_N_mm2)};M.member_statuses[id]=passed;loaded++}if(!loaded)throw new Error('CSV 未包含有效 member_id');document.getElementById('csvStatus').textContent=`已载入 ${loaded} 根构件验算记录`;refreshValidationSummary();draw();if(selectedMember){const selected=pickableMembers.find(item=>item.id===selectedMember);if(selected)showMember(selected.id,selected.checkId)}}
const applyValidationCsvBase=applyValidationCsv;applyValidationCsv=function(text){applyValidationCsvBase(text);for(const row of parseValidationCsv(text)){const id=String(row.member_id||'').trim(),values={h_mm:numberOrNull(row.h_mm),b_mm:numberOrNull(row.b_mm),tw_mm:numberOrNull(row.tw_mm),tf_mm:numberOrNull(row.tf_mm)};if(id&&Object.values(values).every(value=>Number.isFinite(value)&&value>0))M.member_shapes[id]={name:row.section,...values,A_mm2:numberOrNull(row.A_mm2),Ix_mm4:numberOrNull(row.Ix_mm4),Iy_mm4:numberOrNull(row.Iy_mm4),root_radius_mm:numberOrNull(row.root_radius_mm),catalog_standard:row.catalog_standard||'本地截面库',catalog_id:row.catalog_id||row.section}}if(selectedMember){const selected=pickableMembers.find(item=>item.id===selectedMember);if(selected)showMember(selected.id,selected.checkId)}};
const csvFileInput=document.getElementById('validationCsvFile');document.getElementById('loadValidationCsv').addEventListener('click',async()=>{const button=document.getElementById('loadValidationCsv'),status=document.getElementById('csvStatus');button.disabled=true;status.textContent='正在读取 validate_result.csv…';try{if(M.member_check_csv_text){applyValidationCsv(M.member_check_csv_text);return}if(M.member_check_csv_url){const response=await fetch(M.member_check_csv_url,{cache:'no-store'});if(!response.ok)throw new Error(`读取失败（HTTP ${response.status}）`);applyValidationCsv(await response.text());return}csvFileInput.click()}catch(error){status.textContent=`自动读取失败：${error.message}；请选择本地 CSV`;csvFileInput.click()}finally{button.disabled=false}});csvFileInput.addEventListener('change',async()=>{const file=csvFileInput.files?.[0];if(!file)return;try{applyValidationCsv(await file.text())}catch(error){document.getElementById('csvStatus').textContent=`CSV 载入失败：${error.message}`}finally{csvFileInput.value=''}});
window.addEventListener('message',event=>{if(event.source!==window.parent)return;const data=event.data||{};if(data.type==='steelmind-validation-csv'&&typeof data.csv_text==='string'){try{applyValidationCsv(data.csv_text)}catch(error){document.getElementById('csvStatus').textContent=`CSV 载入失败：${error.message}`}}else if(data.type==='steelmind-load-embedded-validation-csv'){if(M.member_check_csv_text||M.member_check_csv_url)document.getElementById('loadValidationCsv').click();else document.getElementById('csvStatus').textContent='当前模型未附带工作流验算 CSV；请在主网页选择本地 validate_result.csv'}});
function distanceToSegment(px,py,item){const dx=item.b[0]-item.a[0],dy=item.b[1]-item.a[1],length=dx*dx+dy*dy,t=length?Math.max(0,Math.min(1,((px-item.a[0])*dx+(py-item.a[1])*dy)/length)):0;return Math.hypot(px-(item.a[0]+dx*t),py-(item.a[1]+dy*t))}
canvas.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,startX:e.clientX,startY:e.clientY,pan:e.shiftKey||e.button===2};canvas.classList.add('dragging');canvas.setPointerCapture(e.pointerId)});
canvas.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x,dy=e.clientY-drag.y;drag.x=e.clientX;drag.y=e.clientY;if(drag.pan){panX+=dx;panY+=dy}else{yaw+=dx*.009;pitch=Math.max(-1.35,Math.min(1.35,pitch+dy*.008))}draw()});
canvas.addEventListener('pointerup',e=>{if(drag&&Math.hypot(e.clientX-drag.startX,e.clientY-drag.startY)<5&&!drag.pan){const rect=canvas.getBoundingClientRect(),px=e.clientX-rect.left,py=e.clientY-rect.top,hit=pickableMembers.map(item=>({item,d:distanceToSegment(px,py,item)})).filter(x=>x.d<14).sort((a,b)=>a.d-b.d||a.item.depth-b.item.depth)[0];if(hit)showMember(hit.item.id,hit.item.checkId)}drag=null;canvas.classList.remove('dragging')});canvas.addEventListener('pointercancel',()=>{drag=null;canvas.classList.remove('dragging')});canvas.addEventListener('contextmenu',e=>e.preventDefault());document.getElementById('inspectorClose').onclick=()=>{document.getElementById('memberInspector').classList.remove('open');selectedMember=null;draw()};
canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.35,Math.min(3.5,zoom*(e.deltaY<0?1.1:.9)));draw()},{passive:false});
document.getElementById('viewIso').onclick=()=>{yaw=-.58;pitch=.28;draw()};document.getElementById('viewX').onclick=()=>{yaw=0;pitch=0;draw()};document.getElementById('viewZ').onclick=()=>{yaw=Math.PI/2;pitch=0;draw()};document.getElementById('reset').onclick=()=>{yaw=-.58;pitch=.28;zoom=1;panX=panY=0;draw()};new ResizeObserver(resize).observe(canvas);resize();
</script></body></html>'''.replace("__MODEL_JSON__", model_json)


def _build_html(model):
    """Add synchronized result layers to the draggable frame scene."""
    document = _build_html_base(model)
    def replace_once(source, old, new):
        count = source.count(old)
        if count != 1:
            raise ValueError(f"可视化模板注入点异常：期望 1 处，实际 {count} 处：{old[:80]}")
        return source.replace(old, new, 1)

    document = replace_once(document,
        '<button class="btn" id="reset">复位视角</button>',
        '<label class="mode">结果图层 <select id="renderMode">'
        '<option value="status">验算状态</option><option value="utilization">利用率</option>'
        '<option value="force">内力量值</option><option value="deformed">变形示意</option></select></label>'
        '<label class="mode">内力 <select id="forceMode">'
        '<option value="N_kn">轴力 N</option><option value="V_kn">剪力 V</option>'
        '<option value="Mx_kNm">弯矩 Mx</option></select></label>'
        '<label class="mode">变形放大 <input id="deformScale" type="range" min="1" max="100" value="20">'
        '<span id="deformScaleValue">20×</span></label>'
        '<button class="btn" id="reset">复位视角</button>')
    document, legend_count = re.subn(
        r'<div class="hud legend">.*?</div><aside class="inspector"',
        '<div class="hud legend" id="legend"></div><aside class="inspector"', document, count=1, flags=re.S)
    if legend_count != 1:
        raise ValueError("可视化模板注入点异常：未找到唯一图例区域")
    document = replace_once(document,
        '@media(max-width:650px)',
        '.mode{display:flex;align-items:center;gap:6px;color:var(--muted);font-size:11px}.mode select{border:1px solid #38556c;color:var(--text);background:#142a3b;padding:7px 8px;border-radius:8px}.mode input{width:78px;accent-color:var(--teal)}.legend{pointer-events:none}\n@media(max-width:650px)')
    document = replace_once(document,
        'let yaw=-.58,pitch=.28,zoom=1,panX=0,panY=0,drag=null,selectedMember=null,pickableMembers=[];',
        'let yaw=-.58,pitch=.28,zoom=1,panX=0,panY=0,drag=null,selectedMember=null,pickableMembers=[],renderMode="status",forceMode="Mx_kNm";'
        'const displacementMap=new Map((M.node_displacements||[]).map(d=>[`${Number(d.x_m).toFixed(6)},${Number(d.y_m).toFixed(6)},${Number(d.z_m||0).toFixed(6)}`,d]));'
        'function updateLegend(){const box=document.getElementById("legend");if(renderMode==="status")box.innerHTML="<div><i class=swatch style=background:#39d0bd></i>梁 · 未验算</div><div><i class=swatch style=background:#f2a94b></i>柱 · 未验算</div><div><i class=swatch style=background:#ff5c67></i>未通过</div><div><i class=swatch style=background:#44dec5></i>通过</div>";else if(renderMode==="utilization")box.innerHTML="<div><i class=swatch style=background:linear-gradient(90deg,#3b82f6,#facc15,#ef4444);width:54px></i>利用率 0 → 1.0+</div><div>无利用率时显示灰色</div>";else if(renderMode==="force")box.innerHTML=`<div><i class=swatch style=background:linear-gradient(90deg,#3b82f6,#facc15,#ef4444);width:54px></i>${forceMode.replace("_kn"," (kN)").replace("_kNm"," (kN·m)")}绝对值包络</div><div>按构件控制值着色，不绘制沿杆内力图</div>`;else box.innerHTML="<div>空间分析节点位移按 XYZ 三方向显示</div><div>按放大系数展示三维变形示意</div>";}'
        'updateLegend();'
        'if(!displacementMap.size)document.querySelector("#renderMode option[value=deformed]").disabled=true;')
    document = replace_once(document,
        'function project(p){const x=p[0]-maxX/2,y=p[1]-maxY/2,z=p[2]-maxZ/2,',
        'function project(p){let [px,py,pz]=p;if(renderMode==="deformed"&&displacementMap.size){const d=displacementMap.get(`${px.toFixed(6)},${py.toFixed(6)},${pz.toFixed(6)}`);if(d){const a=Number(document.getElementById("deformScale").value);px+=d.ux_mm/1000*a;py+=d.uy_mm/1000*a;pz+=d.uz_mm/1000*a}}const x=px-maxX/2,y=py-maxY/2,z=pz-maxZ/2,')
    document = replace_once(document,
        'function member(item){',
        'function heat(value,max){if(!Number.isFinite(value)||max<=0)return "#7b8994";const t=Math.max(0,Math.min(1,Math.abs(value)/max));const stops=[[59,130,246],[250,204,21],[239,68,68]],s=t<.5?0:1,u=t<.5?t*2:(t-.5)*2,a=stops[s],b=stops[s+1];return `rgb(${Math.round(a[0]+(b[0]-a[0])*u)},${Math.round(a[1]+(b[1]-a[1])*u)},${Math.round(a[2]+(b[2]-a[2])*u)})`}'
        'function memberColor(item,status,baseColor){if(renderMode==="status")return status===false?"#ff5c67":status===true?"#44dec5":baseColor;const record=M.member_checks?.[item.checkId]||{};if(renderMode==="utilization"){const u=Number(M.member_utilizations?.[item.checkId]);return Number.isFinite(u)?heat(u,1.15):"#7b8994"}if(renderMode==="force"){const v=Number(record.demands?.[forceMode]);const all=Object.values(M.member_checks||{}).map(x=>Math.abs(Number(x.demands?.[forceMode]))).filter(Number.isFinite);return Number.isFinite(v)?heat(v,Math.max(...all,0)):"#7b8994"}return baseColor}'
        'function member(item){')
    document = replace_once(document,
        "color=status===false?'#ff5c67':status===true?'#44dec5':baseColor,{a,b}=item;",
        'color=memberColor(item,status,baseColor),{a,b}=item;')
    document = replace_once(document,
        "const values=item?.demands||{},fmt=",
        "const sectionMember=pickableMembers.find(member=>member.id===id),geometrySpan=sectionMember?Math.hypot(sectionMember.pair[1][0]-sectionMember.pair[0][0],sectionMember.pair[1][1]-sectionMember.pair[0][1],sectionMember.pair[1][2]-sectionMember.pair[0][2]):null,sectionShape=M.member_shapes?.[checkId]||(isBeam?M.beam_shape:M.column_shape),values=item?.demands||{},fmt=")
    document = replace_once(document,
        "截面：${item?.section||'未提供'}　|　钢材：${item?.steel||'未提供'}　|　跨度：${fmt(item?.span_m,'m')}",
        "截面：${item?.section||sectionShape?.name||(isBeam?M.beam_name:M.column_name)||'未提供'}　|　钢材：${item?.steel||M.steel_grade||'未提供'}　|　跨度：${fmt(item?.span_m??geometrySpan,'m')}")
    document = replace_once(document,
        "document.getElementById('reset').onclick=()=>{yaw=-.58;pitch=.28;zoom=1;panX=panY=0;draw()};new ResizeObserver(resize).observe(canvas);resize();",
        "document.getElementById('reset').onclick=()=>{yaw=-.58;pitch=.28;zoom=1;panX=panY=0;draw()};"
        "document.getElementById('renderMode').onchange=e=>{renderMode=e.target.value;updateLegend();draw()};"
        "document.getElementById('forceMode').onchange=e=>{forceMode=e.target.value;updateLegend();draw()};"
        "document.getElementById('deformScale').oninput=e=>{document.getElementById('deformScaleValue').textContent=e.target.value+'×';draw()};"
        "new ResizeObserver(resize).observe(canvas);resize();")
    document = document.replace("color=memberColor(item,status,baseColor)", "color=resultMemberColor(item,status,baseColor)")
    legend_js = Path(__file__).with_name("viewer_result_legend.js").read_text(encoding="utf-8")
    document = document.replace("</script>", legend_js + "\n</script>", 1)
    return document


@tool
def opensees_frame_visualize(payload: str) -> str:
    """从 OpenSees 参数或 opensees_frame_verify 的结果中生成可拖拽旋转的 3D 几何视图。

    输入同 OpenSees 建模参数，也支持直接传入其返回 JSON（含 parameters 字段）。
    输出包含可打开的 HTML URL；鼠标拖动旋转、滚轮缩放、Shift+拖动平移。
    geometry 可填写 X/Z 两向跨数与跨度，工具生成完整空间框架几何视图；可将三维 OpenSees 构件验算记录按 member_id 映射至相应构件。
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
        beams = model["stories"] * (model["bays_x"] * (model["bays_z"] + 1) + model["bays_z"] * (model["bays_x"] + 1))
        columns = (model["bays_x"] + 1) * (model["bays_z"] + 1) * model["stories"]
        return json.dumps({"ok": True, "html_url": url, "html_content": document, "file_name": filename,
                           "bays_x": model["bays_x"], "bays_z": model["bays_z"],
                           "spans_x_m": model["spans_x_m"], "spans_z_m": model["spans_z_m"],
                           "stories": model["stories"],
                           "nodes": (model["bays_x"] + 1) * (model["bays_z"] + 1) * (model["stories"] + 1),
                           "beams": beams,
                           "columns": columns,
                           "interaction": "拖动旋转；滚轮缩放；Shift+拖动平移",
                           "notice": "双向空间框架几何可视化；仅对输入分析结果中存在相同 member_id 的构件显示计算与验算数据。"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
