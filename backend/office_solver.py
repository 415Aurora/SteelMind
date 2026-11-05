"""Explicit multi-action frame solver; N/mm internally, local axes fixed at input.

PDelta is the GB50017 Chapter5.4 elastic route, NOT a material/imperfection
complete direct-analysis claim. Member stability checks remain mandatory.
"""
from __future__ import annotations
import math
import numpy as np
from office_contracts import geometry_model
from solver_lock import OPENSEES_LOCK
from office_warping import warping_physical_groups,augment_frame,evaluate_chain


def _build(ops,bundle,method,segments,mass_source=None,mass_offset=(0.,0.)):
 if method not in ('Linear','PDelta'):raise ValueError('分析方法仅支持Linear或PDelta')
 if isinstance(segments,bool) or not isinstance(segments,int) or not 2<=segments<=32:raise ValueError('分段数需为2至32整数')
 model=geometry_model(bundle);ops.wipe();ops.model('basic','-ndm',3,'-ndf',6);tags={nid:i for i,nid in enumerate(model['nodes'],1)};xyz={}
 for nid,n in model['nodes'].items():ops.node(tags[nid],*[v*1000 for v in n['xyz']]);ops.fix(tags[nid],*n['fix']);xyz[tags[nid]]=n['xyz']
 chains={};eid=0;nextnode=len(tags);warp_groups=warping_physical_groups(model)
 for tid,(mid,m) in enumerate(model['members'].items(),1):
  chord=bundle.get('analysis_options',{}).get('column_chord',False);count=1 if chord and m['member_type']=='column' else segments
  transformation='Linear' if chord and m['member_type']!='column' else method
  s=model['sections'][m['section_id']];mat=model['materials'][m['material_id']];override=m.get('physical_member_id') in warp_groups;ops.geomTransf(transformation,tid,*m['axes'][2]);a=np.array(model['nodes'][m['i_node']]['xyz']);b=np.array(model['nodes'][m['j_node']]['xyz']);chain=[tags[m['i_node']]]
  for k in range(1,count):
   nextnode+=1;p=(a+(b-a)*k/count).tolist();xyz[nextnode]=p;ops.node(nextnode,*[v*1000 for v in p]);chain.append(nextnode)
   if override:
    axis=int(np.argmax(abs(np.asarray(m['axes'][0]))));flags=[0]*6;flags[3+axis]=1;ops.fix(nextnode,*flags)
  chain.append(tags[m['j_node']]);elements=[]
  for k,(ni,nj) in enumerate(zip(chain,chain[1:])):
   eid+=1;release=(m['hinge_i'] if k==0 else 0)+(2*m['hinge_j'] if k==count-1 else 0)
   ops.element('elasticBeamColumn',eid,ni,nj,s['A'],mat['E_MPa'],mat['G_MPa'],0. if override else s['J'],s['Iy'],s['Iz'],tid,'-releasey',release,'-releasez',release);elements.append(eid)
  chains[mid]=(chain,elements)
 warping=augment_frame(ops,model,tags,chains,eid)
 masters={}
 if bundle.get('diaphragm')=='rigid_in_plane':
  if mass_source is None:raise ValueError('面内刚性楼板需要明确质量/重心信息')
  xs=[n['xyz'][0] for n in model['nodes'].values()];ys=[n['xyz'][1] for n in model['nodes'].values()]
  for floor in mass_source['floors']:
   nextnode+=1;x,y=floor['centroid_m'];x+=mass_offset[0]*(max(xs)-min(xs));y+=mass_offset[1]*(max(ys)-min(ys));z=floor['z_m'];ops.node(nextnode,x*1000,y*1000,z*1000);ops.fix(nextnode,0,0,1,1,1,0)
   # 1 tonne == 1 N*s²/mm; polar inertia converts m² -> mm².
   ops.mass(nextnode,floor['mass_t'],floor['mass_t'],0,0,0,floor['polar_mass_t_m2']*1e6)
   slaves=[tag for tag,p in xyz.items() if abs(p[2]-z)<1e-7];ops.rigidDiaphragm(3,nextnode,*slaves)
   masters['@F'+str(floor['floor'])]={'tag':nextnode,'xyz_m':[x,y,z],'mass_t':floor['mass_t'],'polar_mass_t_mm2':floor['polar_mass_t_m2']*1e6,'floor':floor['floor']}
 return model,tags,chains,masters,xyz,warping


def _apply(ops,model,tags,chains,masters,case):
 ops.timeSeries('Linear',1);ops.pattern('Plain',1,1)
 for mid,q in case.get('member_uniform_kN_m',{}).items():
  if mid not in model['members']:raise ValueError('荷载引用无效构件 '+mid)
  q=np.asarray(q,float)
  if len(q)!=3 or not np.all(np.isfinite(q)):raise ValueError('杆件荷载需为有限三分量')
  local=np.asarray(model['members'][mid]['axes'])@q
  for e in chains[mid][1]:ops.eleLoad('-ele',e,'-type','-beamUniform',float(local[1]),float(local[2]),float(local[0]))
 for nid,f in case.get('nodal_loads_kN_kNm',{}).items():
  tag=masters[nid]['tag'] if nid in masters else tags.get(nid)
  if tag is None:raise ValueError('荷载引用无效节点 '+nid)
  values=np.asarray(f,float)
  if len(values)!=6 or not np.all(np.isfinite(values)):raise ValueError('节点荷载需为有限六分量')
  ops.load(tag,*[v*(1000 if i<3 else 1e6) for i,v in enumerate(values)])


def _setup(ops,method):
 ops.constraints('Transformation');ops.numberer('RCM');ops.system('BandGeneral')
 if method=='Linear':ops.algorithm('Linear');ops.integrator('LoadControl',1.)
 else:ops.test('NormDispIncr',1e-8,50,0);ops.algorithm('Newton');ops.integrator('LoadControl',.1)
 ops.analysis('Static')


def _audit(model,tags,chains,masters,ops,case,method,reactions,column_chord=False):
 external=np.zeros(3);external_m=np.zeros(3)
 for mid,q in case.get('member_uniform_kN_m',{}).items():
  member=model['members'][mid];a=np.asarray(model['nodes'][member['i_node']]['xyz']);b=np.asarray(model['nodes'][member['j_node']]['xyz']);chain=chains[mid][0];force=np.asarray(q)*member['length_m'];external+=force
  # In the second-order route forces act at displaced positions; average the
  # element chords for the moment audit. Record mesh accuracy explicitly.
  for k,(ni,nj) in enumerate(zip(chain,chain[1:])):
   centre=a+(b-a)*(k+.5)/(len(chain)-1)
   if method=='PDelta' and not column_chord:centre+=(np.asarray(ops.nodeDisp(ni)[:3])+np.asarray(ops.nodeDisp(nj)[:3]))/2000
   external_m+=np.cross(centre,force/(len(chain)-1))
 for nid,f in case.get('nodal_loads_kN_kNm',{}).items():
  point=np.asarray(masters[nid]['xyz_m'] if nid in masters else model['nodes'][nid]['xyz']);tag=masters[nid]['tag'] if nid in masters else tags[nid]
  if method=='PDelta' and not column_chord:point=point+np.asarray(ops.nodeDisp(tag)[:3])/1000
  external+=np.asarray(f[:3]);external_m+=np.cross(point,f[:3])+np.asarray(f[3:])
 geometric_couples=[]
 if method=='PDelta' and column_chord:
  for mid,m in model['members'].items():
   if m['member_type']!='column':continue
   elements=chains[mid][1]
   if len(elements)!=1:raise ValueError('柱弦二阶路线必须保留一个物理柱单元')
   ni,nj=tags[m['i_node']],tags[m['j_node']];axial_compression=-float(ops.eleResponse(elements[0],'basicForce')[0])/1000
   delta=(np.asarray(ops.nodeDisp(nj)[:3])-np.asarray(ops.nodeDisp(ni)[:3]))/1000;force=axial_compression*delta/m['length_m'];force[2]=0.;lever=np.asarray(model['nodes'][m['j_node']]['xyz'])-model['nodes'][m['i_node']]['xyz'];couple=np.cross(lever,force);external_m+=couple
   geometric_couples.append({'member_id':mid,'axial_compression_kN':axial_compression,'floor_chord_delta_m':delta.tolist(),'geometric_couple_kNm':couple.tolist()})
 reaction=np.zeros(3);reaction_m=np.zeros(3)
 for row in reactions:
  f=np.asarray([row[k] for k in ('Fx_kN','Fy_kN','Fz_kN')]);mm=np.asarray([row[k] for k in ('Mx_kNm','My_kNm','Mz_kNm')]);reaction+=f;reaction_m+=np.cross(model['nodes'][row['node_id']]['xyz'],f)+mm
 force_res=external+reaction;moment_res=external_m+reaction_m;force_tol=max(1e-5,float(np.linalg.norm(external))*1e-7);moment_tol=max(1e-4,float(np.linalg.norm(external_m))*1e-7)
 if method=='PDelta' and not column_chord:moment_tol=max(moment_tol,float(np.linalg.norm(external))*max(m['length_m'] for m in model['members'].values())*2e-4)
 status='PASS' if np.max(abs(force_res))<=force_tol and np.max(abs(moment_res))<=moment_tol else 'FAIL'
 return {'status':status,'force_residual_kN':force_res.tolist(),'moment_residual_kNm':moment_res.tolist(),'force_tolerance_kN':force_tol,'moment_tolerance_kNm':moment_tol,'column_geometric_couples':geometric_couples,'moment_method':'original loads plus explicit column geometric couples; beam transforms Linear' if method=='PDelta' and column_chord else 'displaced element chord midpoint integral; mesh convergence required' if method=='PDelta' else 'original coordinates exact uniform-load resultants','scope':'整体六分量平衡，不代替构件/节点规范检查'}


def solve_static(bundle,load_case,method='Linear',segments=2,mass_source=None):
 import openseespy.opensees as ops
 with OPENSEES_LOCK:
  try:
   model,tags,chains,masters,xyz,warping=_build(ops,bundle,method,segments,mass_source,load_case.get('mass_offset',(0.,0.)));_apply(ops,model,tags,chains,masters,load_case);_setup(ops,method)
   if ops.analyze(1 if method=='Linear' else 10)!=0:raise ValueError('结构静力不收敛：'+load_case['case_id'])
   ops.reactions();nodes=[];reactions=[];members=[];warp_results={}
   for pid,data in warping.items():
    theta=[float(np.dot(ops.nodeDisp(tags[nid])[3:6],data['axis'])) for nid in data['node_ids']];chain=data['chain'];warp_rate=(chain['warp_map']@np.array(theta))/chain['stations_mm'][-1];stations=chain['stations_mm'];B=[evaluate_chain(chain,theta,float(x))['B_N_mm2'] for x in stations];T=[evaluate_chain(chain,theta,float((a+b)/2))['T_N_mm'] for a,b in zip(stations,stations[1:])];sv=chain['GJ']*warp_rate
    warp_results[pid]={'properties':data['properties'],'node_ids':data['node_ids'],'stations_mm':stations.tolist(),'theta_rad':theta,'bimoment_N_mm2':B,'total_torque_N_mm':T,'saint_venant_torque_at_nodes_N_mm':sv.tolist(),'max_bimoment_N_mm2':max(abs(v) for v in B),'max_saint_venant_torque_N_mm':max(abs(v) for v in sv),'max_warping_shear_torque_N_mm':max(max(abs(sv[i]-t),abs(sv[i+1]-t)) for i,t in enumerate(T)),'boundary':'physical ends free warping B=0; continuity at internal torque joints'}

   for nid,n in model['nodes'].items():
    nodes.append({'node_id':nid,'xyz_m':n['xyz'],'displacement_mm_rad':list(ops.nodeDisp(tags[nid]))})
    if any(n['fix']):reactions.append({'node_id':nid,**dict(zip(('Fx_kN','Fy_kN','Fz_kN','Mx_kNm','My_kNm','Mz_kNm'),[float(v)/(1000 if i<3 else 1e6) for i,v in enumerate(ops.nodeReaction(tags[nid]))]))})
   for mid,m in model['members'].items():
    chain,elements=chains[mid];q=list(load_case.get('member_uniform_kN_m',{}).get(mid,(0.,0.,0.)));forces=[]
    for e in elements:forces.append([float(v)/(1000 if i%6<3 else 1e6) for i,v in enumerate(ops.eleResponse(e,'localForce'))])
    if m.get('physical_member_id') in warping:
     data=warping[m['physical_member_id']];theta=warp_results[m['physical_member_id']]['theta_rad'];start=float(np.dot(np.asarray(model['nodes'][m['i_node']]['xyz'])-data['origin_m'],data['axis']))*1000;ell=m['length_m']*1000/len(elements)
     for k,force in enumerate(forces):
      torque=evaluate_chain(data['chain'],theta,start+(k+.5)*ell)['T_N_mm']/1e6;force[3]=-torque;force[9]=torque

    members.append({**m,'member_id':mid,'self_weight_kN_m':-q[2],'distributed_load_global_kN_m':q,'segment_end_actions_kN_kNm':forces,'segment_displacements_mm_rad':[list(ops.nodeDisp(n)) for n in chain]})
   audit=_audit(model,tags,chains,masters,ops,load_case,method,reactions,bundle.get('analysis_options',{}).get('column_chord',False))
   return {'ok':audit['status']=='PASS','case_id':load_case['case_id'],'method':method,'segments_per_member':segments,'numerical_audit':audit,'errors':[] if audit['status']=='PASS' else ['整体平衡复核未通过'],'analysis':{'coordinate_system':'XYZ Z-up, m/kN in; mm/N solver','nodes':nodes,'members':members,'reactions':reactions,'sections':model['sections'],'materials':model['materials'],'warping_results':warp_results,'master_results':{name:{**v,'displacement_mm_rad':list(ops.nodeDisp(v['tag']))} for name,v in masters.items()},'load_case':load_case}}
  except Exception as e:return {'ok':False,'case_id':load_case.get('case_id'),'errors':[str(e)]}
  finally:ops.wipe()


def solve_modal(bundle,mass_source,segments=2,mass_offset=(0.,0.)):
 import openseespy.opensees as ops
 with OPENSEES_LOCK:
  try:
   model,tags,chains,masters,xyz,warping=_build(ops,bundle,'Linear',segments,mass_source,mass_offset)
   if len(masters)<1:raise ValueError('当前水平模态路径要求面内刚性楼板')
   # All inertial DOFs are the 3 floor-master DOFs. ARPACK on the full
   # massless-member system can break its Arnoldi factorization at rank 12.
   # Statically condense the massless DOFs by 12 unit-load solves, then solve
   # the exact small symmetric floor eigenproblem (not a shear-building fit).
   _setup(ops,'Linear');dofs=[(name,dof) for name in masters for dof in (1,2,6)]
   flexibility=np.zeros((len(dofs),len(dofs)))
   for column,(name,dof) in enumerate(dofs):
    tag=100+column;ops.timeSeries('Linear',tag);ops.pattern('Plain',tag,tag);load=[0.]*6;load[dof-1]=1.;ops.load(masters[name]['tag'],*load)
    if ops.analyze(1)!=0:raise ValueError('静力凝聚单位荷载求解失败')
    for row,(other,dd) in enumerate(dofs):flexibility[row,column]=float(ops.nodeDisp(masters[other]['tag'],dd))
    ops.remove('loadPattern',tag);ops.reset()
   mass_diag=np.array([masters[name]['mass_t'] if dof!=6 else masters[name]['polar_mass_t_mm2'] for name,dof in dofs]);sqrt_m=np.sqrt(mass_diag)
   weighted=sqrt_m[:,None]*flexibility*sqrt_m[None,:]
   asym=float(np.max(abs(weighted-weighted.T)))/max(float(np.max(abs(weighted))),1e-30)
   if asym>1e-6:raise ValueError('静力凝聚柔度不对称')
   inverse_omega2,eigenvectors=np.linalg.eigh((weighted+weighted.T)/2)
   if np.min(inverse_omega2)<=0:raise ValueError('结构凝聚刚度非正定')
   modes=[]
   for index,k in enumerate(np.argsort(inverse_omega2)[::-1],1):
    value=1/float(inverse_omega2[k]);vector=eigenvectors[:,k]/sqrt_m
    shape={name:[float(vector[row*3+j]) for j in range(3)] for row,name in enumerate(masters)}
    modal_mass=float(sum(mass_diag*vector*vector));lx=sum(v['mass_t']*shape[name][0] for name,v in masters.items());ly=sum(v['mass_t']*shape[name][1] for name,v in masters.items())
    modes.append({'mode':index,'omega2_rad2_s2':value,'period_s':2*math.pi/math.sqrt(value),'shape':shape,'modal_mass_t':modal_mass,'participation_x':lx/modal_mass,'participation_y':ly/modal_mass,'effective_mass_x_t':lx*lx/modal_mass,'effective_mass_y_t':ly*ly/modal_mass})
   cx=sum(v['effective_mass_x_t'] for v in modes)/mass_source['total_mass_t'];cy=sum(v['effective_mass_y_t'] for v in modes)/mass_source['total_mass_t'];ok=min(cx,cy)>=.9
   return {'ok':ok,'errors':[] if ok else ['水平质量覆盖不足90%，需扩展模态路径'],'modes':modes,'mass_offset':list(mass_offset),'masters':masters,'coverage_x':cx,'coverage_y':cy,'mass_source':mass_source,'damping_ratio':bundle.get('parameters',{}).get('damping_ratio',.04),'floor_flexibility_mm_N':flexibility.tolist(),'floor_dof_order':[(name,dof) for name,dof in dofs],'static_condensation_symmetry_error':asym,'modal_method':'exact massless-DOF static condensation; 3 rigid-floor DOFs per level','basis':'楼层水平平动/扭转集中质量；90%为采用的模态收敛判据，不标为正文强制条款'}
  except Exception as e:return {'ok':False,'errors':[str(e)]}
  finally:ops.wipe()
