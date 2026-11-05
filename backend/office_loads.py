"""Conservative-source load mapping with independent force/moment accounting."""
from __future__ import annotations
from collections import defaultdict
import math
import numpy as np
from office_contracts import geometry_model

GRAVITY=9.80665


def empty_case(case_id,kind='static'):
 return {'case_id':case_id,'kind':kind,'member_uniform_kN_m':{},'nodal_loads_kN_kNm':{},'sources':[]}


def add_uniform(case,mid,q,source):
 old=case['member_uniform_kN_m'].setdefault(mid,[0.,0.,0.])
 for i,value in enumerate(q):old[i]+=float(value)
 case['sources'].append({'member_id':mid,'q_global_kN_m':list(q),**source})


def audit_case(case,model,expected_force=None,expected_moment=None):
 force=np.zeros(3);moment=np.zeros(3)
 for mid,q in case['member_uniform_kN_m'].items():
  m=model['members'][mid];a=np.array(model['nodes'][m['i_node']]['xyz']);b=np.array(model['nodes'][m['j_node']]['xyz']);f=np.array(q)*m['length_m'];force+=f;moment+=np.cross((a+b)/2,f)
 for nid,f in case['nodal_loads_kN_kNm'].items():force+=np.array(f[:3]);moment+=np.cross(model['nodes'][nid]['xyz'],f[:3])+np.array(f[3:])
 ef=np.asarray(expected_force if expected_force is not None else force);em=np.asarray(expected_moment if expected_moment is not None else moment)
 error=max(float(np.max(abs(force-ef))),float(np.max(abs(moment-em))))
 if error>max(1e-6,float(np.linalg.norm(ef))*1e-8):raise ValueError('荷载分配不守恒：'+case['case_id'])
 return {'status':'PASS','total_force_kN':force.tolist(),'total_moment_kNm':moment.tolist(),'expected_force_kN':ef.tolist(),'expected_moment_kNm':em.tolist(),'max_residual':error,'weight_kN':-float(force[2])}


def build_load_cases(bundle):
 model=geometry_model(bundle);cases={name:empty_case(name) for name in ('G','Q_OFFICE','Q_STAIR','Q_ROOF')};force={k:np.zeros(3) for k in cases};moment={k:np.zeros(3) for k in cases}
 params=bundle['parameters'];by_physical=defaultdict(list)
 for mid,m in model['members'].items():by_physical[m['physical_member_id']].append(mid)
 def expected(key,f,point):force[key]+=f;moment[key]+=np.cross(point,f)
 def line_load(case_id,axis,constant,lo,hi,z,q,source):
  # axis is direction along the support; constant is its transverse coordinate.
  segments=[]
  for mid,m in model['members'].items():
   if m['member_type']!='beam':continue
   a=np.array(model['nodes'][m['i_node']]['xyz']);b=np.array(model['nodes'][m['j_node']]['xyz'])
   other=1-axis
   if abs(a[2]-z)>1e-7 or abs(b[2]-z)>1e-7 or abs(a[other]-constant)>1e-7 or abs(b[other]-constant)>1e-7:continue
   start,end=sorted((a[axis],b[axis]));overlap=min(end,hi)-max(start,lo)
   if overlap>1e-7:
    if abs(overlap-(end-start))>1e-6:raise ValueError('面域支承边需要先切分梁：'+source['source_id'])
    segments.append((start,end,mid))
  segments.sort()
  if not segments or abs(sum(b-a for a,b,mid in segments)-(hi-lo))>1e-6:raise ValueError('楼面/楼梯支承缺失或重复：'+source['source_id'])
  for a,b,mid in segments:add_uniform(cases[case_id],mid,[0.,0.,-q],source)
  p=np.array([0.,0.,z]);p[axis]=(lo+hi)/2;p[1-axis]=constant;expected(case_id,np.array([0.,0.,-q*(hi-lo)]),p)
 floor_area=floor_weight=stair_weight=steel_weight=wall_weight=0.
 for mid,m in model['members'].items():
  s=model['sections'][m['section_id']];mat=model['materials'][m['material_id']];q=s['A']*1e-6*mat['density_t_m3']*GRAVITY
  add_uniform(cases['G'],mid,[0,0,-q],{'source_id':'STEEL-'+mid,'source_type':'member_selfweight'})
  a=np.array(model['nodes'][m['i_node']]['xyz']);b=np.array(model['nodes'][m['j_node']]['xyz']);expected('G',np.array([0.,0.,-q*m['length_m']]),(a+b)/2);steel_weight+=q*m['length_m']
 for panel in bundle['panels']:
  x0,x1,y0,y1=panel['rect_m'];area=(x1-x0)*(y1-y0);floor_area+=area;roof=panel['use']=='roof';dead=params['roof_dead_kPa'] if roof else params['floor_dead_kPa'];live=params['roof_live_kPa'] if roof else params['office_live_kPa'];qcase='Q_ROOF' if roof else 'Q_OFFICE';floor_weight+=dead*area
  for key,pressure in (('G',dead),(qcase,live)):
   source={'source_id':panel['id'],'source_type':'panel','floor':panel['floor'],'pressure_kPa':pressure,'area_m2':area,'span_axis':panel['span_axis']}
   if panel['span_axis']=='X':
    for x in (x0,x1):line_load(key,1,x,y0,y1,panel['z_m'],pressure*(x1-x0)/2,source)
   elif panel['span_axis']=='Y':
    for y in (y0,y1):line_load(key,0,y,x0,x1,panel['z_m'],pressure*(y1-y0)/2,source)
   else:raise ValueError('楼板传力方向未定义：'+panel['id'])
 for row in bundle['walls']:
  for mid in by_physical[row['physical_member_id']]:
   m=model['members'][mid];q=row['dead_kN_m'];add_uniform(cases['G'],mid,[0,0,-q],{'source_id':row['id'],'source_type':'wall','floor':row['floor']});a=np.array(model['nodes'][m['i_node']]['xyz']);b=np.array(model['nodes'][m['j_node']]['xyz']);expected('G',np.array([0.,0.,-q*m['length_m']]),(a+b)/2);wall_weight+=q*m['length_m']
 for row in bundle['stairs']:
  a,b=row['a'],row['b']
  for key,q in (('G',row['dead_kN_m']),('Q_STAIR',row['live_kN_m'])):line_load(key,0,a[1],a[0],b[0],a[2],q,{'source_id':row['id'],'source_type':'stair_support','floor':row['floor']})
  stair_weight+=row['dead_kN_m']*math.dist(a,b)
 for stiffener in bundle.get('stiffeners',[]):
  rows=[model['members'][mid] for mid in by_physical[stiffener['physical_member_id']]];axis=np.asarray(rows[0]['axes'][0]);ends=sorted({nid for row in rows for nid in (row['i_node'],row['j_node'])},key=lambda nid:float(np.dot(model['nodes'][nid]['xyz'],axis)));mat=model['materials'][rows[0]['material_id']];weight=2*stiffener['width_mm']*stiffener['thickness_mm']*stiffener['height_mm']*1e-9*mat['density_t_m3']*GRAVITY
  for nid in stiffener.get('node_ids',(ends[0],ends[-1])):
   if nid not in ends:raise ValueError('加劲肋位置不在该物理梁节点上：'+nid)
   load=cases['G']['nodal_loads_kN_kNm'].setdefault(nid,[0.]*6);load[2]-=weight;expected('G',np.array([0.,0.,-weight]),model['nodes'][nid]['xyz']);cases['G']['sources'].append({'source_id':stiffener['id'],'source_type':'end_stiffener_weight','node_id':nid,'weight_kN':weight})
 for key,case in cases.items():case['audit']=audit_case(case,model,force[key],moment[key])
 cases['G']['audit'].update(floor_area_m2=floor_area,floor_weight_kN=floor_weight,stair_weight_kN=stair_weight,steel_weight_kN=steel_weight,wall_weight_kN=wall_weight)
 return cases


def combine_cases(case_id,cases,factors):
 result=empty_case(case_id);result['factors']=dict(factors)
 for key,factor in factors.items():
  for mid,q in cases[key]['member_uniform_kN_m'].items():
   old=result['member_uniform_kN_m'].setdefault(mid,[0.,0.,0.])
   for i in range(3):old[i]+=q[i]*factor
  for nid,q in cases[key]['nodal_loads_kN_kNm'].items():
   old=result['nodal_loads_kN_kNm'].setdefault(nid,[0.]*6)
   for i in range(6):old[i]+=q[i]*factor
 return result


def build_mass_source(bundle,cases):
 model=geometry_model(bundle);weights=defaultdict(float);factor={'G':1.,'Q_OFFICE':bundle['parameters']['live_mass_factor'],'Q_STAIR':bundle['parameters']['live_mass_factor']}
 for key,scale in factor.items():
  for mid,q in cases[key]['member_uniform_kN_m'].items():
   m=model['members'][mid];w=-q[2]*m['length_m']*scale
   # Lump story-column selfweight to its upper floor, not the fixed ground.
   # All other gravity loads are consistent end-lumped to actual beam nodes.
   if m['member_type']=='column':weights[m['j_node']]+=w
   else:
    weights[m['i_node']]+=w/2;weights[m['j_node']]+=w/2
 for key,scale in factor.items():
  for nid,f in cases[key].get('nodal_loads_kN_kNm',{}).items():weights[nid]+=-f[2]*scale
 floors=[]
 for z in sorted({n['xyz'][2] for n in model['nodes'].values() if n['xyz'][2]>0}):
  rows=[(nid,w/GRAVITY) for nid,w in weights.items() if abs(model['nodes'][nid]['xyz'][2]-z)<1e-7];total=sum(m for n,m in rows)
  if total<=0:raise ValueError('楼层质量应为正')
  x=sum(model['nodes'][n]['xyz'][0]*m for n,m in rows)/total;y=sum(model['nodes'][n]['xyz'][1]*m for n,m in rows)/total
  J=sum(m*((model['nodes'][n]['xyz'][0]-x)**2+(model['nodes'][n]['xyz'][1]-y)**2) for n,m in rows)
  floors.append({'floor':len(floors)+1,'z_m':z,'mass_t':total,'centroid_m':[x,y],'polar_mass_t_m2':J,'node_mass_t':dict(rows)})
 expected=sum(cases[k]['audit']['weight_kN']*v for k,v in factor.items())/GRAVITY;total=sum(f['mass_t'] for f in floors)
 if abs(total-expected)>1e-7*max(1,expected):raise ValueError('质量源总量不守恒')
 return {'floors':floors,'total_mass_t':total,'equivalent_weight_kN':total*GRAVITY,'factors':factor,'basis':'GB55002-2021 表4.1.3；屋面活载不计入；楼梯按等效均布使用活载0.5；柱自重上层集中','scope':'楼层水平平动及面内扭转质量，竖向地震适用性另判','audit_status':'PASS'}


def build_live_influence_cases(bundle,base_cases):
 model=geometry_model(bundle);out=[]
 for parent in ('Q_OFFICE','Q_STAIR','Q_ROOF'):
  grouped={}
  for source in base_cases[parent]['sources']:
   sid=source['source_id'];case=grouped.setdefault(sid,{**empty_case(parent+'__'+sid),'parent_case_id':parent,'region_id':sid})
   add_uniform(case,source['member_id'],source['q_global_kN_m'],{k:v for k,v in source.items() if k not in ('member_id','q_global_kN_m')})
  for case in grouped.values():case['audit']=audit_case(case,model);out.append(case)
 return out


def gravity_floor_resultants(bundle,cases,factors):
 """Floor G_i and centroid for notional loads; column weight belongs upstairs."""
 model=geometry_model(bundle);weights=defaultdict(float)
 for key,factor in factors.items():
  for mid,q in cases[key]['member_uniform_kN_m'].items():
   m=model['members'][mid];weight=-q[2]*m['length_m']*factor
   if m['member_type']=='column':weights[m['j_node']]+=weight
   else:weights[m['i_node']]+=weight/2;weights[m['j_node']]+=weight/2
  for nid,f in cases[key].get('nodal_loads_kN_kNm',{}).items():weights[nid]+=-f[2]*factor
 out=[]
 for z in sorted({n['xyz'][2] for n in model['nodes'].values() if n['xyz'][2]>0}):
  rows=[(nid,w) for nid,w in weights.items() if abs(model['nodes'][nid]['xyz'][2]-z)<1e-7];total=sum(w for nid,w in rows)
  if total<=0:raise ValueError('假想荷载重力来源非正')
  out.append({'floor':len(out)+1,'z_m':z,'weight_kN':total,'centroid_m':[sum(model['nodes'][nid]['xyz'][i]*w for nid,w in rows)/total for i in (0,1)]})
 return out
