"""Versioned office scheme modifications; reference authority is immutable."""
from __future__ import annotations
import copy
from office_contracts import geometry_model

SCHEMES=[None,{'GL2':(600,250,16,20),'GL3':(550,200,15,15),'GZ1':(400,400,12,12)}, {'GL2':(650,300,18,25),'GL3':(550,250,15,20),'GZ1':(450,450,14,14)}, {'GL2':(700,350,20,28),'GL3':(600,300,16,22),'GZ1':(500,500,16,16)}, {'GL2':(750,400,22,30),'GL3':(650,350,18,25),'GZ1':(550,550,20,20)}]


def apply_section_scheme(bundle,index):
 if isinstance(index,bool) or not isinstance(index,int) or index<0 or index>=len(SCHEMES):raise ValueError('截面方案编号无效')
 b=copy.deepcopy(bundle);b['analysis_options']={'column_chord':True,'global_method':'rigid-floor P-Delta; member P-delta Chapter8 retained'};b['scheme_index']=index
 if index:
  mapping={}
  for role,(h,w,tw,tf) in SCHEMES[index].items():
   sid=f'OFFICE-S{index}-{role}';box=role=='GZ1';A=h*w-(h-2*tf)*(w-2*tw) if box else 2*w*tf+(h-2*tf)*tw
   Iz=(w*h**3-(w-2*tw)*(h-2*tf)**3)/12 if box else (w*h**3-(w-tw)*(h-2*tf)**3)/12
   Iy=(h*w**3-(h-2*tf)*(w-2*tw)**3)/12 if box else (2*tf*w**3+(h-2*tf)*tw**3)/12
   row={'section_id':sid,'section_name':('BOX' if box else 'H')+f'{h}x{w}x{tw}x{tf}','shape':'BOX' if box else 'H-WELDED','depth_mm':h,'width_mm':w,'tw_mm':tw,'tf_mm':tf,'area_mm2':A,'Ix_mm4':Iz,'Iy_mm4':Iy,'product_type':'welded_plate_box' if box else 'welded_H','property_provenance':'new_design_ideal_plate_geometry; no fillet; reference section authority preserved','scheme_index':index}
   existing=next((r for r in b['tables']['Sections'] if r['section_id']==sid),None)
   if existing is not None and existing!=row:raise ValueError('新方案编号与已有权威截面冲突：'+sid)
   if existing is None:b['tables']['Sections'].append(row)
   mapping[role]=sid
  for m in b['tables']['Members']+b['physical_members']:m['section_id']=mapping[m['role']]
 model=geometry_model(b);stiffeners=[]
 for m in b['physical_members']:
  if m['member_type']!='beam':continue
  s=model['sections'][m['section_id']];pid=m['physical_member_id'];rows=[v for v in model['members'].values() if v['physical_member_id']==pid];nids=sorted({v[k] for v in rows for k in ('i_node','j_node')})
  stiffeners.append({'id':'ST-'+pid,'physical_member_id':pid,'width_mm':(s['width_mm']-s['tw_mm'])/2,'thickness_mm':20.,'height_mm':s['depth_mm']-2*s['tf_mm'],'node_ids':nids,'placement':'每个物理端及次梁/集中传力交点，双面成对，刨平顶紧；焊缝和节点设计交接'})
 b['stiffeners']=stiffeners
 return b


def json_ready(value):
 import math
 import numpy as np
 if isinstance(value,np.ndarray):return json_ready(value.tolist())
 if isinstance(value,np.generic):return json_ready(value.item())
 if isinstance(value,dict):return {str(k):json_ready(v) for k,v in value.items()}
 if isinstance(value,(list,tuple)):return [json_ready(v) for v in value]
 if isinstance(value,float) and not math.isfinite(value):raise ValueError('成果中存在非有限数值')
 return value


def run_office_design(request,progress=None,cancelled=None,run_id=None):
 import hashlib,time
 from uuid import uuid4
 from pathlib import Path
 from office_contracts import reference_case,validate_office_bundle,bundle_hash
 from office_analysis import analyze_office
 from office_envelopes import build_design_envelopes
 from office_checks import check_office_design
 from office_validation import verify_second_order_controls
 started=time.monotonic();original=copy.deepcopy(request.get('bundle') or reference_case());validation=validate_office_bundle(original);options=request.get('options') or {};indices=options.get('scheme_indices',[0,4])
 if not validation['ok']:return {'ok':False,'status':'needs_input','errors':validation['errors'],'design_status':'INCOMPLETE'}
 if not isinstance(indices,list) or not indices or len(indices)>5 or any(isinstance(i,bool) or not isinstance(i,int) or i<0 or i>=len(SCHEMES) for i in indices):return {'ok':False,'status':'needs_input','errors':['scheme_indices需为0至4的非空整数列表，最多5项'],'design_status':'INCOMPLETE'}
 if not validation['design_inputs_confirmed']:return {'ok':False,'status':'needs_input','errors':['课程设计关键假定尚未确认'],'design_status':'INCOMPLETE'}
 segments=options.get('segments_per_member',2)
 if isinstance(segments,bool) or not isinstance(segments,int) or not 2<=segments<=32:return {'ok':False,'status':'needs_input','errors':['segments_per_member需为2至32整数'],'design_status':'INCOMPLETE'}
 history=[];run_id=run_id or uuid4().hex;last=None
 for number,index in enumerate(indices,1):
  if cancelled and cancelled():return {'ok':False,'status':'cancelled','run_id':run_id,'design_status':'INCOMPLETE'}
  b=apply_section_scheme(original,index)
  def emit(p):
   if cancelled and cancelled():raise RuntimeError('任务已取消')
   if progress:progress({'run_id':run_id,'scheme':index,'iteration':number,**p})
  emit({'stage':'方案开始','total_candidates':len(indices)})
  a=analyze_office(b,progress=emit,segments=segments,cancelled=cancelled)
  if not a['ok']:return {'ok':False,'status':a['status'],'run_id':run_id,'errors':a.get('errors',[]),'iterations':history,'design_status':'INCOMPLETE'}
  emit({'stage':'荷载组合与二阶包络'});e=build_design_envelopes(b,a);checks=check_office_design(b,a,e)
  history.append({'scheme':index,'input_sha256':bundle_hash(b),'design_status':checks['design_status'],'summary':checks['summary'],'max_utilization':max(m['max_utilization'] for m in checks['members']),'controlling_members':sorted([{'member_id':m['member_id'],'section_id':m['section_id'],'status':m['status'],'utilization':m['max_utilization']} for m in checks['members']],key=lambda m:m['utilization'],reverse=True)[:8],'sections':[s for s in b['tables']['Sections'] if s['section_id'] in {m['section_id'] for m in b['tables']['Members']}],'reason':'固定参考方案及保守改型候选；不声称经济最优'})
  last=(b,a,e,checks)
  if checks['design_status']=='PASS':break
 b,a,e,checks=last;emit({'stage':'二阶数值验证'});verification=verify_second_order_controls(b,a,progress=emit,cancelled=cancelled)
 if cancelled and cancelled():return {'ok':False,'status':'cancelled','run_id':run_id,'design_status':'INCOMPLETE'}
 if verification['status']!='PASS':checks['design_status']='INCOMPLETE';checks['coverage_status']='INCOMPLETE'
 engine=hashlib.sha256(b''.join(p.read_bytes() for p in sorted(Path(__file__).parent.glob('office_*.py')))).hexdigest()
 return json_ready({'ok':True,'run_id':run_id,'status':'converged' if checks['design_status']=='PASS' else 'design_failed' if checks['design_status']=='FAIL' else 'incomplete','analysis_status':'analysis_completed','design_status':checks['design_status'],'coverage_status':checks['coverage_status'],'building_status':'EXTERNAL_VERIFICATION_PENDING','input_sha256':bundle_hash(b),'original_input_sha256':bundle_hash(original),'engine_sha256':engine,'bundle':b,'original_bundle':original,'analysis':a,'envelopes':e,'code_checks':checks,'verification':verification,'iterations':history,'elapsed_seconds':time.monotonic()-started,'scope':checks['scope'],'warnings':['完整建筑状态仍需节点、楼板、柱脚和基础等交接复核','本次为参考平面基础上的新课程设计；不冒充原3D3S逐杆恢复或经济最优方案']})
