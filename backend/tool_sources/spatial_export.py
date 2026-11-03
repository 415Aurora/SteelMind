"""SpatialResultBundle/1.0: preserve the final 3D solver state, never project it into a 2D design bundle."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

SCHEMA='SpatialResultBundle/1.0'
BASE_REASONS=[
 '三维线弹性单静力工况的方案级结果，不是完整荷载组合包络或施工图。',
 '上游验算含稳定筛查简化；双向压弯耦合、扭转载荷效应、层间位移适用限值和节点连接未完成独立规范复核。',
 '计算长度按上游几何长度；需按侧移、支撑及节点约束复核。',
 '详算仅保留上游提交公式和数值；缺少的公式、限值、条文或组合不得补造。',
]
END_KEYS=('Ni_kN','Vyi_kN','Vzi_kN','Ti_kNm','Myi_kNm','Mzi_kNm','Nj_kN','Vyj_kN','Vzj_kN','Tj_kNm','Myj_kNm','Mzj_kNm')
DOFS=('ux_mm','uy_mm','uz_mm','rx_rad','ry_rad','rz_rad')
REACTIONS=('fx_kN','fy_kN','fz_kN','mx_kNm','my_kNm','mz_kNm')

def is_spatial_report(report):
 analysis=report.get('analysis') or {};g=(analysis.get('parameters') or {}).get('geometry') or {}
 return bool(g.get('bays_z')) or str((analysis.get('results') or {}).get('model','')).startswith('3D') or any(float(n.get('z_m',0) or 0)!=0 for n in (analysis.get('results') or {}).get('model_nodes',[]))

def _number(value,path):
 if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError(f'{path} 必须是有限数值')
 return float(value)

def _unique(rows,key,label):
 ids=[str(row.get(key) or '') for row in rows]
 if not rows or any(not v for v in ids) or len(set(ids))!=len(ids):raise ValueError(f'{label} 为空、编号缺失或重复')
 return dict(zip(ids,rows))

def _axes(a,b,axis):
 x=[b[k]-a[k] for k in ('x_m','y_m','z_m')];length=math.sqrt(sum(v*v for v in x))
 if length<1e-8:raise ValueError('不支持零长构件')
 x=[v/length for v in x];v=[0.,0.,1.] if axis=='X' else [1.,0.,0.]
 def cross(a,b):return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]
 y=cross(v,x);n=math.sqrt(sum(c*c for c in y))
 if n<1e-8:raise ValueError('构件局部轴与上游约定不兼容')
 y=[c/n for c in y];return {'x':x,'y':y,'z':cross(x,y)},length

def normalize_spatial_report(report):
 if report.get('converged') is not True or report.get('status')!='converged':raise ValueError('仅接受工作流2收敛的最终三维报告')
 # Reject non-JSON numbers anywhere, including unused raw records. Never execute formula strings.
 json.dumps(report,ensure_ascii=False,allow_nan=False)
 analysis=report.get('analysis') or {}
 if analysis.get('ok') is not True:raise ValueError('最终三维分析结果未成功')
 p=analysis.get('parameters') or {};result=analysis.get('results') or {}
 from analysis_input import analysis_shape_errors
 errors=analysis_shape_errors(p)
 if errors:raise ValueError('；'.join(errors))
 nodes=copy.deepcopy(result.get('model_nodes') or []);node_by_id=_unique(nodes,'node_id','节点')
 for n in nodes:
  for k in ('x_m','y_m','z_m')+DOFS:_number(n.get(k),f"node/{n['node_id']}/{k}")
 members=copy.deepcopy(result.get('members') or []);member_by_id=_unique(members,'member_id','构件')
 checks=copy.deepcopy(report.get('member_checks') or []);check_by_id=_unique(checks,'member_id','验算')
 if set(member_by_id)!=set(check_by_id):raise ValueError('实体构件编号与逐构件验算记录不一致')
 sections={};warnings=[]
 for m in members:
  mid=m['member_id'];c=check_by_id[mid]
  if c.get('passed') is not True or any(v.get('passed') is not True for v in c.get('checks',[])):raise ValueError(f'{mid} 存在未通过或未判定的上游验算，不可将其标记为收敛成果')
  if not c.get('checks'):warnings.append(f'{mid} 缺少逐项公式或验算记录')
  if c.get('section')!=m.get('section'):raise ValueError(f'{mid} 分析与验算截面不一致')
  if m.get('node_i') not in node_by_id or m.get('node_j') not in node_by_id:raise ValueError(f'{mid} 节点引用无效')
  if m.get('member_axis') not in ('X','Y','Z'):raise ValueError(f'{mid} 当前仅支持沿全局轴的直杆框架')
  if any(m.get(k) for k in ('offset_i','offset_j','eccentricity','rigid_zone','release_i','release_j','variable_section')):raise ValueError(f'{mid} 偏心、刚域、端部释放或变截面暂不支持')
  axes,length=_axes(node_by_id[m['node_i']],node_by_id[m['node_j']],m['member_axis'])
  axis_index={'X':0,'Y':1,'Z':2}[m['member_axis']]
  if abs(abs(axes['x'][axis_index])-1)>1e-8:raise ValueError(f'{mid} 几何与轴向标签不一致')
  if not math.isclose(_number(m.get('span_m'),mid+'.span_m'),length,rel_tol=1e-6,abs_tol=1e-6):raise ValueError(f'{mid} 几何长度与分析长度不一致')
  m['local_axes']=axes
  for key in END_KEYS:_number((m.get('end_actions_local') or {}).get(key),mid+'.'+key)
  for k in ('N_kn','Mx_kNm','My_kNm','Vy_kn','Vz_kn','T_kNm','deflection_mm'):
   value=_number(m.get(k),mid+'.'+k);submitted=(c.get('analysis_demands') or {}).get(k)
   if submitted is None or not math.isclose(value,_number(submitted,mid+'.analysis_demands.'+k),rel_tol=1e-6,abs_tol=1e-7):raise ValueError(f'{mid} 分析与验算采用值 {k} 不一致')
  _number(c.get('utilization'),mid+'.utilization')
  if c['utilization']>1+1e-8:raise ValueError(f'{mid} 利用率大于1但结论为通过')
  props=(p.get('member_sections') or {}).get(mid) or (p.get('sections') or {}).get(m.get('member_type')) or {}
  if props.get('name')!=m.get('section'):raise ValueError(f'{mid} 缺少最终截面的权威属性快照')
  for k in ('A_mm2','Iy_mm4','Iz_mm4','J_mm4','h_mm','b_mm','tw_mm','tf_mm'):
   if _number(props.get(k),mid+'.section.'+k)<=0:raise ValueError(f'{mid} 截面属性 {k} 应为正值')
  if m['section'] in sections and sections[m['section']]!=props:raise ValueError(f'{mid} 同名截面 {m["section"]} 的权威属性不一致；不能合并或覆盖')
  sections[m['section']]=copy.deepcopy(props)
 supports=copy.deepcopy(result.get('supports') or []);_unique(supports,'node_id','支座')
 reactions=copy.deepcopy(result.get('support_reactions') or []);_unique(reactions,'node_id','支反力')
 if {s['node_id'] for s in supports}!={s['node_id'] for s in reactions}:raise ValueError('支座与支反力节点不一致')
 for s in supports:
  if s['node_id'] not in node_by_id:raise ValueError('支座节点引用无效')
  for k in ('ux','uy','uz','rx','ry','rz'):
   if not isinstance(s.get(k),bool):raise ValueError(f'支座 {s["node_id"]}.{k} 缺少明确约束')
 for row in reactions:
  for k in REACTIONS:_number(row.get(k),'reaction.'+k)
 reasons=BASE_REASONS+[str(report.get('engineering_notice') or result.get('engineering_notice') or '上游未提供适用范围说明')]
 return {'schema_version':SCHEMA,'project_name':str(report.get('project_name') or '三维钢框架方案'),'source_run_id':str(report.get('run_id') or ''),
  'units':{'coordinates':'m','drawing':'mm','displacement':'mm','rotation':'rad','force':'kN','moment':'kN·m','stress':'MPa'},
  'axis_convention':'Global Y up; local x=I→J; local y=vecXZ×x, local z=x×y; end_actions_local are nodal actions on the member, not signed section-force diagrams.',
  'parameters':copy.deepcopy(p),'nodes':nodes,'members':members,'supports':supports,'reactions':reactions,'sections':sections,
  'checks':checks,'iterations':copy.deepcopy(report.get('iterations') or []),'summary':{k:v for k,v in result.items() if k not in ('members','model_nodes','supports','support_reactions')},
  'draft_reasons':list(dict.fromkeys(reasons)),'warnings':warnings,'source':'OpenSees final analysis + upstream member checks; normalized without independent recalculation'}

def inspect_spatial_report(report):
 try:
  b=normalize_spatial_report(report)
  return {'valid':True,'data_validation_status':'valid','upstream_check_summary':'INCOMPLETE','draft':True,'draft_reasons':b['draft_reasons'],'errors':[], 'warnings':b['warnings'],'bundle':b,'format':SCHEMA}
 except Exception as exc:
  return {'valid':False,'data_validation_status':'invalid','upstream_check_summary':'FAIL' if any(c.get('passed') is False for c in report.get('member_checks',[])) else 'INCOMPLETE','draft':True,'draft_reasons':[str(exc)],'errors':[{'code':'spatial_adapter_error','path':'/','message':str(exc)}],'warnings':[],'bundle':None,'format':SCHEMA}

def generate_spatial_package(report,options,output_root):
 """Generate independently versioned 3D scheme artifacts; returns transport-neutral file manifest."""
 from steelmind_export.results import GenerationOptions
 from steelmind_export import runtime
 from tool_sources.spatial_reports import write_book,write_workbook
 from tool_sources.spatial_cad import generate_cad
 opts=GenerationOptions.model_validate(options or {})
 preflight=inspect_spatial_report(report)
 if not preflight['valid']:return {'ok':False,'status':'input_invalid','preflight':{k:v for k,v in preflight.items() if k!='bundle'},'artifacts':[]}
 bundle=preflight.pop('bundle');run_id=uuid4().hex;root=Path(output_root).resolve()/run_id;root.mkdir(parents=True,exist_ok=False)
 def dump(name,data):
  p=root/name;p.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');return p
 files=[dump('input_snapshot.json',report),dump('spatial_bundle.json',bundle),dump('validation.json',preflight)]
 warnings=list(bundle['warnings']);errors=[]
 book=root/'三维结构计算书.docx';write_book(bundle,book);files.append(book)
 xlsx=root/'三维结果表.xlsx';write_workbook(bundle,xlsx);files.append(xlsx)
 if opts.include_pdf:
  try:files.append(runtime.convert_docx_to_pdf(book,root,timeout=opts.office_timeout_s))
  except Exception as e:errors.append(f'计算书PDF转换失败：{e}')
 cadfiles,cadwarnings,caderrors=generate_cad(bundle,root/'cad',include_pdf=opts.include_pdf);files+=cadfiles;warnings+=cadwarnings;errors+=caderrors
 if opts.include_dwg:warnings.append('三维导出暂未接入ODA回转检查，DWG未生成；DXF完整保留。')
 input_hash=hashlib.sha256(json.dumps(report,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
 files.append(dump('generation_log.json',{'run_id':run_id,'source_run_id':bundle['source_run_id'],'schema_version':SCHEMA,'input_sha256':input_hash,'warnings':warnings,'errors':errors,'drawing_source':'saved R2018 DXF A3 layouts','office_pdf':'same DOCX via LibreOffice' if opts.include_pdf else 'not requested'}))
 def artifact(path,i):
  raw=path.read_bytes();return {'id':f'a{i:04d}','name':path.name,'relative_path':path.relative_to(root).as_posix(),'media_type':mimetypes.guess_type(path.name)[0] or 'application/octet-stream','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
 records=[artifact(p,i) for i,p in enumerate(files,1)]
 manifest=dump('manifest.json',{'run_id':run_id,'schema_version':SCHEMA,'input_sha256':input_hash,'generation_status':'partial' if errors else 'success','data_validation_status':'valid','upstream_check_summary':'INCOMPLETE','draft':True,'draft_reasons':bundle['draft_reasons'],'artifacts':records,'self_exclusion':'manifest and ZIP omitted from internal hashes to avoid circular hashing'})
 files.append(manifest);archive=root/'三维工程成果包.zip'
 with ZipFile(archive,'w',ZIP_DEFLATED) as z:
  for p in files:z.write(p,p.relative_to(root))
 files.append(archive);records=[artifact(p,i) for i,p in enumerate(files,1)]
 return {'ok':True,'status':'partial' if errors else 'success','generation_status':'partial' if errors else 'success','data_validation_status':'valid','upstream_check_summary':'INCOMPLETE','draft':True,'draft_reasons':bundle['draft_reasons'],'warnings':warnings,'errors':errors,'preflight':preflight,'run_id':run_id,'input_sha256':input_hash,'output_dir':str(root),'artifacts':records}
