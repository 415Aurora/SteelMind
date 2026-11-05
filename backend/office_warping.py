"""Vlasov free-warping torsion; exact constant-property element condensation.

Energy is integral(GJ*theta'^2 + EIw*theta''^2)/2. Each physical H beam
has continuous warping inside, free bimoment at its physical ends. This
supplements the 6-DOF frame's Saint-Venant model when intermediate joints
introduce torque. Lateral-torsional buckling is still a separate code check.
"""
from __future__ import annotations
import math
from functools import lru_cache
import numpy as np


def h_warping_properties(section):
 h,b,tw,tf=[float(section[k]) for k in ('depth_mm','width_mm','tw_mm','tf_mm')]
 Iw=float(section.get('Iw_mm6') or tf*b**3*(h-tf)**2/24)
 return {'Iw_mm6':Iw,'omega_max_mm2':b*(h-tf)/4,'source':'上游Iw优先，否则理想双轴对称H截面Iw=tf*b³*(h-tf)²/24，ωmax=b*(h-tf)/4；不覆盖权威A/I'}


def _basis(u,lam,derivative=0):
 if derivative==0:return np.array([1.,u,math.cosh(lam*u),math.sinh(lam*u)])
 if derivative==1:return np.array([0.,1.,lam*math.sinh(lam*u),lam*math.cosh(lam*u)])
 if derivative==2:return np.array([0.,0.,lam**2*math.cosh(lam*u),lam**2*math.sinh(lam*u)])
 return np.array([0.,0.,lam**3*math.sinh(lam*u),lam**3*math.cosh(lam*u)])


def _kernel(length,total,GJ,EIw):
 lam=math.sqrt(GJ/EIw)*length
 if not 1e-4<lam<30:raise ValueError('翘曲扭转单元参数超出稳定双精度实现范围')
 A=np.array([_basis(0,lam),_basis(0,lam,1)*total/length,_basis(1,lam),_basis(1,lam,1)*total/length]);inverse=np.linalg.inv(A);K=np.zeros((4,4));x,w=np.polynomial.legendre.leggauss(16)
 for xi,wi in zip(x,w):
  u=(xi+1)/2;b1=_basis(u,lam,1)@inverse/length;b2=_basis(u,lam,2)@inverse/length**2;K+=(GJ*np.outer(b1,b1)+EIw*np.outer(b2,b2))*length*wi/2
 return {'length_mm':length,'lambda':lam,'inverse':inverse,'K':(K+K.T)/2}


def torsion_chain(stations_mm,GJ,EIw):
 x=np.asarray(stations_mm,float)
 if len(x)<2 or x[0]!=0 or np.any(np.diff(x)<=0) or GJ<=0 or EIw<=0:raise ValueError('翘曲链参数无效')
 n=len(x);K=np.zeros((2*n,2*n));kernels=[]
 for i,length in enumerate(np.diff(x)):
  e=_kernel(float(length),float(x[-1]),GJ,EIw);indices=[i*2,i*2+1,i*2+2,i*2+3];K[np.ix_(indices,indices)]+=e['K'];kernels.append(e)
 theta_indices=np.arange(0,2*n,2);warp_indices=np.arange(1,2*n,2);Ktt=K[np.ix_(theta_indices,theta_indices)];Ktw=K[np.ix_(theta_indices,warp_indices)];Kww=K[np.ix_(warp_indices,warp_indices)];warp_map=-np.linalg.solve(Kww,Ktw.T);Kt=Ktt+Ktw@warp_map;Kt=(Kt+Kt.T)/2
 # Remove accumulated roundoff in the exact rigid-twist nullspace.
 Kt-=np.diag(Kt.sum(axis=1))
 return {'stations_mm':x,'GJ':GJ,'EIw':EIw,'K_theta':Kt,'warp_map':warp_map,'kernels':kernels,'basis':'Vlasov linear torsion, end B=0, internal warping continuity'}


@lru_cache(maxsize=256)
def _cached_chain(stations,GJ,EIw):
 return torsion_chain(stations,GJ,EIw)


def evaluate_chain(chain,theta,x_mm):
 x=chain['stations_mm'];theta=np.asarray(theta,float);warp=chain['warp_map']@theta;i=min(len(x)-2,max(0,int(np.searchsorted(x,x_mm,side='right')-1)));kernel=chain['kernels'][i];L=kernel['length_mm'];u=(x_mm-x[i])/L;coeff=kernel['inverse']@np.array([theta[i],warp[i],theta[i+1],warp[i+1]])
 derivatives=[float(_basis(u,kernel['lambda'],d)@coeff)/L**d for d in range(4)]
 return {'theta_rad':derivatives[0],'twist_per_mm':derivatives[1],'T_N_mm':chain['GJ']*derivatives[1]-chain['EIw']*derivatives[3],'B_N_mm2':-chain['EIw']*derivatives[2]}


def augment_frame(ops,model,tags,chains,start_element_tag):
 """Replace selected physical primary-beam torsion by condensed Vlasov links.
 Caller sets J=0 only for members listed by warping_physical_groups().
 """
 groups=warping_physical_groups(model);data={};eid=start_element_tag;material_tag=1000000
 for pid,rows in groups.items():
  first=rows[0];s=model['sections'][first['section_id']];mat=model['materials'][first['material_id']];props=h_warping_properties(s);axis=np.array(first['axes'][0]);origin=np.array(model['nodes'][first['i_node']]['xyz']);ordered=sorted({nid for m in rows for nid in (m['i_node'],m['j_node'])},key=lambda nid:float(np.dot(np.array(model['nodes'][nid]['xyz'])-origin,axis)));origin=np.array(model['nodes'][ordered[0]]['xyz']);stations=[float(np.dot(np.array(model['nodes'][nid]['xyz'])-origin,axis))*1000 for nid in ordered];chain=_cached_chain(tuple(stations),mat['G_MPa']*s['J'],mat['E_MPa']*props['Iw_mm6']);K=chain['K_theta']
  for i in range(len(ordered)):
   for j in range(i+1,len(ordered)):
    stiffness=-float(K[i,j])
    if abs(stiffness)<1e-7:continue
    material_tag+=1;eid+=1;ops.uniaxialMaterial('Elastic',material_tag,stiffness);ops.element('twoNodeLink',eid,tags[ordered[i]],tags[ordered[j]],'-mat',material_tag,'-dir',4,'-orient',*axis,*first['axes'][1])
  data[pid]={'chain':chain,'node_ids':ordered,'axis':axis,'origin_m':origin,'properties':props,'members':[m['member_id'] for m in rows]}
 return data


def warping_physical_groups(model):
 groups={}
 for m in model['members'].values():
  if m.get('role')=='GL2' and str(model['sections'][m['section_id']]['shape']).upper() in ('H','I','H-WELDED'):
   groups.setdefault(m['physical_member_id'],[]).append(m)
 return {pid:rows for pid,rows in groups.items() if len(rows)>1}
