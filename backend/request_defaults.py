"""Explicit teaching assumptions for missing *inputs*, never computed results."""
import copy,json
from pathlib import Path
CONFIG=json.loads((Path(__file__).resolve().parent.parent/'dist/design-defaults.json').read_text())
def blank(v):return v is None or isinstance(v,str) and not v.strip() or v==[]
def apply_request_defaults(payload):
 r=copy.deepcopy(payload)
 def current(path):
  value=r
  for key in path.split('.'):
   if not isinstance(value,dict):return None
   value=value.get(key)
  return value
 audit=[a for a in (r.get('default_assumptions') or []) if isinstance(a,dict) and current(a.get('path',''))==a.get('value')]
 def record(path,value,reason):
  audit[:]=[a for a in audit if a.get('path')!=path]
  audit.append({'path':path,'value':copy.deepcopy(value),'reason':reason,'profile':CONFIG['profile']})
 for name in ['geometry','loads','material','model_sections','candidate_sections']:
  if blank(r.get(name)):r[name]={}
  if not isinstance(r[name],dict):raise ValueError(name+' 必须为参数对象')
 g=r['geometry'];l=r['loads']
 for block,new,old in [(g,'bays_x','bays'),(g,'bay_widths_x_m','bay_widths_m'),(l,'lateral_x_by_story_kN','lateral_by_story_kN'),(l,'q_z_by_story_kN_per_m','q_by_story_z_kN_per_m')]:
  if blank(block.get(new)) and not blank(block.get(old)):block[new]=copy.deepcopy(block[old])
 for group in ['geometry','loads','material','model_sections','candidate_sections']:
  for k,v in CONFIG[group].items():
   if blank(r[group].get(k)):r[group][k]=copy.deepcopy(v);record(group+'.'+k,v,'未填写，采用教学默认值')
 for key in ['project_name','max_iterations','target_utilization']:
  if blank(r.get(key)):r[key]=CONFIG[key];record(key,r[key],'未填写，采用教学默认值')
 for path,(count_key,default) in CONFIG['arrays'].items():
  group,key=path.split('.');count=g[count_key]
  try:
   n=int(count)
   if isinstance(count,bool) or float(count)!=n or not 1<=n<=30:continue
  except (ValueError,TypeError,OverflowError):continue
  value=r[group].get(key)
  # Respect legacy scalar geometry explicitly supplied by users.
  if blank(value) and group=='geometry':
   legacy='height_m' if key=='story_heights_m' else 'bay_m' if key=='bay_widths_x_m' else 'bay_depth_m'
   if not blank(g.get(legacy)):default=g[legacy]
  if blank(value):r[group][key]=[default]*n;record(path,r[group][key],'未填写，按层数/跨数采用默认均布值')
  elif isinstance(value,list) and len(value)==1 and n>1:r[group][key]=value*n;record(path,r[group][key],'仅填一个值，明确按各层/各跨相同展开')
 for role in ('beam','column'):
  if isinstance(r.get('sections'),dict):
   r['sections'].setdefault(role,{})
   if blank(r['sections'][role].get('name')):r['sections'][role]['name']=r['model_sections'][role+'_section'];record('sections.'+role+'.name',r['sections'][role]['name'],'未填写，采用初始截面')
  names=r['candidate_sections'][role];initial=r['model_sections'][role+'_section']
  if isinstance(names,list) and initial not in names and any(a['path']=='candidate_sections.'+role for a in audit):r['candidate_sections'][role]=[initial];record('candidate_sections.'+role,[initial],'默认候选采用用户初始截面，不擅自调整其大小')
 r['default_assumptions']=audit;r['default_profile']=CONFIG['profile']
 return r
