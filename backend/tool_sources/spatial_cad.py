"""True XYZ frame model plus explicitly sliced XZ/XY/ZY scheme sheets."""
from __future__ import annotations
from pathlib import Path
import json,math
import ezdxf
from steelmind_export import runtime
from steelmind_export.cad import _new_doc,_viewport,_dimension,_text,_line,_render_pdf

def _frame(layout,title,note,scale=None):
 for a,b in [((10,10),(410,10)),((410,10),(410,287)),((410,287),(10,287)),((10,287),(10,10)),((10,45),(410,45))]:_line(layout,a,b,'P-FRAME')
 _text(layout,title,18,277,4)
 _text(layout,'三维钢框架方案草稿  INCOMPLETE  非施工图',18,34,3)
 _text(layout,'几何单位 mm；Y竖向；单静力工况；连接、扭转及完整规范适用性待复核',18,24,2.5)
 _text(layout,note[:145],18,14,2.5)
 if scale:_text(layout,f'模型1:1 / 视口1:{scale:g}；M编号见构件表',240,265,2.5)

def _make(font):
 doc,layout=_new_doc(font)
 doc.layers.new('S-MEMBER',dxfattribs={'color':7});doc.appids.new('STEELMIND')
 return doc,layout

def _scale(bounds):
 x0,y0,x1,y1=bounds
 required=max((x1-x0)/280,(y1-y0)/140,1)
 for s in (1,2,5,10,20,25,50,75,100,150,200,250,500,1000,2000,5000,10000,20000,50000,100000):
  if s>=required:return s
 raise ValueError('图纸尺度超出支持范围')

def _save(doc,path,dimension_mm,member_ids,quality):
 doc.saveas(path);saved=ezdxf.readfile(path);audit=saved.audit()
 errors=[str(e) for e in audit.errors]
 if errors:raise ValueError(f'DXF审查失败 {path.name}: {errors}')
 dims=list(saved.modelspace().query('DIMENSION'))
 measured=[float(d.get_measurement()) for d in dims]
 if len(measured)!=len(dimension_mm) or any(not math.isclose(a,b,abs_tol=1e-4) for a,b in zip(measured,dimension_mm)):raise ValueError('DXF真实尺寸与输入不一致')
 quality.append({'file':path.name,'audit_errors':errors,'dimension_mm':measured,'members':list(member_ids),'model_units':saved.units})

def _chunks(values,step=2):
 values=sorted(set(values))
 if len(values)<2:return [(values[0],values[0])] if values else []
 spans=[b-a for a,b in zip(values,values[1:])]
 if max(spans)>4*min(spans):step=1
 return [(values[i],values[min(i+step,len(values)-1)]) for i in range(0,len(values)-1,step)]

def generate_cad(bundle,out,include_pdf=True):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);font,_=runtime.resolve_font()
 nodes={n['node_id']:n for n in bundle['nodes']};marks={m['member_id']:f'M{i:03d}' for i,m in enumerate(bundle['members'],1)}
 quality=[];files=[];covered=set();warnings=[];errors=[]
 def finish(doc,name,dimensions=(),ids=(),pdf=True):
  path=out/(name+'.dxf');_save(doc,path,dimensions,ids,quality);files.append(path)
  if pdf and include_pdf:
   try:_render_pdf(path,path.with_suffix('.pdf'),font);files.append(path.with_suffix('.pdf'))
   except Exception as e:errors.append(f'{name} PDF转换失败：{e}')
 # All slices are exact coordinate planes. No member is fabricated by joining projected nodes.
 views=[]
 for y in sorted({n['y_m'] for n in bundle['nodes'] if n['y_m']>1e-8}):views.append(('XZ',y,'y_m','x_m','z_m',f'层平面 Y={y:g}m'))
 for z in sorted({n['z_m'] for n in bundle['nodes']}):views.append(('XY',z,'z_m','x_m','y_m',f'X向立面 Z={z:g}m'))
 for x in sorted({n['x_m'] for n in bundle['nodes']}):views.append(('ZY',x,'x_m','z_m','y_m',f'Z向立面 X={x:g}m'))
 sheet_count=0
 for plane,value,fixed,u,v,title in views:
  selected=[m for m in bundle['members'] if abs(nodes[m['node_i']][fixed]-value)<1e-8 and abs(nodes[m['node_j']][fixed]-value)<1e-8]
  points=[nodes[m[k]] for m in selected for k in ('node_i','node_j')]
  if not points:continue
  for u0,u1 in _chunks([n[u] for n in points]):
   for v0,v1 in _chunks([n[v] for n in points]):
    tile=[m for m in selected if all(u0-1e-8<=nodes[m[k]][u]<=u1+1e-8 and v0-1e-8<=nodes[m[k]][v]<=v1+1e-8 for k in ('node_i','node_j'))]
    if not tile:continue
    sheet_count+=1
    if sheet_count>500:raise ValueError('超过500张分面图，请分区提交模型')
    doc,layout=_make(font);model=doc.modelspace();bounds=(u0*1000,v0*1000,u1*1000,v1*1000);scale=_scale(bounds);h=2.7*scale
    ids=[]
    for m in tile:
     a,b=nodes[m['node_i']],nodes[m['node_j']];p1=(a[u]*1000,a[v]*1000);p2=(b[u]*1000,b[v]*1000)
     line=model.add_line(p1,p2,dxfattribs={'layer':'S-MEMBER'});line.set_xdata('STEELMIND',[(1000,m['member_id']),(1000,m['section'])]);ids.append(m['member_id']);covered.add(m['member_id'])
     vertical=abs(p1[0]-p2[0])<1e-6
     _text(model,marks[m['member_id']],(p1[0]+p2[0])/2+scale,(p1[1]+p2[1])/2+3*scale,h,'S-TEXT',90 if vertical else 0)
    # Dimension adjacent actual grid levels, not a bounding-box surrogate.
    expected=[]
    us=sorted({nodes[m[k]][u]*1000 for m in tile for k in ('node_i','node_j')});vs=sorted({nodes[m[k]][v]*1000 for m in tile for k in ('node_i','node_j')})
    for a,b in zip(us,us[1:]):_dimension(model,expected,(a,v0*1000),(b,v0*1000),(a,v0*1000-9*scale),0,scale)
    for a,b in zip(vs,vs[1:]):_dimension(model,expected,(u0*1000,a),(u0*1000,b),(u0*1000-10*scale,a),90,scale)
    for support in bundle['supports']:
     n=nodes[support['node_id']]
     if abs(n[fixed]-value)>1e-8 or not(u0<=n[u]<=u1 and v0<=n[v]<=v1):continue
     x,y=n[u]*1000,n[v]*1000
     for dx in (-3,0,3):_line(model,(x+dx*scale,y),(x+(dx-2)*scale,y-4*scale),'S-SUPPORT')
     _text(model,''.join('1' if support[k] else '0' for k in ('ux','uy','uz','rx','ry','rz')),x+4*scale,y-5*scale,2.5*scale,'S-TEXT')
    _viewport(layout,(30,57,390,255),((u0+u1)*500,(v0+v1)*500),scale)
    note=f'{plane} 投影；{u[:-2]}范围 {u0:g}–{u1:g}m；{v[:-2]}范围 {v0:g}–{v1:g}m；支座六位=ux uy uz rx ry rz (1约束)'
    _frame(layout,title,note,scale)
    finish(doc,f'{sheet_count:02d}_{plane}_{value:g}_{u0:g}_{v0:g}',[d['expected_mm'] for d in expected],ids)
 if covered!=set(marks):raise ValueError('分面图未覆盖全部三维构件：'+str(set(marks)-covered))
 # Separate assembly: real XYZ coordinates in mm. Do not offer an XY-flattened browser preview.
 doc,layout=_make(font);model=doc.modelspace()
 for m in bundle['members']:
  a,b=nodes[m['node_i']],nodes[m['node_j']]
  e=model.add_line(tuple(a[k]*1000 for k in ('x_m','y_m','z_m')),tuple(b[k]*1000 for k in ('x_m','y_m','z_m')),dxfattribs={'layer':'S-MEMBER'})
  e.set_xdata('STEELMIND',[(1000,m['member_id']),(1000,m['section'])])
 _frame(layout,'三维线框原始坐标','此文件用于CAD三维视图；网页请查看配套XZ平面和XY/ZY立面，禁止按XY压扁作为整套图纸。')
 finish(doc,'90_三维线框',ids=list(marks),pdf=False)
 # Reproducible paginated member schedule, also mapping browser-visible short IDs.
 members=bundle['members']
 for page,start in enumerate(range(0,len(members),20),1):
  doc,layout=_make(font);_frame(layout,f'构件截面分配表 第{page}页','M编号与各平面/立面图一致；长度为上游几何值，未包含连接构造。')
  columns=(18,43,125,225,345)
  for x,t in zip(columns,('图中标记','完整构件编号','截面','方向 / 长度m','材料')):_text(layout,t,x,258,2.7)
  for i,m in enumerate(members[start:start+20]):
   for x,t in zip(columns,(marks[m['member_id']],m['member_id'],m['section'],f'{m["member_axis"]} / {m["span_m"]:g}',m.get('steel','未提供'))):_text(layout,t,x,247-i*9,2.5)
  finish(doc,f'80_构件表_{page:03d}')
 for i,(name,p) in enumerate(bundle['sections'].items(),1):
  doc,layout=_make(font);model=doc.modelspace();h,b,tw,tf=[p[k] for k in ('h_mm','b_mm','tw_mm','tf_mm')];scale=_scale((-b,-h,b,h))
  vertices=[(-b/2,0),(b/2,0),(b/2,tf),(tw/2,tf),(tw/2,h-tf),(b/2,h-tf),(b/2,h),(-b/2,h),(-b/2,h-tf),(-tw/2,h-tf),(-tw/2,tf),(-b/2,tf)]
  for a,c in zip(vertices,vertices[1:]+vertices[:1]):_line(model,a,c,'S-OUTLINE')
  expected=[];_dimension(model,expected,(-b/2,0),(b/2,0),(0,-10*scale),0,scale);_dimension(model,expected,(-b/2,0),(-b/2,h),(-b/2-10*scale,0),90,scale)
  _viewport(layout,(30,65,210,250),(0,h/2),scale);_frame(layout,'H/I截面示意 '+name,'圆角未深化；尺寸采用上游属性，型钢表面积/惯性矩与理想几何值不作替换。',scale)
  for j,key in enumerate(('h_mm','b_mm','tw_mm','tf_mm','A_mm2','Iy_mm4','Iz_mm4','J_mm4')):_text(layout,f'{key} = {p[key]:g}',245,235-j*15,2.7)
  _text(layout,str(p.get('catalog_standard','来源未提供')),245,100,2.7)
  finish(doc,f'85_截面_{i:03d}',[e['expected_mm'] for e in expected])
 qa={'schema_version':'SpatialCAD/1.0','source_run_id':bundle['source_run_id'],'covered_members':sorted(covered),'marks':marks,'sheets':quality,'warnings':warnings,'errors':errors}
 path=out/'cad_quality.json';path.write_text(json.dumps(qa,ensure_ascii=False,indent=2));files.append(path)
 return files,warnings,errors
