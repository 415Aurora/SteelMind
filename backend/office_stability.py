"""Auditable GB50017 stability kernels; geometric authority is never overwritten."""
from __future__ import annotations
import math


def compression_phi(slenderness,fy,E=206000.,curve='d'):
 if slenderness<0 or fy<=0 or E<=0:raise ValueError('受压稳定参数无效')
 normalized=slenderness/math.pi*math.sqrt(fy/E)
 coefficients={'a':(.41,.986,.152),'b':(.65,.965,.3),'c':(.73,.906,.595) if normalized<=1.05 else (.73,1.216,.302),'d':(1.35,.868,.915) if normalized<=1.05 else (1.35,1.375,.432)}
 if curve not in coefficients:raise ValueError('屈曲曲线应为a/b/c/d')
 a1,a2,a3=coefficients[curve]
 if normalized<=.215:return max(0.,1-a1*normalized**2)
 term=a2+a3*normalized+normalized**2
 return min(1.,2/(term+math.sqrt(max(0.,term*term-4*normalized**2))))


def beam_phi(section,unbraced_mm,fy,beta_b=.69):
 A=section['A'];h=float(section['depth_mm']);tf=float(section['tf_mm']);W=float(section.get('Zx_mm3') or 2*section['Iz']/h);lam=unbraced_mm/math.sqrt(section['Iy']/A)
 if unbraced_mm<=0 or beta_b<=0:raise ValueError('梁侧向无支撑长度/系数无效')
 raw=beta_b*4320/lam**2*A*h/W*math.sqrt(1+(lam*tf/(4.4*h))**2)*(235/fy)
 phi=min(1.,1.07-.282/raw) if raw>.6 else raw
 return {'phi_b':phi,'raw_phi_b':raw,'lambda_y':lam,'beta_b':beta_b,'grade_factor':235/fy,'unbraced_mm':unbraced_mm,'basis':'GB50017 C.0.1-1/7；采用表C.0.1荷载类型的保守β下限0.69；混合端矩/均布/集中作用采用各分解弯矩绝对值和的上界，不将其误称实际最大弯矩','boundary':'双轴对称H，物理端防扭、翘曲自由，无中间翼缘支撑；不按网格缩短长度'}


def box_effective_section(section,fy):
 h,b,tw,tf=[float(section[k]) for k in ('depth_mm','width_mm','tw_mm','tf_mm')];eps=math.sqrt(235/fy)
 def width(clear,t):
  lam=clear/t/(28.1*eps*math.sqrt(4.));rho=1. if lam<=.75 else min(1.,max(0.,(1-.191/lam)/lam))
  return clear*(1-rho),rho
 dh,rh=width(h-2*tf,tw);db,rb=width(b-2*tw,tf)
 area=section['A']-2*dh*tw-2*db*tf
 Iz=section['Iz']-2*tw*dh**3/12-2*(db*tf**3/12+db*tf*((h-tf)/2)**2)
 Iy=section['Iy']-2*tf*db**3/12-2*(dh*tw**3/12+dh*tw*((b-tw)/2)**2)
 if min(area,Iz,Iy)<=0:raise ValueError('有效截面为非正，无法使用给定毛截面性质')
 return {'A_mm2':area,'Iy_mm4':Iy,'Iz_mm4':Iz,'Wy_mm3':2*Iy/b,'Wz_mm3':2*Iz/h,'rho_web':rh,'rho_flange':rb,'removed_web_width_mm':dh,'removed_flange_width_mm':db,'basis':'GB50017 8.4.2；四板按均匀受压kσ=4保守折减，中心去除无效条带；权威毛截面另存','gross_A_mm2':section['A'],'gross_Iy_mm4':section['Iy'],'gross_Iz_mm4':section['Iz']}


def geometry_s4(section,fy):
 h,b,tw,tf=[float(section[k]) for k in ('depth_mm','width_mm','tw_mm','tf_mm')];eps=math.sqrt(235/fy);box=str(section['shape']).upper() in ('BOX','RHS','SHS')
 if box:ratios={'web':(h-2*tf)/tw/(45*eps),'flange':(b-2*tw)/tf/(45*eps)}
 else:ratios={'web':(h-2*tf)/tw/(45*eps),'flange':(b-tw)/(2*tf)/(15*eps)}
 return {'status':'PASS' if max(ratios.values())<=1+1e-9 else 'NEEDS_REFINEMENT','ratios':ratios,'epsilon_k':eps,'method':'uniform_compression_sufficient_S4','basis':'GB50017 表3.5.1，按均匀受压取保守充分条件；未满足只说明需应力梯度/有效截面精算，不宣告真实承载力失败'}


def material_strength(grade,thickness):
 from explicit_checks import design_strength
 row=design_strength(grade,thickness);normalized=row['grade'];fy0=int(normalized[1:]);fy=(fy0 if thickness<=16 else fy0-10 if thickness<=40 else fy0-20) if normalized=='Q235' else fy0 if thickness<=16 else fy0-10 if thickness<=40 else fy0-20 if thickness<=63 else fy0-30 if thickness<=80 else fy0-40
 row.update(fy_MPa=fy,grade_correction_fy_MPa=fy0,table_review_required=False,table_review_status='公开转载原始勘误表数值已逐格核对，非出版社原发认证',official_publication_authenticated=False,source='GB50017-2017 表4.4.1及2019勘误表公开转载；Q355更正表图已归档核对，冷弯产品不适用',evidence_url='https://5b0988e595225.cdn.sohucs.com/images/20190719/9646e3d31078452cad8a9d1c9b653349.jpeg')
 return row
