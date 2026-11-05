"""GB/T50011 adopted elastic spectrum and signed modal CQC mathematics."""
import math
import numpy as np
from office_loads import empty_case


def spectrum_alpha(period_s,Tg_s=.9,damping=.04,alpha_max=.04):
 T=float(period_s);z=float(damping)
 if not 0<=T<=6 or not 0<Tg_s<=1.2 or not 0<z<1:raise ValueError('反应谱参数超出实现范围')
 gamma=.9+(.05-z)/(.3+6*z);eta1=max(0.,.02+(.05-z)/(4+32*z));eta2=max(.55,1+(.05-z)/(.08+1.6*z))
 if T<.1:factor=.45+(eta2-.45)*T/.1
 elif T<=Tg_s:factor=eta2
 elif T<=5*Tg_s:factor=eta2*(Tg_s/T)**gamma
 else:factor=eta2*.2**gamma-eta1*(T-5*Tg_s)
 return alpha_max*max(0.,factor)


def cqc_matrix(periods,damping=.04):
 T=np.asarray(periods,float);z=float(damping)
 if np.any(~np.isfinite(T)) or np.any(T<=0) or not 0<z<1:raise ValueError('CQC周期/阻尼无效')
 r=T[None,:]/T[:,None]
 rho=8*z*z*(1+r)*r**1.5/((1-r*r)**2+4*z*z*r*(1+r)**2)
 return (rho+rho.T)/2


def cqc(values,correlation):
 v=np.asarray(values,float);rho=np.asarray(correlation,float)
 return float(math.sqrt(max(0.,float(v@rho@v))))


def build_modal_load_cases(modal,bundle,direction):
 if not modal.get('ok'):raise ValueError('模态分析未通过')
 if direction not in ('X','Y'):raise ValueError('地震方向无效')
 out=[];p=bundle['parameters'];d=0 if direction=='X' else 1
 for mode in modal['modes']:
  case=empty_case(f'E{direction}-M{mode["mode"]:02}');case['mass_offset']=modal['mass_offset'];case['modal_index']=mode['mode'];case['direction']=direction
  gamma=mode['participation_x' if direction=='X' else 'participation_y'];a=spectrum_alpha(mode['period_s'],p['Tg_s'],p['damping_ratio'])*9806.65
  for name,master in modal['masters'].items():
   x,y,rz=mode['shape'][name];f=[master['mass_t']*x*gamma*a/1000,master['mass_t']*y*gamma*a/1000,0.,0.,0.,master['polar_mass_t_mm2']*rz*gamma*a/1e6];case['nodal_loads_kN_kNm'][name]=f
  out.append(case)
 return out


def minimum_shear_scale(modal,cases,direction):
 rho=cqc_matrix([m['period_s'] for m in modal['modes']],modal.get('damping_ratio',.04));index=0 if direction=='X' else 1;floors=modal['mass_source']['floors'];T=modal['modes'][0]['period_s'];coef=.008 if T<=3.5 else .006 if T>=5 else .008-(T-3.5)/1.5*.002
 scale=1.;rows=[]
 for floor in floors:
  above=['@F'+str(f['floor']) for f in floors if f['floor']>=floor['floor']];values=[sum(c['nodal_loads_kN_kNm'][key][index] for key in above) for c in cases];V=cqc(values,rho);limit=coef*sum(f['mass_t']*9.80665 for f in floors if f['floor']>=floor['floor']);required=limit/V if V>1e-12 else math.inf;scale=max(scale,required);rows.append({'floor':floor['floor'],'CQC_shear_kN':V,'minimum_kN':limit,'required_scale':required})
 if not math.isfinite(scale):raise ValueError('地震层剪力为零，不能进行最小剪力调整')
 return scale,rows
