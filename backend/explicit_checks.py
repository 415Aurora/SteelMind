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

def not_applicable(item, reason, basis, inputs=None):
 return {**pending(item, reason, basis), 'status':'NA', 'inputs':inputs or {}}

def local_plate_checks(section, grade, max_compression, max_my, max_mz, max_t, *, is_beam=False):
 """Conservative S4 geometry gates, not a replacement for effective-section design.

 No stress relaxation, slab restraint, or stiffeners are invented. Authority
 section properties remain untouched. A geometry gate exceeding its bound
 produces PENDING, since effective-section verification may still succeed.
 """
 shape=str(section['shape']).upper()
 h,b,tw,tf=[float(section[k]) for k in ('depth_mm','width_mm','tw_mm','tf_mm')]
 try: fy=float(str(grade).upper().split('Q')[1][:3])
 except (ValueError, IndexError): return [pending('plate_local_stability','未支持的钢号修正系数','GB50017 表3.5.1')]
 eps=math.sqrt(235/fy)
 if shape in ('BOX','SHS','RHS'):
  ratio=max((h-2*tf)/tw,(b-2*tw)/tf);limit=(42 if is_beam else 45)*eps
  gate=numeric('plate_local_stability',ratio,limit,'1','max((h-2tf)/tw,(b-2tw)/tf) ≤ C sqrt(235/fy)',{'C':42 if is_beam else 45,'epsilon_k':eps,'grade_number_MPa':fy,'gross_properties_preserved':True},'GB50017 表3.5.1；按四壁均匀受压作保守S4筛查；双轴压弯及有效截面另核',upper_bound=True)
  if gate['status']=='PENDING': gate['reason']='毛截面保守S4门槛未满足；需按实际应力梯度/板件分类及8.4.2有效截面 effective section 精算，不代表构件承载力已失败。不得用抗震应力修正条件直接放宽本自重案例。'
  return [gate]
 if shape not in ('H','I','H-WELDED','I-WELDED','HN','HW','HM'):return [pending('plate_local_stability','该截面类型尚未实现板件适用性判断','GB50017 3.5、8.4')]
 flange=numeric('flange_width_thickness',(b-tw)/(2*tf),15*eps,'1','(b-tw)/(2tf) ≤ 15 sqrt(235/fy)',{'epsilon_k':eps,'grade_number_MPa':fy,'fillet_deduction_mm':0},'GB50017 表3.5.1 H/I翼缘S4；忽略圆角对外伸宽度的有利扣减',upper_bound=True)
 # Uniform compression is a conservative lower S4 limit for a web with any
 # compressive axial action. Pure major-axis bending may use the beam limit.
 pure_major=(max_compression<=1e-8 and max_my<=1e-8 and max_t<=1e-8)
 web=numeric('web_width_thickness',(h-2*tf)/tw,(124 if pure_major else 45)*eps,'1','(h-2tf)/tw ≤ C sqrt(235/fy)',{'C':124 if pure_major else 45,'epsilon_k':eps,'max_compression_kN':max_compression,'max_minor_moment_kNm':max_my,'gross_properties_preserved':True},'GB50017 表3.5.1；仅无轴压且无弱轴弯扭时采用纯受弯腹板124ε，其余按均匀受压45ε保守筛查',upper_bound=True)
 if pure_major and (h-2*tf)/tw<=80*eps:
  extra=not_applicable('web_additional_stability','本均布自重无局部横向压应力场，腹板高厚比不超过80ε，无需另作6.3.3至6.3.5区格稳定验算；支座/节点承压仍属项目缺项','GB50017 6.3.1、6.3.2',{'h0_over_tw':(h-2*tf)/tw,'threshold':80*eps})
 else:
  extra=pending('web_additional_stability','腹板超过80ε或存在轴压/弱轴弯扭；需明确实际区格、加劲肋及边界并按6.3/8.4验算；S4筛查通过不等于此项通过','GB50017 6.3.1至6.3.5及8.4')
 group=pending('plate_local_stability','板件分项仍有待补充；见翼缘、腹板S4门槛和腹板区格稳定分项','GB50017 3.5、6.3、8.4')
 if all(c['status'] in ('PASS','NA') for c in (flange,web,extra)):
  group={'item':'plate_local_stability','status':'PASS','reason':'本次受力适用条件下翼缘、腹板S4门槛满足，且无需另作腹板区格稳定；不涵盖连接局部承压或其他作用','basis':'GB50017 表3.5.1、6.3.1、6.3.2'}
 return [flange,web,extra,group]

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
  max_compression=max_my=max_mz=0.;max_stress=max_shear_y=max_shear_z=max_t=max_defl=0.;stress_where=defl_where=''
  for k,F in enumerate(m['segment_end_actions_kN_kNm']):
   n=np.array([F[0]*1000,q[0]]);my=np.array([F[4]*1e6,F[2]*1000,q[2]/2]);mz=np.array([-F[5]*1e6,F[1]*1000,q[1]/2])
   for coeff,kind,divisor in ((n,'n',1000),(my,'my',1e6),(mz,'mz',1e6)):
    values=[float(poly.polyval(x,coeff))/divisor for x in [0.,ell]+roots_in(poly.polyder(coeff),ell)]
    if kind=='n':max_compression=max(max_compression,max(values))
    elif kind=='my':max_my=max(max_my,max(abs(v) for v in values))
    else:max_mz=max(max_mz,max(abs(v) for v in values))
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
  else:c.append(not_applicable('member_deformation_limit','柱不套用梁相对挠度限值；节点位移已计算，整体层间位移控制另列项目级缺项','GB50017 附录B'))
  if max_compression<=1e-8:
   c.append(not_applicable('compression_stability','本工况连续杆段轴力无受压区，不作受压/压弯稳定；不外推其他荷载组合','GB50017 第7、8章',{'max_compression_kN':max_compression,'tolerance_kN':1e-8,'sign':'局部截面N正为受压'}))
  else:c.append(pending('compression_stability',f'本工况最大受压轴力{max_compression:.6g} kN；需双向计算长度、侧移条件、屈曲曲线及压弯相互作用；未用层高代替计算长度','GB50017 第7、8章、附录D'))
  if box and 'column' in str(m.get('member_type','')):
   c.append(not_applicable('lateral_torsional_stability','闭口箱形截面不重复套用H梁侧扭稳定；受压箱柱仍须完成双轴压弯稳定，未据此免除柱稳定','GB50017 8.2.5闭口截面稳定计算分工'))
  elif max_compression<=1e-8 and max_my<=1e-8 and max_mz<=1e-8:
   c.append(not_applicable('lateral_torsional_stability','本工况无受压及弯矩，不作梁侧扭稳定','GB50017 6.2',{'moment_tolerance_kNm':1e-8}))
  else:c.append(pending('lateral_torsional_stability','未采用组合楼板约束；需实际受压翼缘侧向支承、无支撑长度及端部抗扭条件，不能仅凭杆端弯矩释放判为免验','GB50017 6.2及附录C'))
  c.extend(local_plate_checks(s,mat.get('grade',''),max_compression,max_my,max_mz,max_t,is_beam='beam' in str(m.get('member_type',''))))
  if max_t>1e-8:c.append(pending('torsion_interaction',f'存在T={max_t:.6g}kN·m；尚未完成扭转/翘曲与弯剪共同作用判定','GB50017 6.3及第8章'))
  else:c.append({'item':'torsion_interaction','status':'NA','reason':'仅本次自重工况的扭矩在数值容差内为零；不外推其他工况'})
  state='FAIL' if any(v['status']=='FAIL' for v in c) else 'INCOMPLETE' if any(v['status']=='PENDING' for v in c) else 'PASS'
  members.append({'member_id':m['member_id'],'section_id':sid,'status':state,'completed_check_status':'FAIL' if any(v['status']=='FAIL' for v in c) else 'PASS' if any(v['status']=='PASS' for v in c) else 'NOT_CHECKED','coverage':{k:sum(v['status']==k for v in c) for k in ('PASS','FAIL','PENDING','NA')},'checks':c})
 counts={s:sum(c['status']==s for m in members for c in m['checks']) for s in ('PASS','FAIL','PENDING','NA')}
 missing=[{'item':'complete_load_combinations','reason':'当前只执行框架自重；楼面活载、风震和完整组合尚未执行'}, {'item':'frame_deformation_limits','reason':'整体层间位移控制需明确适用作用及限值；柱不套梁挠度，已计算节点位移保留'}, {'item':'frame_second_order_stability','reason':'未完成二阶效应/初始缺陷及整体稳定适用性验证'}, {'item':'connections_and_supports','reason':'连接节点、柱脚及基础承载力不在本杆系验证范围'}]
 return {'schema_version':'ExplicitCodeChecks/1.1','applicability_policy':'force-aware-v1; no-slab-restraint; NA requires recorded reason','scope':'框架自重工况的已实现截面强度、抗剪保守上界及梁挠度验算；不等同完整结构规范通过','status':'FAIL' if counts['FAIL'] else 'INCOMPLETE','summary':counts,'members':members,'project_pending':missing,'assumptions':[f'承载力按 {g0:g}×{gg:g}G，γ0/γG可通过Design_Controls设置；缺省值须按设计条件确认',f'正常使用按1.0G，梁挠度缺省L/{den:g}；按楼盖主梁控制，需核对实际用途','模型未定义孔洞及截面削弱，采用给定毛截面；板件分项另列，未满足S4筛查者须精算有效截面，毛截面应力通过不等于有效截面强度通过','Q355强度表的牌号修订及材料质量证明需独立复核，未将Fy直接当作f'],'source':SOURCE}
