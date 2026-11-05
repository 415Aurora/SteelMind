"""Positive-envelope P-Delta certificate for rigid-floor frame chord geometry.

u=F(f+Kg(N)u), r=r1+H Kg(N)u. For nonnegative bounds C >= abs(Kg),
abs(u) <= abs(u1)+abs(F) C abs(u). A nonnegative resolvent and a verified
postfixed column-force cap enclose all declared load pattern/sign choices.
This is an elastic P-Delta calculation, not material direct analysis.

Failure of this sufficient bound is NOT proof of physical instability.
"""
import numpy as np


def notional_force_bound(floors,masters):
 """GB50017 5.2.1-2. Both horizontal directions independently enveloped.

 Torque includes eccentric gravity centre relative to the retained master.
 This rectangular absolute bound also covers every horizontal direction.
 """
 factor=np.clip(np.sqrt(.2+1/len(floors)),2/3,1.)/250
 values=[]
 for row in floors:
  master=masters['@F'+str(row['floor'])]['xyz_m'];x,y=row['centroid_m'];force=row['weight_kN']*factor*1000
  values.extend([force,force,force*(abs(x-master[0])+abs(y-master[1]))*1000])
 return np.asarray(values)


def positive_second_order_bound(flexibility,kg_per_column_kN,initial_compression_kN,axial_influence_abs,first_order_u_abs,coordinate_scales=None,max_iterations=40):
 F=np.asarray(flexibility,float);n=len(F);scale=np.ones(n) if coordinate_scales is None else np.asarray(coordinate_scales,float);N0=np.maximum(0.,np.asarray(initial_compression_kN,float));H=np.asarray(axial_influence_abs,float);u0=np.asarray(first_order_u_abs,float)
 if F.shape!=(n,n) or H.shape!=(len(N0),n) or u0.shape!=(n,) or np.any(~np.isfinite(F)) or np.any(N0<0) or np.any(H<0) or np.any(u0<0) or np.any(scale<=0):raise ValueError('二阶包络参数不合法')
 Fs=scale[:,None]*F*scale[None,:];us0=u0*scale;Hs=H*scale[None,:];kg=[np.asarray(g)/scale[:,None]/scale[None,:] for g in kg_per_column_kN]
 if len(kg)!=len(N0):raise ValueError('柱几何矩阵数量不一致')
 cap=N0*1.0001+1e-12
 try:chol=np.linalg.cholesky((Fs+Fs.T)/2)
 except np.linalg.LinAlgError:return {'ok':False,'status':'BOUND_NOT_SATISFIED','reason':'弹性楼层柔度非正定'}
 for iteration in range(max_iterations):
  C=sum((value*np.abs(g) for value,g in zip(cap,kg)),np.zeros_like(Fs));G=sum((value*g for value,g in zip(cap,kg)),np.zeros_like(Fs));B=np.abs(Fs)@C;rho=float(max(abs(np.linalg.eigvals(B)),default=0.));theta=float(max(np.linalg.eigvalsh(chol.T@G@chol),default=0.))
  if rho>=1-1e-10:return {'ok':False,'status':'BOUND_NOT_SATISFIED','reason':'保守正包络不收敛，需增加刚度或更精细分析；不能据此宣告物理失稳','positive_operator_radius':rho,'theta_upper_bound':theta}
  us=np.linalg.solve(np.eye(n)-B,us0);extra=C@us;proposed=N0+Hs@extra
  if np.all(proposed<=cap*(1+1e-10)+1e-12):
   return {'ok':theta<=.25,'status':'PASS' if theta<=.25 else 'BOUND_NOT_SATISFIED','reason':'' if theta<=.25 else '保守二阶效应上界超过0.25，按设计控制增大刚度','displacement_abs_bound':(us/scale).tolist(),'extra_floor_force_abs_N_Nmm':(extra*scale).tolist(),'column_compression_cap_kN':cap.tolist(),'positive_operator_radius':rho,'theta_upper_bound':theta,'iterations':iteration+1,'postfixed_cap_verified':True,'method':'rigid-floor elastic P-Delta positive-resolvent envelope; Chapter8 P-delta member stability remains'}
  cap=np.maximum(cap,proposed*1.001+1e-10)
 return {'ok':False,'status':'BOUND_NOT_SATISFIED','reason':'未形成可验证的轴力上界，不允许通过'}


def column_geometric_maps(bundle,mass_source):
 from office_contracts import geometry_model
 model=geometry_model(bundle);floors=mass_source['floors'];n=len(floors)*3;maps=[];ids=[];by_z={round(f['z_m'],8):f for f in floors}
 for m in model['members'].values():
  if m['member_type']!='column':continue
  a=model['nodes'][m['i_node']]['xyz'];b=model['nodes'][m['j_node']]['xyz'];ax=np.zeros(n);ay=np.zeros(n)
  for point,sign in ((a,-1.),(b,1.)):
   if point[2]<=0:continue
   f=by_z[round(point[2],8)];i=(f['floor']-1)*3;x,y=f['centroid_m'];ax[i]+=sign;ax[i+2]-=sign*(point[1]-y)*1000;ay[i+1]+=sign;ay[i+2]+=sign*(point[0]-x)*1000
  maps.append(1000/(m['length_m']*1000)*(np.outer(ax,ax)+np.outer(ay,ay)));ids.append(m['physical_member_id'])
 return ids,maps
