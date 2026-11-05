// Generated config from design-defaults.json; algorithms are tested against Python.
(function(root,factory){const api=factory();if(typeof module!=="undefined"&&module.exports)module.exports=api;else root.SteelMindDefaults=api;})(globalThis,function(){
const CONFIG={"profile": "teaching-frame-v1", "project_name": "钢框架教学示例", "geometry": {"bays_x": 1, "bays_z": 1, "stories": 1, "base_support": "fixed"}, "loads": {"dead": 5, "live": 2, "wind": 0, "seismic": 0, "unit": "kN/m"}, "material": {"steel_grade": "Q355", "E_MPa": 206000}, "model_sections": {"beam_section": "H400x300x10x16", "column_section": "H350x350x12x19"}, "candidate_sections": {"beam": ["H400x300x10x16"], "column": ["H350x350x12x19", "H400x400x13x21"]}, "max_iterations": 8, "target_utilization": 0.85, "arrays": {"geometry.bay_widths_x_m": ["bays_x", 6], "geometry.bay_widths_z_m": ["bays_z", 6], "geometry.story_heights_m": ["stories", 3], "loads.q_by_story_kN_per_m": ["stories", 10], "loads.q_z_by_story_kN_per_m": ["stories", 5], "loads.lateral_x_by_story_kN": ["stories", 5], "loads.lateral_z_by_story_kN": ["stories", 2]}};
function blank(v){return v==null||typeof v==='string'&&!v.trim()||Array.isArray(v)&&!v.length}
function apply(payload){
 const r=structuredClone(payload),audit=(r.default_assumptions||[]).filter(a=>JSON.stringify(a.value)===JSON.stringify(a.path.split('.').reduce((v,k)=>v?.[k],r)));const record=(path,value,reason)=>{for(let i=audit.length-1;i>=0;i--)if(audit[i].path===path)audit.splice(i,1);audit.push({path,value:structuredClone(value),reason,profile:CONFIG.profile})};
 for(const name of ['geometry','loads','material','model_sections','candidate_sections']){if(blank(r[name]))r[name]={};if(typeof r[name]!=='object'||Array.isArray(r[name]))throw Error(name+' 必须为参数对象')}
 const g=r.geometry,l=r.loads;
 for(const [block,key,old] of [[g,'bays_x','bays'],[g,'bay_widths_x_m','bay_widths_m'],[l,'lateral_x_by_story_kN','lateral_by_story_kN'],[l,'q_z_by_story_kN_per_m','q_by_story_z_kN_per_m']])if(blank(block[key])&&!blank(block[old]))block[key]=structuredClone(block[old]);
 for(const group of ['geometry','loads','material','model_sections','candidate_sections'])for(const [key,value] of Object.entries(CONFIG[group]))if(blank(r[group][key])){r[group][key]=structuredClone(value);record(group+'.'+key,value,'未填写，采用教学默认值')}
 for(const key of ['project_name','max_iterations','target_utilization'])if(blank(r[key])){r[key]=CONFIG[key];record(key,r[key],'未填写，采用教学默认值')}
 for(const [path,[countKey,fallback]] of Object.entries(CONFIG.arrays)){
  const [group,key]=path.split('.'),n=Number(g[countKey]);if(typeof g[countKey]==='boolean'||!Number.isInteger(n)||n<1||n>30)continue;
  let value=r[group][key],d=fallback;
  if(blank(value)&&group==='geometry'){const legacy=key==='story_heights_m'?'height_m':key==='bay_widths_x_m'?'bay_m':'bay_depth_m';if(!blank(g[legacy]))d=g[legacy]}
  if(blank(value)){r[group][key]=Array(n).fill(d);record(path,r[group][key],'未填写，按层数/跨数采用默认均布值')}
  else if(Array.isArray(value)&&value.length===1&&n>1){r[group][key]=Array(n).fill(value[0]);record(path,r[group][key],'仅填一个值，明确按各层/各跨相同展开')}
 }
 for(const role of ['beam','column']){if(r.sections){r.sections[role]??={};if(blank(r.sections[role].name)){r.sections[role].name=r.model_sections[role+'_section'];record('sections.'+role+'.name',r.sections[role].name,'未填写，采用初始截面')}}const names=r.candidate_sections[role],initial=r.model_sections[role+'_section'];if(Array.isArray(names)&&!names.includes(initial)&&audit.some(a=>a.path==='candidate_sections.'+role)){r.candidate_sections[role]=[initial];record('candidate_sections.'+role,[initial],'默认候选采用用户初始截面，不擅自调整其大小')}}
 r.default_assumptions=audit;r.default_profile=CONFIG.profile;return r;
}
return {apply,config:CONFIG};

});
