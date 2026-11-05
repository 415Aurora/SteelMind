"""Independent controls of the elastic column-chord P-Delta envelope.

Absolute tolerances remove arithmetic roundoff only: 1e-6 kN/kNm,
1e-3 Nmm torsion, 1 Nmm² bimoment, 1e-7 mm deflection. They are not
applied to design demands or used to turn a structural failure into a pass.
"""
from __future__ import annotations
import numpy as np
from office_responses import DEMAND_KEYS,physical_demands,demand_array,master_vector

TOLERANCES=np.array([1e-6]*7+[1e-3,1e-3,1.,1e-6,1e-7])


def compare_demands(actual,bound,ids=None):
 actual=np.asarray(actual,float);bound=np.asarray(bound,float)
 if actual.shape!=bound.shape or actual.ndim!=2 or actual.shape[1]!=len(DEMAND_KEYS) or not np.isfinite(actual).all() or not np.isfinite(bound).all():raise ValueError('对照矩阵无效')
 allowed=TOLERANCES+1e-7*np.abs(bound);failures=[]
 for i,j in np.argwhere(actual-bound>allowed):failures.append({'member_id':ids[i] if ids else int(i),'component':DEMAND_KEYS[j],'actual':float(actual[i,j]),'bound':float(bound[i,j]),'tolerance':float(allowed[i,j])})
 return {'status':'FAIL' if failures else 'PASS','failures':failures,'absolute_tolerances':dict(zip(DEMAND_KEYS,TOLERANCES.tolist())),'relative_tolerance':1e-7,'max_actual_to_toleranced_bound':float(np.max(actual/(bound+allowed))), 'scope':'numerical enclosure only; does not independently verify normative formula applicability'}


def verify_second_order_controls(bundle,a,progress=None,cancelled=None):
 from office_loads import combine_cases,gravity_floor_resultants
 from office_solver import solve_static
 from office_second_order import notional_force_bound,positive_second_order_bound,column_geometric_maps
 from office_envelopes import first_order_envelope
 ids=a['physical_ids'];columns,kg=column_geometric_maps(bundle,a['mass_source']);ix=[ids.index(pid) for pid in columns];iN=DEMAND_KEYS.index('N_compression_kN');iNa=DEMAND_KEYS.index('N_abs_kN');H=a['influences'][:,ix,iNa].T;F=a['flexibility'];rows=[]
 for wind in (None,'W_XP','W_XN','W_YP','W_YN'):
  combination={'id':'CONTROL-'+str(wind),'factors':{'G':1.3,'Q_OFFICE':1.5,'Q_STAIR':1.5,'Q_ROOF':1.5,**({wind:1.5} if wind else {})}};d,u,_=first_order_envelope(a,combination);floors=gravity_floor_resultants(bundle,a['cases'],{k:v for k,v in combination['factors'].items() if k=='G' or k.startswith('Q_')});notional=notional_force_bound(floors,a['masters']);d+=np.einsum('i,ijk->jk',notional,a['influences']);u+=abs(F)@notional;certificate=positive_second_order_bound(F,kg,d[ix,iN],H,u,coordinate_scales=np.tile([1.,1.,38000.],len(floors)))
  if not certificate['ok']:return {'status':'FAIL','errors':['二阶上界控制未成立'],'controls':rows}
  d+=np.einsum('i,ijk->jk',np.asarray(certificate['extra_floor_force_abs_N_Nmm']),a['influences'])
  for axis in (0,1):
   if cancelled and cancelled():raise RuntimeError('任务已取消')
   case=combine_cases(combination['id'],a['cases'],combination['factors']);coefficient=np.clip(np.sqrt(.2+1/len(floors)),2/3,1.)/250
   for floor in floors:
    name='@F'+str(floor['floor']);master=a['masters'][name]['xyz_m'];x,y=floor['centroid_m'];force=floor['weight_kN']*coefficient;load=case['nodal_loads_kN_kNm'].setdefault(name,[0.]*6);load[axis]+=force;load[5]+=force*((master[1]-y) if axis==0 else (x-master[0]))
   if progress:progress({'stage':'二阶直接对照','case_id':case['case_id'],'axis':axis,'current':len(rows)+1,'total':10})
   result=solve_static(bundle,case,method='PDelta',segments=a['segments_per_member'],mass_source=a['mass_source'])
   if cancelled and cancelled():raise RuntimeError('任务已取消')
   if not result['ok']:return {'status':'FAIL','errors':result['errors'],'controls':rows}
   comparison=compare_demands(demand_array(physical_demands(result),ids),d,ids);ub=np.asarray(certificate['displacement_abs_bound']);ua=abs(master_vector(result));uok=bool(np.all(ua<=ub+np.tile([1e-6,1e-6,1e-10],len(floors))))
   rows.append({'case_id':case['case_id'],'notional_axis':axis,'status':'PASS' if comparison['status']=='PASS' and uok else 'FAIL','response_comparison':comparison,'displacement_enclosed':uok,'coordinate_equilibrium':result['numerical_audit']})
 return {'status':'PASS' if all(row['status']=='PASS' for row in rows) else 'FAIL','controls':rows,'method':'10 direct OpenSees PDelta controls vs component absolute envelope; all live1.5 for extra conservatism','scope':'same adopted rigid-floor column-chord elastic model; not an independent structural solver or connection verification'}
