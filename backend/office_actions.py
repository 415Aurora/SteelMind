"""Rectangular closed-building face wind, with exact height-strip integration."""
import math
import numpy as np
from office_contracts import geometry_model
from office_loads import empty_case,audit_case,add_uniform


def wind_height_factor(z,terrain='C'):
 if terrain!='C':raise ValueError('该风表当前只实现C类，禁止静默套用')
 points=[(0.,.65),(15.,.65),(20.,.74),(30.,.88),(40.,1.),(50.,1.1)]
 if not 0<=z<=50:raise ValueError('风压高度超出此表适用范围')
 for (a,fa),(b,fb) in zip(points,points[1:]):
  if a<=z<=b:return fa+(fb-fa)*(z-a)/(b-a)
 raise ValueError('无可用风压高度系数')


def _roof_suction(bundle,model,case,wind_axis,sign):
 height=max(n['xyz'][2] for n in model['nodes'].values());extent=max(n['xyz'][wind_axis] for n in model['nodes'].values());mid=extent/2;F=np.zeros(3);M=np.zeros(3)
 def line(axis,constant,lo,hi,q):
  found=0.
  for member_id,m in model['members'].items():
   if m['member_type']!='beam':continue
   a=np.asarray(model['nodes'][m['i_node']]['xyz']);b=np.asarray(model['nodes'][m['j_node']]['xyz'])
   if abs(a[2]-height)>1e-7 or abs(b[2]-height)>1e-7 or abs(a[1-axis]-constant)>1e-7 or abs(b[1-axis]-constant)>1e-7:continue
   start,end=sorted((a[axis],b[axis]));overlap=min(hi,end)-max(lo,start)
   if overlap>1e-7:
    if abs(overlap-(end-start))>1e-6:raise ValueError('屋面风吸力分界需先拆分梁')
    add_uniform(case,member_id,[0.,0.,q],{'source_id':'ROOF_WIND','source_type':'roof_suction'});found+=end-start
  if abs(found-(hi-lo))>1e-6:raise ValueError('屋面风支承边不完整')
 pressure=bundle['parameters']['wind_basic_kPa']*wind_height_factor(height,bundle['parameters']['terrain'])
 for panel in bundle['panels']:
  if panel['use']!='roof':continue
  x0,x1,y0,y1=panel['rect_m'];bounds=[(x0,x1),(y0,y1)];span=0 if panel['span_axis']=='X' else 1;along=1-span;a,b=bounds[wind_axis];cuts=sorted(set([a,b]+([mid] if a<mid<b else [])))
  for c,d in zip(cuts,cuts[1:]):
   windward=((c+d)/2<mid) if sign==1 else ((c+d)/2>mid);q=pressure*(.6 if windward else .5);rect=[list(v) for v in bounds];rect[wind_axis]=[c,d];area=(rect[0][1]-rect[0][0])*(rect[1][1]-rect[1][0]);f=np.array([0.,0.,q*area]);F+=f;M+=np.cross([(rect[0][0]+rect[0][1])/2,(rect[1][0]+rect[1][1])/2,height],f)
   lo,hi=bounds[span];length=hi-lo
   if wind_axis==span:
    # Reaction of the pressure strip about the ORIGINAL panel support edges.
    reaction_hi=q*((d-lo)**2-(c-lo)**2)/(2*length);reaction_lo=q*(d-c)-reaction_hi
    for edge,reaction in ((lo,reaction_lo),(hi,reaction_hi)):line(along,edge,bounds[along][0],bounds[along][1],reaction)
   else:
    for edge in (lo,hi):line(along,edge,c,d,q*length/2)
 return F,M


def build_wind_cases(bundle):
 model=geometry_model(bundle);p=bundle['parameters'];nodes=model['nodes'];levels=sorted({n['xyz'][2] for n in nodes.values()});xmax=max(n['xyz'][0] for n in nodes.values());ymax=max(n['xyz'][1] for n in nodes.values());height=max(levels)
 if height>30 or height/min(xmax,ymax)>1.5:raise ValueError('需要另行风振分析，当前低矮矩形建筑风模型不适用')
 result={}
 for direction in ('X','Y'):
  axis=0 if direction=='X' else 1;transverse=1-axis;width=ymax if axis==0 else xmax;depth=xmax if axis==0 else ymax
  for sign,label in ((1,'P'),(-1,'N')):
   case=empty_case('W_'+direction+label);F=np.zeros(3);M=np.zeros(3)
   for z0,z1 in zip(levels,levels[1:]):
    # Two-point Gauss is exact for linear mu(z), including the z*q moment.
    strips=sorted(set([z0,z1]+[z for z in (15.,20.,30.,40.,50.) if z0<z<z1]));integral=moment=0.
    for a,b in zip(strips,strips[1:]):
     for xi in (-1/math.sqrt(3),1/math.sqrt(3)):
      z=(a+b)/2+(b-a)/2*xi;v=p['wind_basic_kPa']*wind_height_factor(z,p['terrain'])*(b-a)/2;integral+=v;moment+=v*z
    for face,coefficient in ((0.,.8 if sign==1 else .5),(depth,.5 if sign==1 else .8)):
     total=sign*coefficient*width*integral;top=(sign*coefficient*width*moment-z0*total)/(z1-z0);bottom=total-top
     for z,force in ((z0,bottom),(z1,top)):
      # Only real column nodes receive cladding-to-frame forces. Tributary
      # widths are consistent half-span values and preserve the face centroid.
      candidates=[]
      column_nodes={m['i_node'] for m in model['members'].values() if m['member_type']=='column'}|{m['j_node'] for m in model['members'].values() if m['member_type']=='column'}
      for nid in column_nodes:
       a=nodes[nid]['xyz']
       if abs(a[2]-z)<1e-7 and abs(a[axis]-face)<1e-7:candidates.append((a[transverse],nid))
      candidates.sort()
      if len(candidates)<2:raise ValueError('风立面承托节点缺失')
      for i,(coordinate,nid) in enumerate(candidates):
       before=candidates[i-1][0] if i else coordinate;after=candidates[i+1][0] if i<len(candidates)-1 else coordinate;tributary=(after-before)/2
       values=case['nodal_loads_kN_kNm'].setdefault(nid,[0.]*6);values[axis]+=force*tributary/width
     force=np.zeros(3);force[axis]=total;point=np.array([0.,0.,moment/integral]);point[axis]=face;point[transverse]=width/2;F+=force;M+=np.cross(point,force)
   roof_force,roof_moment=_roof_suction(bundle,model,case,axis,sign);F+=roof_force;M+=roof_moment
   case['audit']=audit_case(case,model,F,M);case['wind_parameters']={'windward_mu':.8,'leeward_abs_mu':.5,'beta_z':1.,'height_m':height,'terrain':'C','method':'closed rectangular prism, principal directions; GB50009表8.3.1(1)及8.4.1；原图已核验','normative_evidence_status':'verified_official_table_image','roof_mu_windward':-.6,'roof_mu_leeward':-.5,'roof_slope_deg':0.,'evidence':'住建部GB50009-2012 PDF物理42页/印刷34页 表8.3.1第1项；低坡封闭式房屋，另核局部围护压力，不以此代替围护设计'};result[case['case_id']]=case
 return result
