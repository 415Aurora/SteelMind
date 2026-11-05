"""Traceable checks of explicit self-weight results; incomplete coverage is never PASS."""
from __future__ import annotations
import itertools,math
import numpy as np
from numpy.polynomial import polynomial as poly

SOURCE='GB 50017-2017 表4.4.1、6.1.3、8.1.1及附录B；使用条件与未覆盖项另列'

def design_strength(grade,thickness):
 g=str(grade).upper().replace('B','').replace('C','').replace('D','').replace('E','')
 tables={'Q235':[(16,215,125),(40,205,120),(100,200,115)],'Q355':[(16,305,175),(40,295,170),(63,290,165),(80,280,160),(100,270,155)]}
 if g not in tables:raise ValueError('未实现该牌号设计强度表：'+g)
 for upper,f,fv in tables[g]:
  if 0<thickness<=upper:return {'grade':g,'thickness_mm':thickness,'f_MPa':f,'fv_MPa':fv,'source':'GB50017-2017 表4.4.1，按较厚板件保守取值；Q355牌号修订资料及证据需独立核对','table_review_required':g=='Q355'}
 raise ValueError('厚度超出已实现材料强度表范围')

def roots_in(coeff,length):
 # Solve in normalized u=x/L. Millimetre-scale coefficients can be tiny
 # while their high-degree terms still dominate inside a long member.
 scaled=np.asarray([value*length**i for i,value in enumerate(coeff)],float)
 scale=float(np.max(np.abs(scaled))) if len(scaled) else 0
 if not scale:return []
 scaled=poly.polytrim(scaled/scale,tol=1e-14)
 if len(scaled)<2:return []
 return [float(r.real)*length for r in poly.polyroots(scaled) if abs(r.imag)<1e-7 and 0<float(r.real)<1]

def numeric(item,demand,limit,unit,formula,inputs,source,location='',upper_bound=False):
 status='PASS' if demand<=limit*(1+1e-9) else 'PENDING' if upper_bound else 'FAIL'
 return {'item':item,'status':status,'demand':float(demand),'limit':float(limit),'unit':unit,'utilization':float(demand/limit),'formula':formula,'inputs':inputs,'substitution':f'{demand:.9g} {unit} <= {limit:.9g} {unit}','basis':source,'data_location':location,'upper_bound':upper_bound,'reason':'保守上界超限时须精算，不能据此宣告真实应力超限' if upper_bound and status=='PENDING' else ''}

def pending(item,reason,basis):return {'item':item,'status':'PENDING','reason':reason,'basis':basis,'demand':None,'limit':None,'unit':None,'utilization':None,'formula':None,'inputs':{},'substitution':None,'data_location':None}

def evaluate_checks(tables,analysis):
 controls={str(r.get('parameter_id')):r.get('value') for name,rows in tables.items() if name.lower()=='design_controls' for r in rows}
 def option(key,default):
  v=controls.get(key);return float(v) if v not in (None,'') else default
 gg=option('permanent_load_factor',1.3);g0=option('importance_factor',1.0);den=option('beam_deflection_denominator',400)
 if not all(math.isfinite(v) and v>0 for v in (gg,g0,den)):raise ValueError('作用系数、重要性系数及挠度分母必须为有限正数')
 if gg<1.3 or g0<1:raise ValueError('本自重验算通道不接受低于1.3的永久作用系数或低于1的结构重要性系数')
 members=[]
 node_rows={r['node_id']:r for name,rows in tables.items() if name.lower()=='nodes' for r in rows}
 degree={}
 for member in analysis['members']:
  for key in ('i_node','j_node'):degree[member[key]]=degree.get(member[key],0)+1
 def free_tip(nid):
  return degree[nid]==1 and not any(float(node_rows[nid].get(k) or 0) for k in ('ux','uy','uz','rx','ry','rz'))
 for m in analysis['members']:
  sid=m['section_id'];s=analysis['sections'][sid];mat=analysis['materials'][m['material_id']];h,b,tw,tf=[float(s[k]) for k in ('depth_mm','width_mm','tw_mm','tf_mm')];A,Iy,Iz=s['A'],s['Iy'],s['Iz'];Wy=float(s.get('Zy_mm3') or 2*Iy/b);Wz=float(s.get('Zx_mm3') or 2*Iz/h)
  c=[]
  try:strength=design_strength(mat.get('grade',''),max(tw,tf))
  except ValueError as e:
   members.append({'member_id':m['member_id'],'section_id':sid,'status':'INCOMPLETE','checks':[pending('material_strength',str(e),'GB50017 表4.4.1')]});continue
  f,fv=strength['f_MPa'],strength['fv_MPa'];axes=np.array(m['axes']);q=axes@np.array([0.,0.,-m['self_weight_kN_m']]);nseg=len(m['segment_end_actions_kN_kNm']);L=m['length_m']*1000;ell=L/nseg;E=mat['E_MPa'];D=np.array(m['segment_displacements_mm_rad'])[:,:3]@axes.T
  free_i,free_j=free_tip(m['i_node']),free_tip(m['j_node'])
  cantilever=free_i != free_j
  anchor=-1 if free_i else 0
  # Relative cantilever deflection is measured from the moving root tangent,
  # never the chord through its displaced free end.
  root_slope=(np.cross(np.array(m['segment_displacements_mm_rad'])[anchor,3:6],axes[0])@axes.T) if cantilever else None
  reference_unresolved=(free_i and free_j) or (cantilever and m.get('hinge_j' if free_i else 'hinge_i'))
  max_stress=max_shear_y=max_shear_z=max_t=max_defl=0.;stress_where=defl_where=''
  for k,F in enumerate(m['segment_end_actions_kN_kNm']):
   n=np.array([F[0]*1000,q[0]]);my=np.array([F[4]*1e6,F[2]*1000,q[2]/2]);mz=np.array([-F[5]*1e6,F[1]*1000,q[1]/2])
   candidates=[0.,ell]
   for sn,sy,sz in itertools.product([-1,1],repeat=3):
    expr=poly.polyadd(poly.polyadd(n*sn/A,my*sy/Wy),mz*sz/Wz);candidates+=roots_in(poly.polyder(expr),ell)
   for x in candidates:
    stress=g0*gg*(abs(poly.polyval(x,n))/A+abs(poly.polyval(x,my))/Wy+abs(poly.polyval(x,mz))/Wz)
    if stress>max_stress:max_stress=stress;stress_where=f'/analysis/members/{m["member_id"]}/segment/{k+1}/x_mm={x:.6g}'
   for x in (0.,ell):
    max_shear_y=max(max_shear_y,abs(F[1]*1000+q[1]*x));max_shear_z=max(max_shear_z,abs(F[2]*1000+q[2]*x))
   max_t=max(max_t,abs(F[3]),abs(F[9]))
   # Reconstruct the exact quartic Euler-Bernoulli displacement within each
   # uniformly loaded segment from end translations and end actions. Released
   # nodal rotations need not equal the element's slope, so do not interpolate them.
   rel=[]
   for axis,I,moment,shear,load in [(1,Iz,-F[5]*1e6,F[1]*1000,q[1]),(2,Iy,F[4]*1e6,F[2]*1000,q[2])]:
    a2=moment/(2*E*I);a3=shear/(6*E*I);a4=load/(24*E*I)
    a1=(D[k+1,axis]-D[k,axis]-a2*ell**2-a3*ell**3-a4*ell**4)/ell
    if cantilever:
     chord1=root_slope[axis];chord0=D[anchor,axis]+chord1*(k*ell-(L if anchor==-1 else 0))
    else:chord0=D[0,axis]+(D[-1,axis]-D[0,axis])*k/nseg;chord1=(D[-1,axis]-D[0,axis])/L
    rel.append(np.array([D[k,axis]-chord0,a1-chord1,a2,a3,a4]))
   objective=poly.polyadd(poly.polymul(rel[0],poly.polyder(rel[0])),poly.polymul(rel[1],poly.polyder(rel[1])))
   for x in [0.,ell]+roots_in(objective,ell):
    defl=math.hypot(poly.polyval(x,rel[0]),poly.polyval(x,rel[1]))
    if defl>max_defl:max_defl=defl;defl_where=f'/analysis/members/{m["member_id"]}/segment/{k+1}/x_mm={x:.6g}'
  c.append(numeric('section_strength',max_stress,f,'MPa','σmax=γ0γG max_x(|N(x)|/A+|My(x)|/Wy+|Mz(x)|/Wz), γy=γz=1',{'gamma_G':gg,'gamma_0':g0,'A_mm2':A,'Wy_mm3':Wy,'Wz_mm3':Wz,'material_strength':strength},'GB50017 8.1.1-1；按无孔模型净截面=毛截面，取弹性系数1；有效截面及局部稳定仍另验',stress_where))
  box=str(s['shape']).upper() in ('BOX','SHS','RHS');by=2*tw if box else tw;bz=2*tf
  # S<=A*c provides a provable bound without fabricating first moments for
  # rolled fillets. A failed bound is pending exact section shear calculation.
  tauy=g0*gg*max_shear_y*A*h/(2*Iz*by);tauz=g0*gg*max_shear_z*A*b/(2*Iy*bz)
  for item,tau,V,I,width,extent in [('strong_axis_shear_bound',tauy,max_shear_y,Iz,by,h),('weak_axis_shear_bound',tauz,max_shear_z,Iy,bz,b)]:
   c.append(numeric(item,tau,fv,'MPa','τ≤γ0γG |V| A c /(I b_cut), S≤A c',{'V_N':V,'A_mm2':A,'c_mm':extent/2,'I_mm4':I,'b_cut_mm':width,'gamma_G':gg,'gamma_0':g0},'GB50017 6.1.3；使用毛截面第一面积矩的保守上界',upper_bound=True))
  if max_t<=1e-8:
   equivalent=math.sqrt(max_stress**2+3*(tauy+tauz)**2)
   c.append(numeric('combined_stress_bound',equivalent,1.1*f,'MPa','σeq≤sqrt(σmax²+3(τy_up+τz_up)²) ≤ 1.1f',{'sigma_upper_MPa':max_stress,'tau_y_upper_MPa':tauy,'tau_z_upper_MPa':tauz,'local_bearing_stress':'本均布自重应力场取0；节点局部承压另列未覆盖'},'GB50017 6.1.5的无局部压应力弹性折算应力保守界；节点承压不包含',upper_bound=True))
  else:c.append(pending('combined_stress_bound','存在扭矩，不能将未计扭转的折算应力作为通过判据','GB50017 6.1.5及6.3'))
  if 'beam' in str(m.get('member_type','')) and reference_unresolved:
   c.append(pending('beam_deflection','自由端/释放端的挠度参照条件未明确，不能套用两端连线判据','GB50017 附录B'))
  elif 'beam' in str(m.get('member_type','')):
   c.append(numeric('beam_deflection',max_defl,(2 if cantilever else 1)*L/den,'mm','v=max_x ||u_transverse(x)-u_reference(x)|| ≤ L_effective / denominator',{'L_mm':L,'L_effective_mm':(2 if cantilever else 1)*L,'reference':'root_tangent' if cantilever else 'end_chord','denominator':den,'load_case':'1.0G characteristic','sampling':'连续分段四次多项式，含区间驻点，不仅取节点值'},'GB50017 附录B 表B.1.1；缺省采用楼盖主梁L/400的较严格要求，悬臂有效跨度取2L并相对根部切线计挠度；具体构件用途须复核',defl_where))
  else:c.append(pending('member_deformation_limit','柱构件横向变形不能替代整体层间位移角；需要适用体系/作用及限值','GB50017 附录B'))
  c.extend([
   pending('compression_stability','缺少按实际侧移/支撑确定的计算长度、屈曲曲线及压弯相互作用条件；本显式模块尚未实现完整双向压弯稳定判定','GB50017 第7、8章、附录D'),
   pending('lateral_torsional_stability','需明确侧向支承、有效无支撑长度、弯矩分布和扭转约束；不能用几何长度直接替代','GB50017 6.2及附录C'),
   pending('plate_local_stability','H/箱形板件的应力梯度、板件等级和有效截面需分别判定；未沿用H型筛查公式冒充箱柱验算','GB50017 3.5、7.3、8.4'),
  ])
  if max_t>1e-8:c.append(pending('torsion_interaction',f'存在T={max_t:.6g}kN·m；尚未完成扭转/翘曲与弯剪共同作用判定','GB50017 6.3及第8章'))
  else:c.append({'item':'torsion_interaction','status':'NA','reason':'仅本次自重工况的扭矩在数值容差内为零；不外推其他工况'})
  state='FAIL' if any(v['status']=='FAIL' for v in c) else 'INCOMPLETE' if any(v['status']=='PENDING' for v in c) else 'PASS'
  members.append({'member_id':m['member_id'],'section_id':sid,'status':state,'checks':c})
 counts={s:sum(c['status']==s for m in members for c in m['checks']) for s in ('PASS','FAIL','PENDING','NA')}
 missing=[{'item':'complete_load_combinations','reason':'当前只执行框架自重；楼面活载、风震和完整组合尚未执行'}, {'item':'frame_second_order_stability','reason':'未完成二阶效应/初始缺陷及整体稳定适用性验证'}, {'item':'connections_and_supports','reason':'连接节点、柱脚及基础承载力不在本杆系验证范围'}]
 return {'schema_version':'ExplicitCodeChecks/1.0','scope':'框架自重工况的已实现截面强度、抗剪保守上界及梁挠度验算；不等同完整结构规范通过','status':'FAIL' if counts['FAIL'] else 'INCOMPLETE','summary':counts,'members':members,'project_pending':missing,'assumptions':[f'承载力按 {g0:g}×{gg:g}G，γ0/γG可通过Design_Controls设置；缺省值须按设计条件确认',f'正常使用按1.0G，梁挠度缺省L/{den:g}；按楼盖主梁控制，需核对实际用途','模型未定义孔洞及截面削弱，采用给定毛截面；截面局部稳定及有效截面未验证','Q355强度表的牌号修订及材料质量证明需独立复核，未将Fy直接当作f'],'source':SOURCE}
