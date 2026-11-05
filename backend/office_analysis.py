"""Case/region/modal analysis pipeline; no design PASS is inferred here."""
from __future__ import annotations
import copy,math
import numpy as np
from office_contracts import validate_office_bundle
from office_loads import build_load_cases,build_mass_source,build_live_influence_cases,empty_case
from office_actions import build_wind_cases
from office_solver import solve_static,solve_modal
from office_spectrum import cqc_matrix,build_modal_load_cases,minimum_shear_scale
from office_responses import physical_demands,correlated_demand_bounds,DEMAND_KEYS,master_vector,storey_drifts,demand_array


def analyze_office(bundle,progress=None,segments=2,include_accidental=True,include_live_regions=True,cancelled=None):
 def emit(stage,**values):
  if cancelled and cancelled():raise RuntimeError('任务已取消')
  if progress:progress({'stage':stage,**values})
 validation=validate_office_bundle(bundle)
 if not validation['ok']:return {'ok':False,'status':'needs_input','errors':validation['errors']}
 cases=build_load_cases(bundle);cases.update(build_wind_cases(bundle));mass=build_mass_source(bundle,cases);results={};demands={};U={};drifts={}
 for index,(key,case) in enumerate(cases.items(),1):
  emit('静力工况',current=index,total=len(cases),case_id=key);r=solve_static(bundle,case,segments=segments,mass_source=mass)
  if not r['ok']:return {'ok':False,'status':'analysis_failed','errors':[key+': '+str(r['errors'])]}
  results[key]=r;demands[key]=physical_demands(r);U[key]=master_vector(r);drifts[key]=storey_drifts(r)
 ids=list(demands['G']);masters=results['G']['analysis']['master_results'];floor_ids=sorted(drifts['G']['floors']);matrix={key:demand_array(value,ids) for key,value in demands.items()};drift_matrix={key:np.array([[value['floors'][f][name] for name in ('max_x_mm','max_y_mm','max_vector_mm')] for f in floor_ids]) for key,value in drifts.items()}
 emit('模态分析',case_id='mean_mass');modal=solve_modal(bundle,mass,segments=segments)
 if not modal['ok']:return {'ok':False,'status':'analysis_failed','errors':modal['errors']}
 influences=[];influence_u=[];influence_drifts=[]
 for j,(name,dof) in enumerate(modal['floor_dof_order']):
  emit('二阶影响系数',current=j+1,total=len(modal['floor_dof_order']));case=empty_case('UNIT-'+str(j));force=[0.]*6;force[dof-1]=.001 if dof in (1,2) else 1e-6;case['nodal_loads_kN_kNm'][name]=force;r=solve_static(bundle,case,segments=segments,mass_source=mass)
  if not r['ok']:return {'ok':False,'status':'analysis_failed','errors':r['errors']}
  influences.append(demand_array(physical_demands(r),ids));influence_u.append(master_vector(r));d=storey_drifts(r);influence_drifts.append([[d['floors'][f][k] for k in ('max_x_mm','max_y_mm','max_vector_mm')] for f in floor_ids])
 flexibility=np.array(influence_u).T
 if not np.allclose(flexibility,modal['floor_flexibility_mm_N'],rtol=1e-6,atol=1e-12):raise ValueError('楼层单位影响系数与静力凝聚不一致')
 live_bounds={k:np.zeros_like(matrix[k]) for k in ('Q_OFFICE','Q_STAIR','Q_ROOF')};live_u={k:np.zeros_like(U[k]) for k in live_bounds};live_drift={k:np.zeros_like(drift_matrix[k]) for k in live_bounds};region_count=0
 if include_live_regions:
  regions=build_live_influence_cases(bundle,cases)
  for index,case in enumerate(regions,1):
   emit('活载不利布置包络',current=index,total=len(regions),case_id=case['case_id']);r=solve_static(bundle,case,segments=segments,mass_source=mass)
   if not r['ok']:return {'ok':False,'status':'analysis_failed','errors':r['errors']}
   key=case['parent_case_id'];live_bounds[key]+=demand_array(physical_demands(r),ids);live_u[key]+=abs(master_vector(r));d=storey_drifts(r);live_drift[key]+=np.array([[d['floors'][f][v] for v in ('max_x_mm','max_y_mm','max_vector_mm')] for f in floor_ids]);region_count+=1
 else:
  for key in live_bounds:live_bounds[key]=matrix[key];live_u[key]=abs(U[key]);live_drift[key]=drift_matrix[key]
 earthquake={};modal_groups=[]
 for direction in ('X','Y'):
  offsets=[(0.,0.)]+(([(0.,.05),(0.,-.05)] if direction=='X' else [(.05,0.),(-.05,0.)]) if include_accidental else [])
  group_bounds=[];group_u=[];group_drift=[];details=[]
  for offset in offsets:
   emit('反应谱与偶然偏心',case_id=direction,mass_offset=offset);m=modal if offset==(0.,0.) else solve_modal(bundle,mass,segments=segments,mass_offset=offset)
   if not m['ok']:return {'ok':False,'status':'analysis_failed','errors':m['errors']}
   active=[mode for mode in m['modes'] if mode['effective_mass_x_t' if direction=='X' else 'effective_mass_y_t']/mass['total_mass_t']>1e-12];m={**m,'modes':active};modal_cases=build_modal_load_cases(m,bundle,direction);scale,minimum=minimum_shear_scale(m,modal_cases,direction);per_mode=[];mode_u=[];mode_drifts=[];signed_columns=[]
   for index,case in enumerate(modal_cases,1):
    for load in case['nodal_loads_kN_kNm'].values():
     for i in range(6):load[i]*=scale
    emit('反应谱模态响应',current=index,total=len(modal_cases),case_id=case['case_id'],mass_offset=offset);r=solve_static(bundle,case,segments=segments,mass_source=mass)
    if not r['ok']:return {'ok':False,'status':'analysis_failed','errors':r['errors']}
    per_mode.append(physical_demands(r));mode_u.append(master_vector(r,masters));d=storey_drifts(r);signed_columns.append(d['columns']);mode_drifts.append([[d['floors'][f][v] for v in ('max_x_mm','max_y_mm','max_vector_mm')] for f in floor_ids])
   correlation=cqc_matrix([mode['period_s'] for mode in m['modes']],bundle['parameters']['damping_ratio']);bound=correlated_demand_bounds(per_mode,correlation);values=np.asarray(mode_u);u_amp=np.sqrt(np.maximum(0.,np.einsum('mi,mn,ni->i',values,correlation,values)));dvals=np.asarray(mode_drifts);drift_amp=np.sqrt(np.maximum(0.,np.einsum('mij,mn,nij->ij',dvals,correlation,dvals)))
   col_ids=list(signed_columns[0]);column_spectrum={}
   for pid in col_ids:
    x=np.array([[rows[pid]['dx_mm'],rows[pid]['dy_mm']] for rows in signed_columns]);amp=np.sqrt(np.maximum(0.,np.einsum('mi,mn,ni->i',x,correlation,x)));column_spectrum[pid]={**signed_columns[0][pid],'dx_amplitude_mm':float(amp[0]),'dy_amplitude_mm':float(amp[1])}
   torsion=[]
   for floor in floor_ids:
    col=[v for v in column_spectrum.values() if v['floor']==floor];component='dx_amplitude_mm' if direction=='X' else 'dy_amplitude_mm';coord='y_m' if direction=='X' else 'x_m';low=min(v[coord] for v in col);high=max(v[coord] for v in col);side0=max(v[component] for v in col if v[coord]==low);side1=max(v[component] for v in col if v[coord]==high);average=(side0+side1)/2;torsion.append({'floor':floor,'max_interstory_displacement_mm':max(side0,side1),'two_edge_average_mm':average,'torsion_displacement_ratio':max(side0,side1)/average if average>1e-12 else 1.})
   group_bounds.append(demand_array(bound,ids));group_u.append(u_amp);group_drift.append(drift_amp);details.append({'direction':direction,'mass_offset':offset,'modes':[{'mode':v['mode'],'period_s':v['period_s'],'participation':v['participation_x' if direction=='X' else 'participation_y'],'effective_mass_t':v['effective_mass_x_t' if direction=='X' else 'effective_mass_y_t']} for v in active],'minimum_shear_scale':scale,'minimum_shear_checks':minimum,'torsion':torsion,'column_displacement_amplitudes':column_spectrum,'correlation':correlation.tolist(),'coverage_x':m['coverage_x'],'coverage_y':m['coverage_y']})
  earthquake[direction]={'demand_bounds':np.max(group_bounds,axis=0),'master_u_amplitudes':np.max(group_u,axis=0),'drift_bounds':np.max(group_drift,axis=0),'minimum_shear_scale':max(d['minimum_shear_scale'] for d in details),'details':details,'semantics':'CQC response upper bound; accidental eccentric cases enveloped; NOT a simultaneous signed force field'}
 ex,ey=earthquake['X'],earthquake['Y'];earthquake['XY']={name:np.maximum(np.sqrt(ex[name]**2+.85*ey[name]**2),np.sqrt(ey[name]**2+.85*ex[name]**2)) for name in ('demand_bounds','master_u_amplitudes','drift_bounds')};earthquake['XY']['semantics']='GB/T50011 5.2.3双向效应的分量保守包络，非同时内力向量'
 emit('工况分析完成')
 return {'ok':True,'status':'analysis_completed','scope_status':'FULL_DECLARED_GQWE' if include_accidental and include_live_regions else 'REDUCED_TEST_SCOPE','validation':validation,'cases':cases,'case_results':results,'mass_source':mass,'modal':modal,'physical_ids':ids,'physical_descriptors':demands['G'],'demand_matrices':matrix,'master_displacements':U,'drift_matrices':drift_matrix,'floor_ids':floor_ids,'masters':masters,'influences':np.asarray(influences),'flexibility':flexibility,'drift_influences':np.asarray(influence_drifts),'live_region_bounds':live_bounds,'live_region_u_bounds':live_u,'live_region_drift_bounds':live_drift,'live_regions_analyzed':region_count,'earthquake':earthquake,'segments_per_member':segments,'design_status':'NOT_CHECKED'}
