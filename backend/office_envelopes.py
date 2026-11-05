"""Design envelopes, including a verified postfixed P-Delta sufficient bound.

Every envelope dominates the declared independent panel occupancy and action
signs. It is deliberately NOT exported as a simultaneous signed force case.
"""
from __future__ import annotations
import numpy as np
from office_combinations import build_combinations
from office_second_order import column_geometric_maps,notional_force_bound,positive_second_order_bound
from office_loads import gravity_floor_resultants
from office_responses import DEMAND_KEYS


def first_order_envelope(a,combination):
 template=next(iter(a['demand_matrices'].values()));d=np.zeros_like(template);u=np.zeros_like(next(iter(a['master_displacements'].values())));dr=np.zeros_like(next(iter(a['drift_matrices'].values())))
 for key,factor in combination['factors'].items():
  f=abs(factor)
  if key.startswith('Q_'):
   d+=f*a['live_region_bounds'][key];u+=f*a['live_region_u_bounds'][key];dr+=f*a['live_region_drift_bounds'][key]
  else:d+=f*a['demand_matrices'][key];u+=f*abs(a['master_displacements'][key]);dr+=f*a['drift_matrices'][key]
 if combination.get('earthquake_direction'):
  eq=a['earthquake'][combination['earthquake_direction']];f=combination['earthquake_factor'];d+=f*eq['demand_bounds'];u+=f*eq['master_u_amplitudes'];dr+=f*eq['drift_bounds']
 return d,u,dr


def build_design_envelopes(bundle,a):
 ids=a['physical_ids'];columns,kg=column_geometric_maps(bundle,a['mass_source']);indices=[ids.index(pid) for pid in columns];iN=DEMAND_KEYS.index('N_compression_kN');iNa=DEMAND_KEYS.index('N_abs_kN');H=a['influences'][:,indices,iNa].T;F=np.asarray(a['flexibility']);influences=a['influences'];driftH=a['drift_influences'];combinations=build_combinations();n=len(ids);strength=np.zeros((n,len(DEMAND_KEYS)));service=np.zeros_like(strength);control=np.full(strength.shape,'',dtype=object);service_control=control.copy();drift=np.zeros((len(a['floor_ids']),3));drift_control=np.full(drift.shape,'',dtype=object);records=[];all_ok=True
 for row in combinations:
  d,u,dr=first_order_envelope(a,row)
  gravity={k:v for k,v in row['factors'].items() if k=='G' or k.startswith('Q_')};floors=gravity_floor_resultants(bundle,a['cases'],gravity);notional=notional_force_bound(floors,a['masters']);d+=np.einsum('i,ijk->jk',notional,influences);u+=abs(F)@notional;dr+=np.einsum('i,ijk->jk',notional,driftH)
  bound=positive_second_order_bound(F,kg,d[indices,iN],H,u,coordinate_scales=np.tile([1.,1.,38000.],len(floors)))
  if bound['ok']:
   extra=np.asarray(bound['extra_floor_force_abs_N_Nmm']);d+=np.einsum('i,ijk->jk',extra,influences);dr+=np.einsum('i,ijk->jk',extra,driftH)
  else:all_ok=False
  target=service if row['limit_state']=='SLS' else strength;locations=service_control if row['limit_state']=='SLS' else control;mask=d>target;target[mask]=d[mask];locations[mask]=row['id']
  if row['limit_state']=='SLS' and row.get('service_type')=='STANDARD':
   mask=dr>drift;drift[mask]=dr[mask];drift_control[mask]=row['id']
  if row['limit_state']=='SEISMIC':
   # Elastic earthquake drift uses unfactored horizontal earthquake, not1.4.
   # Gravity-induced deformation and P-Delta are retained conservatively.
   elastic_dr=dr/row['earthquake_factor'];mask=elastic_dr>drift;drift[mask]=elastic_dr[mask];drift_control[mask]=row['id']+' /Eh1.4'
  records.append({**row,'notional_force_abs_N_Nmm':notional.tolist(),'second_order':bound,'response_semantics':'分区活载、作用符号、各分量与位置的绝对值充分上界；非同时内力向量'})
 return {'ok':all_ok,'strength':strength,'service':service,'strength_control':control.tolist(),'service_control':service_control.tolist(),'drift_mm':drift.tolist(),'drift_control':drift_control.tolist(),'combinations':records,'method':'linear superposition + regional absolute envelope + signed modal CQC component bounds + postfixed column-chord P-Delta envelope','scope_status':a['scope_status'],'column_ids':columns,'maximum_theta_upper_bound':max((r['second_order'].get('theta_upper_bound',1.) for r in records),default=1.),'second_order_verified':all_ok and a['scope_status']=='FULL_DECLARED_GQWE'}
