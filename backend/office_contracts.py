"""Versioned, source-traceable reference-based course office design geometry.

This is an explicitly adopted NEW design, not an invented reconstruction of
all unavailable original drawings. Coordinates m; section mm; actions kN.
"""
from __future__ import annotations
import copy,hashlib,json,math
from collections import defaultdict
from pathlib import Path
import numpy as np
from explicit_model import normalize

SCHEMA='OfficeDesign/1.0'
SOURCE_SHA='a5ee1f63370e5c0db7ef5a0dfa6d3ed00d5e1ebad9af6323a620761a601258af'


def bundle_hash(bundle):
 def canonical(value):
  if isinstance(value,float) and math.isfinite(value) and value.is_integer():return int(value)
  if isinstance(value,dict):return {k:canonical(v) for k,v in value.items()}
  if isinstance(value,(list,tuple)):return [canonical(v) for v in value]
  return value
 return hashlib.sha256(json.dumps(canonical(bundle),sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def geometry_model(bundle):
 tables=copy.deepcopy(bundle['tables']);tables.pop('Office_Design',None)
 model,errors=normalize(tables)
 if errors:raise ValueError('；'.join(errors))
 return model


def reference_case():
 legacy=json.loads((Path(__file__).resolve().parents[1]/'examples/longyan-selfweight/input.json').read_text())
 xbase=[0.,8.,15.,23.,30.,38.];ys=[0.,7.,9.5,16.5]
 columns=[(x,y) for y in ys for x in (sorted(xbase+[4.,34.]) if y in (0.,7.) else xbase)]
 tables={'Project':[{'field_id':'project_name','value':'龙岩办公楼 参考布置课程设计方案'}], 'Materials':copy.deepcopy(legacy['Materials']),'Sections':copy.deepcopy(legacy['Sections']),'Nodes':[],'Members':[], 'Floor_Loads':[{'荷载类别':'构件自重','数值':1.}], 'Nodal_Loads':[],'Member_Loads':[], 'Office_Design':[{'mode':'full_office','schema':SCHEMA}]}
 for section in tables['Sections']:
  section['product_type']='welded_plate_box' if str(section['shape']).upper()=='BOX' else 'welded_H' if 'WELDED' in str(section['shape']).upper() else 'hot_rolled_H'
 material=next(m['material_id'] for m in tables['Materials'] if '355' in str(m.get('grade','')))
 node_map={};physical=[];panels=[];walls=[];stairs=[]
 def node(x,y,z):
  key=tuple(round(v,9) for v in (x,y,z))
  if key not in node_map:
   nid='N%04d'%(len(node_map)+1);node_map[key]=nid
   tables['Nodes'].append({'node_id':nid,'x':key[0],'y':key[1],'z':key[2],**dict.fromkeys(('ux','uy','uz','rx','ry','rz'),int(z==0))})
  return node_map[key]
 def member(pid,a,b,section,kind,role):
  physical.append({'physical_member_id':pid,'a':a,'b':b,'section_id':section,'material_id':material,'member_type':kind,'role':role,'unbraced_length_m':math.dist(a,b),'orientation_deg':0.,'release_i':int(role=='GL3'),'release_j':int(role=='GL3')})
  node(*a);node(*b)
 for floor in range(1,5):
  z=floor*4.;level=f'L{floor}'
  for i,(x,y) in enumerate(columns,1):member(f'{level}-C{i:02}',(x,y,z-4),(x,y,z),'SEC_COL_BOX_ASSUMED','column','GZ1')
  count=0
  for y in ys:
   xs=sorted(x for x,yy in columns if yy==y)
   for a,b in zip(xs,xs[1:]):
    count+=1;member(f'{level}-GX{count:02}',(a,y,z),(b,y,z),'SEC_HN600','beam','GL2')
  count=0
  for x in sorted(set(x for x,y in columns)):
   yy=sorted(y for xx,y in columns if xx==x)
   for a,b in zip(yy,yy[1:]):
    count+=1;member(f'{level}-GY{count:02}',(x,a,z),(x,b,z),'SEC_HN600','beam','GL2')
  count=0
  for a,b in ((0.,8.),(15.,23.),(30.,38.)):
   for low,high in ((9.5,16.5),)+(((0.,7.),) if a==15. or floor==4 else ()):
    for x in (a+2,a+4,a+6):
     # Roof stair zones already have the x=4/34 primary frame beam.
     if low==0 and a in (0.,30.) and x==a+4:continue
     count+=1;member(f'{level}-SY{count:02}',(x,low,z),(x,high,z),'SEC_H550','beam','GL3')
    for x0,x1 in zip((a,a+2,a+4,a+6),(a+2,a+4,a+6,b)):
     panels.append({'id':f'{level}-P{len(panels)+1}','floor':floor,'z_m':z,'rect_m':[x0,x1,low,high],'span_axis':'X','use':'roof' if floor==4 else 'office'})
  for a,b in ((8.,15.),(23.,30.)):
   for low,high in ((0.,7.),(9.5,16.5)):
    yy=[low+(high-low)*k/3 for k in range(4)]
    for y in yy[1:-1]:
     count+=1;member(f'{level}-SX{count:02}',(a,y,z),(b,y,z),'SEC_H550','beam','GL3')
    for y0,y1 in zip(yy,yy[1:]):panels.append({'id':f'{level}-P{len(panels)+1}','floor':floor,'z_m':z,'rect_m':[a,b,y0,y1],'span_axis':'Y','use':'roof' if floor==4 else 'office'})
  for a,b in zip(xbase,xbase[1:]):panels.append({'id':f'{level}-P{len(panels)+1}','floor':floor,'z_m':z,'rect_m':[a,b,7.,9.5],'span_axis':'Y','use':'roof' if floor==4 else 'office'})
  if floor<4:
   for a,b in ((0.,8.),(30.,38.)):
    for y in (0.,7.):stairs.append({'id':f'{level}-STAIR-{a:g}-{y:g}','floor':floor,'a':[a,y,z],'b':[b,y,z],'dead_kN_m':28.,'live_kN_m':12.5})
 # Split all intersecting horizontal beams; endpoints along any physical beam
 # are sufficient here because GL3 families do not cross inside panels.
 for m in physical:
  if m['member_type']=='beam' and m['role']=='GL2':
   a,b=np.array(m['a']),np.array(m['b']);outer=(abs(a[0]-b[0])<1e-8 and a[0] in (0.,38.)) or (abs(a[1]-b[1])<1e-8 and a[1] in (0.,16.5))
   walls.append({'id':'WALL-'+m['physical_member_id'],'physical_member_id':m['physical_member_id'],'floor':int(a[2]/4),'dead_kN_m':6. if outer else 4.,'placement':'user_confirmed_design_assumption'})
 points=list(node_map)
 for m in physical:
  a,b=np.array(m['a'],float),np.array(m['b'],float);delta=b-a;L=float(np.linalg.norm(delta));stations=[]
  for p in points:
   t=float(np.dot(np.array(p)-a,delta)/(L*L))
   if -1e-8<=t<=1+1e-8 and np.linalg.norm(np.array(p)-a-t*delta)<1e-7:stations.append((max(0.,min(1.,t)),p))
  stations=sorted({round(t,10):(t,p) for t,p in stations}.values())
  for k,((t0,p0),(t1,p1)) in enumerate(zip(stations,stations[1:]),1):
   row={key:value for key,value in m.items() if key not in ('a','b')};row.update(member_id=f'{m["physical_member_id"]}.{k:02}',i_node=node(*p0),j_node=node(*p1),length_m=math.dist(p0,p1),release_i=m['release_i'] if k==1 else 0,release_j=m['release_j'] if k==len(stations)-1 else 0,notes='参考二层图为基础的新课程设计；用户已确认标准层/屋面与墙梯假定，非原3D3S逐杆恢复')
   tables['Members'].append(row)
 assumptions=[{'id':key,'description':description,'status':'user_confirmed_design_assumption','confirmed_date':'2026-11-05'} for key,description in (
  ('geometry','三个楼面层采用图示标准层；屋面覆盖楼梯区补GL3支承；不凑原552杆件'),('stairs','两处8×7m楼梯区楼面开洞；两X边承托恒28/活12.5kN/m'),('walls','内侧GL2线载4，外围GL2线载6kN/m；GL3不分配墙载'),('project','一般办公、50年、安全等级二级、γ0=1、标准设防类'),('supports','GL2刚接，GL3双弯矩释放，柱脚固定；梁端防扭且翘曲自由，无中间楼板侧向支承'),('stiffeners','需要的支承/横向加劲肋作为新设计计算项；不冒充原输入'),('optimization','允许梁柱完整截面及加劲肋改型，不加支撑/不减荷'),('handoff','楼板/楼梯本体、连接、柱脚、地基基础由组员完成并实现列明性能要求'))]
 return {'schema_version':SCHEMA,'scope':'office_superstructure','tables':tables,'columns_per_floor':[list(c) for c in columns],'physical_members':physical,'panels':panels,'walls':walls,'stairs':stairs,'diaphragm':'rigid_in_plane','compression_flange_slab_restraint':False,'assumptions':assumptions,'parameters':{'floor_dead_kPa':4.5,'roof_dead_kPa':5.5,'office_live_kPa':3.5,'roof_live_kPa':.5,'wind_basic_kPa':.35,'terrain':'C','seismic_intensity':6,'ag_g':.05,'site_class':'IV','seismic_group':2,'Tg_s':.9,'normative_Tg_s':.75,'Tg_basis':'用户采用谱平台延长值0.90s，不称第二组IV类规范表值；表值0.75s另存','damping_ratio':.04,'importance_factor':1.,'beam_deflection_denominator':400,'live_mass_factor':.5,'lateral_restraint':'end_fork_warping_free','global_drift_limit_denominator':250},'source':{'document':'案例验证.docx','sha256':SOURCE_SHA,'plan':'image5.png 二层结构平面','load_pages':[8,9],'legacy_input':'examples/longyan-selfweight/input.json','classification':'reference_based_new_course_design'},'exclusions':['slab_and_stair_bodies','connections','column_bases','foundations_and_geotechnics']}


def validate_office_bundle(bundle):
 errors=[];digest=None
 try:
  digest=bundle_hash(bundle)
  if bundle.get('schema_version')!=SCHEMA:raise ValueError('办公楼契约版本不支持')
  if bundle.get('scope')!='office_superstructure' or bundle.get('diaphragm')!='rigid_in_plane' or bundle.get('compression_flange_slab_restraint') is not False:raise ValueError('本办公楼课程入口仅支持已采用面内刚性楼板且不计受压翼缘楼板约束的上部框架')
  p=bundle['parameters']
  for key,value in {'seismic_intensity':6,'ag_g':.05,'site_class':'IV','seismic_group':2,'normative_Tg_s':.75,'terrain':'C','live_mass_factor':.5}.items():
   if p.get(key)!=value:raise ValueError('当前版本尚未实现该设计条件的独立适配：'+key)
  for key in ('floor_dead_kPa','roof_dead_kPa','office_live_kPa','roof_live_kPa','wind_basic_kPa','Tg_s','damping_ratio','importance_factor','beam_deflection_denominator','global_drift_limit_denominator'):
   value=p.get(key)
   if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or (key in ('Tg_s','damping_ratio','importance_factor','beam_deflection_denominator','global_drift_limit_denominator') and value<=0):raise ValueError('办公楼参数需为有效非负数：'+key)
  if p['importance_factor']!=1 or p['global_drift_limit_denominator']!=250 or not .01<=p['damping_ratio']<=.1 or not 0<p['Tg_s']<=1.2:raise ValueError('重要性、层间限值或谱参数超出本课程实现范围')
  ref=reference_case()
  if set(p)-set(ref['parameters']):raise ValueError('存在当前版本不支持的参数字段')
  if bundle['panels']!=ref['panels']:raise ValueError('当前入口限定已确认参考楼板/洞口布置；变更布置需独立适配与复核')
  geometry_keys={'Nodes':('node_id','x','y','z','ux','uy','uz','rx','ry','rz'),'Members':('member_id','i_node','j_node','member_type','role','physical_member_id','release_i','release_j','orientation_deg','unbraced_length_m')}
  for table,keys in geometry_keys.items():
   canonical=lambda rows:sorted([tuple(row.get(key,0) for key in keys) for row in rows],key=lambda row:str(row[0]))
   if canonical(bundle['tables'][table])!=canonical(ref['tables'][table]):raise ValueError('当前入口限定已确认四层参考杆系和支承；不可静默更改几何/释放：'+table)
  for table,keys in (('walls',('id','physical_member_id','floor')),('stairs',('id','floor','a','b'))):
   if len(bundle[table])!=len(ref[table]) or any(any(row[k]!=expected[k] for k in keys) for row,expected in zip(bundle[table],ref[table])):raise ValueError('墙梯布置超出已采用课程范围：'+table)
   for row in bundle[table]:
    for k in ('dead_kN_m','live_kN_m'):
     if k in row and (isinstance(row[k],bool) or not isinstance(row[k],(int,float)) or row[k]<0):raise ValueError('墙梯荷载需为非负数')
  model=geometry_model(bundle)
  for section in model['sections'].values():
   if section['section_id'] not in {m['section_id'] for m in model['members'].values()}:continue
   expected='welded_plate_box' if str(section['shape']).upper() in ('BOX','RHS','SHS') else 'welded_H' if str(section['shape']).upper()=='H-WELDED' else 'hot_rolled_H'
   if section.get('product_type')!=expected:raise ValueError('当前材料强度表与截面产品类型不匹配：'+section['section_id'])
  for member in model['members'].values():
   a=model['nodes'][member['i_node']]['xyz'];b=model['nodes'][member['j_node']]['xyz']
   if member['member_type']=='column' and (abs(a[0]-b[0])>1e-8 or abs(a[1]-b[1])>1e-8):raise ValueError('当前办公楼楼层模型不支持斜柱')
   if member['member_type']=='beam' and abs(a[2]-b[2])>1e-8:raise ValueError('当前办公楼楼层模型不支持斜梁')
  for panel in bundle['panels']:
   x0,x1,y0,y1=panel['rect_m']
   if not x1>x0 or not y1>y0:raise ValueError('楼面区域尺寸无效：'+panel['id'])
  for m in bundle['tables']['Members']:
   if not m.get('physical_member_id') or not math.isfinite(float(m.get('unbraced_length_m',0))) or m['unbraced_length_m']+1e-7<m['length_m']:raise ValueError('物理构件/无支撑段信息缺失或小于计算段')
 except (ValueError,KeyError,TypeError) as exc:errors.append(str(exc));model=None
 confirmed=bool(bundle.get('assumptions')) and all(a.get('status')=='user_confirmed_design_assumption' for a in bundle.get('assumptions',[]))
 return {'ok':not errors,'errors':errors,'design_inputs_confirmed':confirmed,'nodes':len(model['nodes']) if model else 0,'members':len(model['members']) if model else 0,'input_sha256':digest}
