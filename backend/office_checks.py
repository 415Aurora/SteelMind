"""Conservative elastic member checks with explicit applicability and handoff.

Response component maxima are UPPER BOUNDS, not simultaneous force vectors.
Gamma and equivalent moment coefficients are conservatively taken as 1.
No slab lateral support, plastic section reserve or seismic resistance bonus.
"""
from __future__ import annotations
import math
from collections import Counter
from office_stability import material_strength,compression_phi,beam_phi,geometry_s4,box_effective_section


def torsion_assessment(ratio,*,spatial_bidirectional_accidental):
 return {'classification':'TORSIONALLY_IRREGULAR' if ratio>1.2 else 'REGULAR_BY_TORSION','classification_threshold':1.2,'limit':1.5,'status':'PASS' if ratio<=1.2 or (ratio<=1.5 and spatial_bidirectional_accidental) else 'PENDING','treatment':'三维空间模型、面内扭转、双向地震效应与±5%偶然质量偏心；1.2是分类阈值，1.5是本次采用的位移比控制'}


def check_member(d,section,material,*,second_order_verified=False,stiffener=None):
 pid=d['physical_member_id'];s=section;h,b,tw,tf=[float(s[k]) for k in ('depth_mm','width_mm','tw_mm','tf_mm')];box=str(s['shape']).upper() in ('BOX','RHS','SHS');E=material['E_MPa'];strength=material_strength(material['grade'],max(tw,tf));f=strength['f_MPa'];fv=strength['fv_MPa'];fy=strength['fy_MPa'];fy0=strength['grade_correction_fy_MPa'];A=s['A'];Wy=2*s['Iy']/b;Wz=2*s['Iz']/h;checks=[];handoff=[]
 def record(item,util,formula,basis,inputs,reason='',status=None):
  checks.append({'item':item,'status':status or ('PASS' if util<=1+1e-9 else 'FAIL'),'utilization':util,'demand':util,'limit':1.,'unit':'ratio','formula':formula,'inputs':inputs,'substitution':'; '.join(f'{k}={v:.9g}' if isinstance(v,(float,int)) else f'{k}={v}' for k,v in inputs.items()),'basis':basis,'data_location':f'physical_members/{pid}; governing_combinations/{d.get("combination_id","envelope")}','reason':reason})
 plate=geometry_s4(s,fy0);record('plate_class_S4_sufficient',max(plate['ratios'].values()),'max[(h0/tw)/(45εk),c/tf/(15εk)] ≤ 1' if not box else 'max[(h0/tw),(b0/tf)]/(45εk) ≤ 1','GB50017 表3.5.1',plate,reason=plate['method'],status='PASS' if plate['status']=='PASS' else 'PENDING')
 effective=box_effective_section(s,fy0) if box else {'A_mm2':A,'Wy_mm3':Wy,'Wz_mm3':Wz,'basis':'S4充分条件满足后采用弹性毛截面；未满足时强度值仅供改型筛查'}
 Ae,We_y,We_z=[effective[k] for k in ('A_mm2','Wy_mm3','Wz_mm3')]
 N=d['N_abs_kN']*1000;Nc=d['N_compression_kN']*1000;My=d['My_kNm']*1e6;Mz=d['Mz_kNm']*1e6
 omega=b*(h-tf)/4;Iw=tf*b**3*(h-tf)**2/24 if not box else 1.
 sigma=N/Ae+My/We_y+Mz/We_z+(d['B_Nmm2']*omega/Iw if not box else 0.)
 if box:
  tau=1.5*(d['Vy_kN']*1000/(2*(h-2*tf)*tw)+d['Vz_kN']*1000/(2*(b-2*tw)*tf))+d['T_kNm']*1e6/(2*(h-tf)*(b-tw)*min(tw,tf))
 else:
  Q=b*tf*(h-tf)/2+tw*(h/2-tf)**2/2
  tau=d['Vy_kN']*1000*Q/(s['Iz']*tw)+3*d['Vz_kN']*1000/(2*b*tf)+d['Tsv_Nmm']*max(tw,tf)/s['J']+d['Twarp_Nmm']*b*b*(h-tf)/(16*Iw)
 record('elastic_section_strength',sigma/f,'σup = |N|/Ae+|My|/Wey+|Mz|/Wez+|B|ωmax/Iw ≤ f','GB50017 6.1/8.1，保守γ=1，无塑性储备',{'sigma_upper_MPa':sigma,'f_MPa':f,'Ae_mm2':Ae,'We_y_mm3':We_y,'We_z_mm3':We_z,'B_Nmm2':d['B_Nmm2'],'Iw_mm6':Iw,'gamma_RE':1.,'effective_section':effective})
 record('combined_shear_and_torsion',tau/fv,'τup = Σ|τV|+|τSaintVenant|+|τwarping| ≤ fv','GB50017 6.1.2；薄壁弹性剪应力叠加上界',{'tau_upper_MPa':tau,'fv_MPa':fv,'SaintVenant_T_Nmm':d['Tsv_Nmm'],'warping_shear_T_Nmm':d['Twarp_Nmm']})
 record('equivalent_stress',math.hypot(sigma,math.sqrt(3)*tau)/f,'sqrt(σup²+3τup²) ≤ f','GB50017 6.1.3；取更保守的f而非1.1f',{'sigma_upper_MPa':sigma,'tau_upper_MPa':tau,'f_MPa':f})
 L=d['unbraced_length_m']*1000;lam_y=L/math.sqrt(s['Iy']/A);lam_z=L/math.sqrt(s['Iz']/A);phi_y=compression_phi(lam_y,fy,E,'d');phi_z=compression_phi(lam_z,fy,E,'d');NEy=math.pi**2*E*A/(1.1*lam_y**2);NEz=math.pi**2*E*A/(1.1*lam_z**2)
 ltb={'phi_b':1.,'unbraced_mm':L,'basis':'闭口截面φb=1'} if box else beam_phi(s,L,fy)
 if not box:
  record('lateral_torsional_stability',d['ltb_moment_bound_kNm']*1e6/(ltb['phi_b']*Wz*f),'Σ|Mdecomposed|/(φb Wz f) ≤ 1','GB50017 6.2及附录C，完整无支撑物理段',dict(ltb,ltb_moment_bound_kNm=d['ltb_moment_bound_kNm'],Wz_mm3=Wz,f_MPa=f),'荷载类型分解后绝对值和的充分上界，不称实际最大弯矩；梁端防扭性能需外部实现')
 denominators=(1-.8*Nc/NEy,1-.8*Nc/NEz)
 # This sum dominates BOTH 8.2.5 inequalities: beta=eta=gamma=1,
 # min(phi), each moment amplified and strong-axis divided by phi_b.
 stable_den=max(1e-12,min(denominators));interaction=Nc/(min(phi_y,phi_z)*Ae*f)+(My/We_y+Mz/(ltb['phi_b']*We_z))/(stable_den*f)
 record('biaxial_compression_stability',interaction,'N/(φmin Ae f)+[|My|/Wey+|Mz|/(φb Wez)]/[f min(1−0.8N/N′E)] ≤ 1','GB50017 8.2.5 两式的保守充分上界；8.3.1的μ=1仅经二阶及假想力验证后采用',{'N_compression_N':Nc,'phi_y':phi_y,'phi_z':phi_z,'lambda_y':lam_y,'lambda_z':lam_z,'NE_y_N':NEy,'NE_z_N':NEz,'moment_denominator':min(denominators),'mu':1. if second_order_verified else 'unverified','beta_m':1.,'beta_t':1.,'eta':1.,'gamma':1.,'gamma_RE':1.},status=('PENDING' if not second_order_verified else 'FAIL' if min(denominators)<=0 else None))
 if Nc>1e-6:record('compression_slenderness',max(lam_y,lam_z)/150,'max(λy,λz) ≤ 150','GB50017 7.4，主要受压构件采用150保守控制',{'lambda_y':lam_y,'lambda_z':lam_z,'limit':150.})
 if not box:
  record('web_no_intermediate_stiffener_threshold',(h-2*tf)/tw/(80*math.sqrt(235/fy0)),'h0/tw ≤ 80εk','GB50017 6.3.2，不采用屈曲后强度',{'h0_mm':h-2*tf,'tw_mm':tw,'epsilon_k':math.sqrt(235/fy0)},status='PASS' if (h-2*tf)/tw<=80*math.sqrt(235/fy0) else 'PENDING')
  if stiffener:
   bs=stiffener['width_mm'];ts=stiffener['thickness_mm'];hs=h-2*tf;Ast=2*bs*ts;I=2*ts*bs**3/3;lam=hs/math.sqrt(I/Ast);st_strength=material_strength(material['grade'],ts);ph=compression_phi(lam,st_strength['fy_MPa'],E,'d');R=2*d['Vy_kN']*1000;f_st=st_strength['f_MPa']
   record('support_stiffener_stability',R/(ph*Ast*f_st),'Rup/(φ As f) ≤ 1, Rup=2Vup, l0=h0','GB50017 6.3.7，忽略有效腹板面积的保守加劲肋验算',{'R_upper_N':R,'A_stiffeners_mm2':Ast,'I_stiffeners_mm4':I,'l0_mm':hs,'lambda':lam,'phi':ph,'f_MPa':f_st})
   record('support_stiffener_end_bearing',R/(Ast*f_st),'Rup/(As f) ≤ 1','GB50017 6.3.7-2；刨平顶紧，承压限值保守取f',{'R_upper_N':R,'A_stiffeners_mm2':Ast,'f_MPa':f_st,'end_contact':'planed_tight_contact_required'})
   record('stiffener_plate_slenderness',bs/ts/(15*math.sqrt(235/fy0)),'bs/ts ≤ 15εk','GB50017 表3.5.1 保守S4板件条件',{'bs_mm':bs,'ts_mm':ts,'epsilon_k':math.sqrt(235/fy0)})
  else:record('support_stiffener_stability',0.,'支承/集中力处承压传力应有计算与构造','GB50017 6.1.4/6.3.7',{},status='PENDING',reason='需定义支承加劲肋或腹板局部承压计算')
  handoff.append({'member_id':pid,'item':'梁端防扭/潜在塑性铰区双翼缘侧向支承与集中力加劲肋焊缝','status':'EXTERNAL_VERIFICATION_PENDING','basis':'GB55006 5.3.2；GB50017 6.3.7','performance':{'end_fork':True,'intermediate_slab_restraint':False,'warping':'free','stiffener_force_upper_kN':2*d['Vy_kN'],'stiffener':stiffener},'reason':'模型边界为已采用设计要求；连接组需验证刚度、承载力、铰区支承位置及传力路径，数学节点约束不等于构造已通过'})
 counts=Counter(c['status'] for c in checks);status='FAIL' if counts['FAIL'] else 'INCOMPLETE' if counts['PENDING'] else 'PASS'
 return {'member_id':pid,'section_id':d['section_id'],'member_type':d['member_type'],'role':d.get('role'),'status':status,'checks':checks,'coverage':dict(counts),'max_utilization':max(c['utilization'] for c in checks),'handoff':handoff,'strength_table':strength,'response_semantics':'各分量/位置/组合绝对值的保守上界，不是同时内力向量'}


def storey_stiffness(flexibility,floors,masters,target_xy=(0.,0.)):
 import numpy as np
 F=np.asarray(flexibility,float);weights=np.array([r['mass_t']*r['z_m'] for r in floors]);weights/=sum(weights);out={'method':'story_shear_over_interstory_drift','force_pattern':'horizontal floor force proportional to m_i z_i, total1N','reference_xy_m':list(target_xy)}
 for axis,name in enumerate(('X','Y')):
  force=np.zeros(len(F));force[axis::3]=weights;u=F@force;displacement=[]
  for k,floor in enumerate(floors):
   x,y,_=masters['@F'+str(floor['floor'])]['xyz_m'];rotation=u[3*k+2];value=u[3*k+axis]+(-rotation*(target_xy[1]-y)*1000 if axis==0 else rotation*(target_xy[0]-x)*1000);displacement.append(value)
  drift=np.diff([0.]+displacement);shear=np.array([sum(weights[k:]) for k in range(len(weights))])
  if min(drift)<=0:raise ValueError('采用荷载模式下层间侧移非正，不能判断竖向刚度规则性')
  out[name]={'stiffness_N_mm':(shear/drift).tolist(),'story_shear_N':shear.tolist(),'interstory_displacement_mm':drift.tolist(),'floor_displacement_mm':displacement}
 return out


def check_office_design(bundle,analysis,envelopes):
 import numpy as np
 from office_contracts import geometry_model
 from office_responses import DEMAND_KEYS
 model=geometry_model(bundle);members=[];handoff=[];stiffeners={s['physical_member_id']:s for s in bundle.get('stiffeners',[])}
 for index,pid in enumerate(analysis['physical_ids']):
  d={**analysis['physical_descriptors'][pid],**dict(zip(DEMAND_KEYS,envelopes['strength'][index])),'combination_id':'component_upper_envelope','governing_components':dict(zip(DEMAND_KEYS,envelopes['strength_control'][index]))};s=model['sections'][d['section_id']];mat=model['materials'][d['material_id']];r=check_member(d,s,mat,second_order_verified=envelopes['second_order_verified'],stiffener=stiffeners.get(pid));r['demand_upper_bounds']=d;r['control_combinations']=d['governing_components']
  if d['member_type']=='beam':
   delta=float(envelopes['service'][index,DEMAND_KEYS.index('deflection_mm')]);limit=d['length_m']*1000/bundle['parameters']['beam_deflection_denominator'];r['checks'].append({'item':'beam_deflection','status':'PASS' if delta<=limit else 'FAIL','demand':delta,'limit':limit,'unit':'mm','utilization':delta/limit,'formula':'δphysical,chord ≤ Lphysical / '+str(bundle['parameters']['beam_deflection_denominator']),'inputs':{'length_mm':d['length_m']*1000,'deflection_upper_mm':delta,'denominator':bundle['parameters']['beam_deflection_denominator']},'substitution':f'{delta:.9g} ≤ {limit:.9g} mm','basis':'GB50017 附录B；用户采用总挠度L/400保守控制','data_location':'combinations/'+envelopes['service_control'][index][DEMAND_KEYS.index('deflection_mm')],'reason':'沿程弹性位移相对整根物理梁端弦线；保守分区/工况包络，不在网格处重新归零'})
  else:
   ratio=d['N_compression_kN']*1000/(s['A']*r['strength_table']['f_MPa']);r['checks'].append({'item':'strong_column_weak_beam_applicability','status':'NA' if ratio<=.4 else 'PENDING','demand':ratio,'limit':.4,'unit':'ratio','utilization':ratio/.4,'formula':'nupper=Nupper/(Ag f) ≤ 0.4','inputs':{'N_upper_kN':d['N_compression_kN'],'A_mm2':s['A'],'f_MPa':r['strength_table']['f_MPa']},'substitution':f'{ratio:.9g} ≤ 0.4','basis':'GB/T50011-2010(2024) 8.2.5 低轴压比例外条件','data_location':d['governing_components']['N_compression_kN'],'reason':'以f代fy作更保守轴压比；符合例外仅免强柱弱梁弯矩比，不免节点域、连接及铰区构造' if ratio<=.4 else '需进一步验算节点强柱弱梁，不自动通过'})
  counts=Counter(c['status'] for c in r['checks']);r['coverage']=dict(counts);r['status']='FAIL' if counts['FAIL'] else 'INCOMPLETE' if counts['PENDING'] else 'PASS';r['max_utilization']=max(c.get('utilization',0.) for c in r['checks'] if c['status']!='NA');members.append(r);handoff.extend(r['handoff'])
 global_checks=[]
 def add(item,value,limit,basis,reason='',status=None,**extra):
  global_checks.append({'item':item,'status':status or ('PASS' if value<=limit+1e-9 else 'FAIL'),'demand':float(value),'limit':float(limit),'utilization':float(value/limit) if limit else 0.,'basis':basis,'reason':reason,**extra})
 add('declared_scope_coverage',0,1,'OfficeDesign/1.0','完整偶然偏心和分区活载均执行后才允许通过',status='PASS' if analysis['scope_status']=='FULL_DECLARED_GQWE' else 'PENDING')
 add('global_PDelta_bound',envelopes['maximum_theta_upper_bound'],.25,'GB50017 5.1/5.4/8.3；正算子充分上界',status='PASS' if envelopes['second_order_verified'] else 'PENDING',method=envelopes.get('method'))
 heights=sorted({n['xyz'][2] for n in model['nodes'].values() if n['xyz'][2]>0})
 for index,floor in enumerate(analysis['floor_ids']):
  h=(heights[index]-(heights[index-1] if index else 0.))*1000
  for j,axis in enumerate(('X','Y')):add(f'storey_{floor}_drift_{axis}',envelopes['drift_mm'][index][j],h/bundle['parameters']['global_drift_limit_denominator'],'GB50017 B.2.2；GB/T50011 表5.5.1','标准组合及弹性地震的保守上界，含假想力及P-Delta上界',unit='mm',control=envelopes['drift_control'][index][j])
 for direction in ('X','Y'):
  details=analysis['earthquake'][direction]['details'];ratio=max((t['torsion_displacement_ratio'] for detail in details for t in detail['torsion']),default=1.)
  assessment=torsion_assessment(ratio,spatial_bidirectional_accidental=analysis['scope_status']=='FULL_DECLARED_GQWE')
  add('torsion_regularity_'+direction,ratio,assessment['limit'],'GB/T50011 3.4.3/3.4.4',assessment['treatment'],status=assessment['status'],classification=assessment['classification'],classification_threshold=1.2,details=[{'mass_offset':r['mass_offset'],'torsion':r['torsion']} for r in details])
 mass=[v['mass_t'] for v in analysis['mass_source']['floors']];mass_ratio=max((max(a/b,b/a) for a,b in zip(mass,mass[1:])),default=1.)
 add('adjacent_floor_mass_contrast',mass_ratio,1.5,'GB/T50011 3.4.3 类似不规则筛查；课程附加控制','质量对比为额外保守筛查，不冒称该表强制数值条款')
 mass_rows=[{'floor':k+1,'z_m':heights[k],**row} for k,row in enumerate(analysis['mass_source']['floors'])];master_points=analysis.get('masters') or {'@F'+str(k+1):{'xyz_m':[0.,0.,z]} for k,z in enumerate(heights)}
 centre=tuple((min(n['xyz'][j] for n in model['nodes'].values())+max(n['xyz'][j] for n in model['nodes'].values()))/2 for j in (0,1))
 stiffness_audit=storey_stiffness(analysis['flexibility'],mass_rows,master_points,centre);story_stiffness={axis:stiffness_audit[axis]['stiffness_N_mm'] for axis in ('X','Y')}
 for axis,values in story_stiffness.items():
  for k in range(len(values)-1):
   ratio=values[k]/values[k+1];add(f'stiffness_adjacent_{axis}_{k+1}',.7/ratio,1.,'GB/T50011 表3.4.3-2','采用m_i z_i水平力模式，层剪力/统一平面参考点层间侧移',stiffness_N_mm=values,ratio_lower_to_upper=ratio)
  for k in range(len(values)-3):
   ratio=values[k]/(sum(values[k+1:k+4])/3);add(f'stiffness_three_above_{axis}_{k+1}',.8/ratio,1.,'GB/T50011 表3.4.3-2',stiffness_N_mm=values)
 opening=(627-min(sum((p['rect_m'][1]-p['rect_m'][0])*(p['rect_m'][3]-p['rect_m'][2]) for p in bundle['panels'] if p['floor']==f) for f in range(1,5)))/627
 add('floor_opening_area_ratio',opening,.3,'GB/T50011 表3.4.3-1','刚性楼板为用户确认边界；其面内刚度与洞口传力由楼板组验证')
 for name,reason,basis in [('vertical_earthquake','6度普通16m框架、最大跨度8m，无本次定义的专项大跨/长悬臂','GB55002 4.1.2(3)'),('rare_inelastic_deformation','普通丙类6度、16m非高层且本次规则性控制满足；若改变为竖向不规则则本项失效','GB/T50011 5.5.2')]:
  vertical_regular=all(c['status']=='PASS' for c in global_checks if 'stiffness_' in c['item']);add(name,0,1,basis,reason,status='NA' if name=='vertical_earthquake' or vertical_regular else 'PENDING')
 handoff.extend([{'item':item,'status':'EXTERNAL_VERIFICATION_PENDING','reason':reason} for item,reason in [('刚性楼板及楼梯本体','实现面内刚性假定、洞口边缘传力、楼板梁连接及楼梯支承；未按此免梁侧扭'),('梁柱节点/柱脚/基础','实现GL2刚接、GL3铰接及柱脚固定的刚度和承载力，验算节点域/焊缝/螺栓与地基'),('层受剪承载力及抗震构造','本模块构件弹性设计成立不等于连接塑性机制成立；结构组核对层承载力、节点与塑性铰区支承'),('其他作用与工程适用条件','本次约定G/Q/W/水平E课程设计；真实工程另核勘察、温度及施工阶段/火灾等适用作用，不以本报告替代施工设计')]])
 counts=Counter(c['status'] for r in members for c in r['checks']);counts.update(c['status'] for c in global_checks);status='FAIL' if counts['FAIL'] else 'INCOMPLETE' if counts['PENDING'] else 'PASS'
 return {'schema_version':'OfficeChecks/1.0','design_status':status,'coverage_status':'INCOMPLETE' if counts['PENDING'] else 'COMPLETE','building_status':'EXTERNAL_VERIFICATION_PENDING','summary':dict(counts),'members':members,'global_checks':global_checks,'handoff':handoff,'story_stiffness_N_mm':story_stiffness,'stiffness_audit':stiffness_audit,'scope':'已采用设计边界下的上部钢框架G/Q/W/水平E弹性构件计算；构造性能另交接','method':'各分量/工况/位置上界的保守充分验算；满足可判通过，不满足可能需精算，不冒称同一实际组合应力'}
