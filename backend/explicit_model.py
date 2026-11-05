"""Explicit workbook geometry and self-weight static analysis. No catalog substitution or code-compliance claim."""
from __future__ import annotations
import copy,math,json,hashlib
import numpy as np
from solver_lock import OPENSEES_LOCK

class InputIssue(ValueError):pass

def input_hash(tables):
 return hashlib.sha256(json.dumps(tables,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def number(value,path,positive=False):
 if isinstance(value,bool):raise InputIssue(path+' 不能为布尔值')
 try:v=float(value)
 except (TypeError,ValueError):raise InputIssue(path+' 缺少有效数值')
 if not math.isfinite(v) or positive and v<=0:raise InputIssue(path+' 应为有限'+('正数' if positive else '数值'))
 return v

def flag(value,path):
 if value in (None,''):return 0
 if str(value).lower() in ('0','false'):return 0
 if str(value).lower() in ('1','true'):return 1
 raise InputIssue(path+' 仅支持0或1；端释放定义为两个局部弯矩释放，保留扭矩')

def normalize(tables):
 t={''.join(c for c in k.lower() if c.isalnum()):v for k,v in tables.items()}
 def rows(name):return t.get(name.lower().replace('_',''),[])
 errors=[]
 def unique(name,key):
  out={}
  for row in rows(name):
   ident=str(row.get(key) or '').strip()
   if not ident or ident in out:errors.append(f'{name}.{key}: 编号缺失或重复 {ident}')
   else:out[ident]=copy.deepcopy(row)
  if not out:errors.append(name+' 为空')
  return out
 nodes=unique('Nodes','node_id');sections=unique('Sections','section_id');materials=unique('Materials','material_id');members=unique('Members','member_id')
 for mid,m in members.items():
  for field,lookup in [('i_node',nodes),('j_node',nodes),('material_id',materials),('section_id',sections)]:
   if m.get(field) not in lookup:errors.append(mid+'.'+field+' 引用无效')
 used_sections={m.get('section_id') for m in members.values()};used_materials={m.get('material_id') for m in members.values()}
 for sid in used_sections:
  if sid not in sections:continue
  s=sections[sid]
  # Only resolve a complete explicit designation. Never guess HN600x200 thicknesses.
  from section_catalog import section_record
  name=str(s.get('section_name') or '').replace('×','x')
  candidate=section_record(name) or section_record('H'+name[2:] if name.upper().startswith('HN') else name)
  if candidate:
   for key,source in [('depth_mm','h_mm'),('width_mm','b_mm'),('tw_mm','tw_mm'),('tf_mm','tf_mm'),('area_mm2','area_mm2'),('Ix_mm4','Ix_mm4'),('Iy_mm4','Iy_mm4')]:
    if s.get(key) in (None,''):s[key]=candidate[source]
   s['catalog_source']=candidate['id']+' / local catalog source page '+str(candidate.get('source_pdf_page'))
  try:
   h,b,tw,tf=[number(s.get(k),f'Sections.{sid}.{k}',True) for k in ('depth_mm','width_mm','tw_mm','tf_mm')]
   if h<=2*tf or b<=2*tw:raise InputIssue(sid+' 板厚与外形尺寸矛盾')
   A,Iy,Iz=[number(s.get(k),f'Sections.{sid}.{k}',True) for k in ('area_mm2','Iy_mm4','Ix_mm4')]
   shape=str(s.get('shape','')).upper()
   if shape in ('BOX','RHS','SHS'):J=4*((h-tf)*(b-tw))**2/(2*(h-tf)/tw+2*(b-tw)/tf)
   elif shape in ('H','I','H-WELDED'):J=(2*b*tf**3+(h-2*tf)*tw**3)/3
   else:raise InputIssue(sid+' 截面形状不支持 '+shape)
   s.update(A=A,Iy=Iy,Iz=Iz,J=J,property_source='工作簿提供值；J为薄壁近似，不覆盖给定面积/惯性矩')
  except InputIssue as e:errors.append(str(e))
 for matid in used_materials:
  if matid not in materials:continue
  mat=materials[matid]
  try:
   for field in ('E_MPa','G_MPa','density_t_m3'):mat[field]=number(mat.get(field),matid+'.'+field,True)
  except InputIssue as e:errors.append(str(e))
 for nid,n in nodes.items():
  try:
   n['xyz']=[number(n.get(k),nid+'.'+k) for k in ('x','y','z')]
   n['fix']=[flag(n.get(k),nid+'.'+k) for k in ('ux','uy','uz','rx','ry','rz')]
  except InputIssue as e:errors.append(str(e))
 for mid,m in members.items():
  try:
   m['hinge_i']=flag(m.get('release_i'),mid+'.release_i');m['hinge_j']=flag(m.get('release_j'),mid+'.release_j')
   a,b=nodes.get(m.get('i_node'),{}),nodes.get(m.get('j_node'),{})
   if 'xyz' not in a or 'xyz' not in b:continue
   x=np.array(b['xyz'])-a['xyz'];length=float(np.linalg.norm(x))
   if length<1e-8:raise InputIssue(mid+' 零长构件')
   x/=length
   # Horizontal beams: local y is vertical, so gravity uses strong-axis Iz.
   # Vertical members keep the reference orientation; BOX is symmetric here.
   if abs(x[2])<.99:
    vertical=np.array([0.,0.,1.]);y=vertical-np.dot(vertical,x)*x;y/=np.linalg.norm(y);z=np.cross(x,y)
   else:
    y=np.cross(np.array([1.,0.,0.]),x);y/=np.linalg.norm(y);z=np.cross(x,y)
   angle=math.radians(number(m.get('orientation_deg') or 0,mid+'.orientation_deg'));y,z=y*math.cos(angle)+z*math.sin(angle),z*math.cos(angle)-y*math.sin(angle)
   m.update(length_m=length,axes=np.array([x,y,z]).tolist())
  except InputIssue as e:errors.append(str(e))
 weights=[row.get('数值') for row in rows('Floor_Loads') if row.get('荷载类别')=='构件自重']
 if len(weights)!=1:errors.append('Floor_Loads 必须明确给出一项构件自重系数；不会默认为零或默认示例荷载')
 else:
  try:factor=number(weights[0],'自重系数');assert factor>=0
  except (InputIssue,AssertionError):errors.append('自重系数需为有限非负值')
 if rows('Nodal_Loads') or rows('Member_Loads'):errors.append('本显式适配首版仅执行已明确的框架自重；非空节点/杆件外荷载不能静默忽略')
 if errors:return None,errors
 return {'nodes':nodes,'sections':sections,'materials':materials,'members':members,'self_weight_factor':factor,'source_tables':copy.deepcopy(tables)},[]

def run_explicit_model(tables):
 model,errors=normalize(tables)
 if errors:return {'ok':False,'status':'needs_input','errors':errors,'upstream_check_summary':'INCOMPLETE','draft':True}
 import openseespy.opensees as ops
 with OPENSEES_LOCK:
  try:
   ops.wipe();ops.model('basic','-ndm',3,'-ndf',6);tags={nid:i for i,nid in enumerate(model['nodes'],1)}
   for nid,n in model['nodes'].items():
    ops.node(tags[nid],*[v*1000 for v in n['xyz']]);ops.fix(tags[nid],*n['fix'])
   chains={};eid=0;nextnode=len(tags);weights={};total=0.;segments=8
   for ti,(mid,m) in enumerate(model['members'].items(),1):
    s=model['sections'][m['section_id']];mat=model['materials'][m['material_id']];axes=np.array(m['axes']);ops.geomTransf('Linear',ti,*axes[2])
    a=np.array(model['nodes'][m['i_node']]['xyz']);b=np.array(model['nodes'][m['j_node']]['xyz']);chain=[tags[m['i_node']]]
    for k in range(1,segments):nextnode+=1;ops.node(nextnode,*((a+(b-a)*k/segments)*1000));chain.append(nextnode)
    chain.append(tags[m['j_node']]);elements=[]
    for k,(ni,nj) in enumerate(zip(chain,chain[1:])):
     eid+=1;release=(m['hinge_i'] if k==0 else 0)+(2*m['hinge_j'] if k==segments-1 else 0)
     ops.element('elasticBeamColumn',eid,ni,nj,s['A'],mat['E_MPa'],mat['G_MPa'],s['J'],s['Iy'],s['Iz'],ti,'-releasey',release,'-releasez',release);elements.append(eid)
    q=s['A']*1e-6*mat['density_t_m3']*9.80665*model['self_weight_factor'];weights[mid]=q;total+=q*m['length_m'];chains[mid]=(chain,elements)
   ops.timeSeries('Linear',1);ops.pattern('Plain',1,1)
   for mid,m in model['members'].items():
    local=np.array(m['axes'])@np.array([0.,0.,-weights[mid]])
    for e in chains[mid][1]:ops.eleLoad('-ele',e,'-type','-beamUniform',float(local[1]),float(local[2]),float(local[0]))
   ops.constraints('Transformation');ops.numberer('RCM');ops.system('BandGeneral');ops.algorithm('Linear');ops.integrator('LoadControl',1);ops.analysis('Static')
   if ops.analyze(1)!=0:raise InputIssue('显式模型静力求解失败，检查释放和稳定性')
   ops.reactions();nodal=[];reactions=[];members=[]
   for nid,n in model['nodes'].items():
    nodal.append({'node_id':nid,'xyz_m':n['xyz'],'displacement_mm_rad':list(ops.nodeDisp(tags[nid]))})
    if any(n['fix']):reactions.append({'node_id':nid,**dict(zip(['Fx_kN','Fy_kN','Fz_kN','Mx_kNm','My_kNm','Mz_kNm'],[float(v)/(1000 if i<3 else 1e6) for i,v in enumerate(ops.nodeReaction(tags[nid]))]))})
   for mid,m in model['members'].items():
    chain,elements=chains[mid];forces=[]
    for e in elements:
     raw=ops.eleResponse(e,'localForce');forces.append([float(v)/(1000 if i%6<3 else 1e6) for i,v in enumerate(raw)])
    members.append({**m,'member_id':mid,'self_weight_kN_m':weights[mid],'segment_end_actions_kN_kNm':forces,'segment_displacements_mm_rad':[list(ops.nodeDisp(n)) for n in chain]})
   balance=sum(r['Fz_kN'] for r in reactions)-total
   if abs(balance)>max(1e-6,total*1e-7):raise InputIssue('支反力合计与框架自重不平衡')
   result={'ok':True,'status':'analysis_completed','draft':True,'upstream_check_summary':'INCOMPLETE','analysis':{'coordinate_system':'Excel XYZ, Z竖向；m/kN输入、mm/N求解','nodes':nodal,'members':members,'reactions':reactions,'sections':model['sections'],'materials':model['materials'],'weight_kN':total,'vertical_balance_error_kN':balance},'notice':'仅完成框架自重三维线弹性静力分析和反力平衡验证。未执行模态、反应谱、其他荷载组合或构件规范验算；analysis_completed不等于converged或规范通过。释放值1表示局部y/z两弯矩释放、保留扭矩。'}
   from explicit_checks import evaluate_checks
   result['input_sha256']=input_hash(tables)
   result['code_checks']=evaluate_checks(tables,result['analysis'])
   result['upstream_check_summary']=result['code_checks']['status']
   result['notice']='框架自重三维线弹性静力分析完成，已附逐构件截面强度、抗剪上界与梁挠度数值验算。稳定、板件等级及完整组合等缺项单独列出；不得将已算项通过解释为完整规范通过。'
   return result
  except Exception as e:return {'ok':False,'status':'analysis_failed','errors':[str(e)],'upstream_check_summary':'INCOMPLETE','draft':True}
  finally:ops.wipe()
