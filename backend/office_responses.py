"""Physical-member response operators; mesh nodes never reset beam span limits."""
from __future__ import annotations
import math,copy
from collections import defaultdict
import numpy as np
from numpy.polynomial import polynomial as poly
from explicit_checks import roots_in

DEMAND_KEYS=('N_abs_kN','N_compression_kN','My_kNm','Mz_kNm','Vy_kN','Vz_kN','T_kNm','Tsv_Nmm','Twarp_Nmm','B_Nmm2','ltb_moment_bound_kNm','deflection_mm')


def combine_results(results,factors,case_id):
 selected=[(results[k],factor) for k,factor in factors.items() if factor];base=selected[0][0];a=base['analysis'];members=[];nodes=[];warping={}
 for index,m in enumerate(a['members']):
  f=sum(factor*np.asarray(r['analysis']['members'][index]['segment_end_actions_kN_kNm']) for r,factor in selected);u=sum(factor*np.asarray(r['analysis']['members'][index]['segment_displacements_mm_rad']) for r,factor in selected);q=sum(factor*np.asarray(r['analysis']['members'][index]['distributed_load_global_kN_m']) for r,factor in selected)
  members.append({**m,'segment_end_actions_kN_kNm':f.tolist(),'segment_displacements_mm_rad':u.tolist(),'distributed_load_global_kN_m':q.tolist(),'self_weight_kN_m':-float(q[2])})
 for index,n in enumerate(a['nodes']):nodes.append({**n,'displacement_mm_rad':sum(factor*np.asarray(r['analysis']['nodes'][index]['displacement_mm_rad']) for r,factor in selected).tolist()})
 for pid,v in a.get('warping_results',{}).items():
  out={**v}
  for key in ('theta_rad','bimoment_N_mm2','total_torque_N_mm','saint_venant_torque_at_nodes_N_mm'):out[key]=sum(factor*np.asarray(r['analysis']['warping_results'][pid][key]) for r,factor in selected).tolist()
  out['max_bimoment_N_mm2']=max(abs(x) for x in out['bimoment_N_mm2']);out['max_saint_venant_torque_N_mm']=max(abs(x) for x in out['saint_venant_torque_at_nodes_N_mm']);out['max_warping_shear_torque_N_mm']=max(max(abs(out['saint_venant_torque_at_nodes_N_mm'][i]-t),abs(out['saint_venant_torque_at_nodes_N_mm'][i+1]-t)) for i,t in enumerate(out['total_torque_N_mm']));warping[pid]=out
 masters={name:{**v,'displacement_mm_rad':sum(factor*np.asarray(r['analysis']['master_results'][name]['displacement_mm_rad']) for r,factor in selected).tolist()} for name,v in a.get('master_results',{}).items()}
 return {'ok':True,'case_id':case_id,'method':'Linear superposition','analysis':{**a,'members':members,'nodes':nodes,'warping_results':warping,'master_results':masters},'factors':factors}


def _peak(coeff,length,absolute=True):
 values=[float(poly.polyval(x,coeff)) for x in [0.,length]+roots_in(poly.polyder(coeff),length)]
 return max(abs(v) for v in values) if absolute else max(values)


def physical_demands(result):
 a=result['analysis'];nodes={n['node_id']:n for n in a['nodes']};groups=defaultdict(list)
 for member in a['members']:groups[member['physical_member_id']].append(member)
 demands={}
 for pid,rows in groups.items():
  axes=np.asarray(rows[0]['axes']);rows=sorted(rows,key=lambda m:float(np.dot(nodes[m['i_node']]['xyz_m'],axes[0])));first,last=rows[0],rows[-1];start=np.asarray(nodes[first['i_node']]['xyz_m']);L=sum(m['length_m'] for m in rows)*1000;section=a['sections'][first['section_id']];material=a['materials'][first['material_id']];E=material['E_MPa'];d={key:0. for key in DEMAND_KEYS};d.update(physical_member_id=pid,member_type=first['member_type'],role=first.get('role'),section_id=first['section_id'],material_id=first['material_id'],length_m=L/1000,unbraced_length_m=first['unbraced_length_m'],source_members=[m['member_id'] for m in rows]);end0=np.asarray(first['segment_displacements_mm_rad'][0][:3])@axes.T;end1=np.asarray(last['segment_displacements_mm_rad'][-1][:3])@axes.T
  shear_jumps=[];moment_jumps=[];distributed=[];last_force=None
  for member in rows:
   q=axes@np.asarray(member['distributed_load_global_kN_m']);forces=member['segment_end_actions_kN_kNm'];ell=member['length_m']/len(forces);u=np.asarray(member['segment_displacements_mm_rad'])[:,:3]@axes.T;member_start=float(np.dot(np.asarray(nodes[member['i_node']]['xyz_m'])-start,axes[0]))*1000
   for k,f in enumerate(forces):
    n=[f[0],q[0]];my=[f[4],f[2],q[2]/2];mz=[-f[5],f[1],q[1]/2];vy=[f[1],q[1]];vz=[f[2],q[2]]
    d['N_abs_kN']=max(d['N_abs_kN'],_peak(n,ell));d['N_compression_kN']=max(d['N_compression_kN'],_peak(n,ell,False))
    for key,coeff in (('My_kNm',my),('Mz_kNm',mz),('Vy_kN',vy),('Vz_kN',vz)):d[key]=max(d[key],_peak(coeff,ell))
    d['T_kNm']=max(d['T_kNm'],abs(f[3]),abs(f[9]));s0=member_start+k*ell*1000
    if last_force is not None:
     shear_jumps.append((s0/1000,abs(f[1]+last_force[7])));moment_jumps.append(abs(-f[5]-last_force[11]))
    last_force=f;distributed.append((q[1],ell));mm=ell*1000;relative=[]
    if first['member_type']=='beam':
     for axis,I,moment,shear,load in ((1,section['Iz'],-f[5]*1e6,f[1]*1000,q[1]),(2,section['Iy'],f[4]*1e6,f[2]*1000,q[2])):
      a2=moment/(2*E*I);a3=shear/(6*E*I);a4=load/(24*E*I);a1=(u[k+1,axis]-u[k,axis]-a2*mm**2-a3*mm**3-a4*mm**4)/mm;chord0=end0[axis]+(end1[axis]-end0[axis])*s0/L;chord1=(end1[axis]-end0[axis])/L;relative.append(np.array([u[k,axis]-chord0,a1-chord1,a2,a3,a4]))
     objective=poly.polyadd(poly.polymul(relative[0],poly.polyder(relative[0])),poly.polymul(relative[1],poly.polyder(relative[1])))
     for station in [0.,mm]+roots_in(objective,mm):d['deflection_mm']=max(d['deflection_mm'],math.hypot(poly.polyval(station,relative[0]),poly.polyval(station,relative[1])))
  if first['member_type']=='beam':
   lm=L/1000;end_m=max(abs(first['segment_end_actions_kN_kNm'][0][5]),abs(last['segment_end_actions_kN_kNm'][-1][11]));qref=distributed[0][0];transverse=abs(qref)*lm**2/8+sum(abs(q-qref)*ell for q,ell in distributed)*lm/4+sum(P*x*(lm-x)/lm for x,P in shear_jumps)+sum(moment_jumps);d['ltb_moment_bound_kNm']=end_m+transverse;d['ltb_decomposition']={'end_moment_bound_kNm':end_m,'simply_supported_load_bound_kNm':transverse,'method':'端矩线性分量、均布荷载、剪力跳跃的集中力及弯矩跳跃的集中偶分别取绝对上界，支点/网格不缩短物理跨度'}
  if pid in a.get('warping_results',{}):
   warp=a['warping_results'][pid];d['B_Nmm2']=warp['max_bimoment_N_mm2'];d['Tsv_Nmm']=warp['max_saint_venant_torque_N_mm'];d['Twarp_Nmm']=warp['max_warping_shear_torque_N_mm']
  else:d['Tsv_Nmm']=d['T_kNm']*1e6
  demands[pid]=d
 return demands


def correlated_demand_bounds(per_mode,correlation):
 from office_spectrum import cqc
 first=per_mode[0];out={}
 for pid,base in first.items():
  d={**base}
  for key in DEMAND_KEYS:d[key]=cqc([m[pid][key] for m in per_mode],correlation)
  d['response_semantics']='逐模态绝对控制值的CQC保守上界；各分量/控制位置不同时发生，不是同时内力向量'
  out[pid]=d
 return out


def master_vector(result,target_masters=None):
 out=[]
 for name,v in result['analysis']['master_results'].items():
  u=v['displacement_mm_rad'];target=(target_masters or result['analysis']['master_results'])[name]['xyz_m'];dx=(target[0]-v['xyz_m'][0])*1000;dy=(target[1]-v['xyz_m'][1])*1000
  out.extend([float(u[0]-u[5]*dy),float(u[1]+u[5]*dx),float(u[5])])
 return np.array(out)


def storey_drifts(result):
 a=result['analysis'];nodes={n['node_id']:n for n in a['nodes']};columns={};floors={};levels=sorted({n['xyz_m'][2] for n in a['nodes'] if n['xyz_m'][2]>0})
 for member in a['members']:
  if member['member_type']!='column':continue
  top=nodes[member['j_node']];bottom=nodes[member['i_node']];u=np.asarray(top['displacement_mm_rad'])-np.asarray(bottom['displacement_mm_rad']);floor=levels.index(top['xyz_m'][2])+1;pid=member['physical_member_id'];columns[pid]={'floor':floor,'x_m':top['xyz_m'][0],'y_m':top['xyz_m'][1],'dx_mm':float(u[0]),'dy_mm':float(u[1]),'height_mm':(top['xyz_m'][2]-bottom['xyz_m'][2])*1000};f=floors.setdefault(floor,{'max_x_mm':0.,'max_y_mm':0.,'max_vector_mm':0.})
  f['max_x_mm']=max(f['max_x_mm'],abs(float(u[0])));f['max_y_mm']=max(f['max_y_mm'],abs(float(u[1])));f['max_vector_mm']=max(f['max_vector_mm'],float(np.linalg.norm(u[:2])))
 return {'columns':columns,'floors':floors}


def demand_array(demands,ids):
 return np.array([[demands[pid][key] for key in DEMAND_KEYS] for pid in ids],float)
