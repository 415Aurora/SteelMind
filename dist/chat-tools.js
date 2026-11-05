/* Local engineering-tool bridge. No model code or arbitrary tool names execute. */
(function(root){
'use strict';
const noArgs={type:'object',properties:{},additionalProperties:false};
const tools=[
 {type:'function',function:{name:'analyze_office_case',description:'仅当前已载入办公楼完整荷载课程案例时使用，执行G/Q/W/水平地震及验算。不得将任意上传Excel静默替换为此案例。',parameters:noArgs}},
 {type:'function',function:{name:'get_office_results',description:'读取当前办公楼完整荷载运行汇总或指定物理构件验算记录，未分析先调用analyze_office_case。',parameters:{type:'object',properties:{member_id:{type:'string'}},additionalProperties:false}}},
 {type:'function',function:{name:'analyze_excel_model',description:'对当前会话上传的Excel原始节点和杆件执行实际自重分析及已实现的验算。不会修改模型或补造其他荷载。用户要求分析Excel时调用。',parameters:noArgs}},
 {type:'function',function:{name:'get_excel_results',description:'读取当前Excel实际分析结果、控制构件、位移及缺项。可用member_id查询一根原始构件的全部验算。尚未分析时先调用analyze_excel_model。',parameters:{type:'object',properties:{member_id:{type:'string',description:'原始构件编号，可省略以查询汇总'}},additionalProperties:false}}},
 {type:'function',function:{name:'generate_engineering_package',description:'用户要求计算书或图纸时调用。Excel使用当前上传原模型，必要时先实际分析，保留FAIL/缺项并生成草稿；规则框架使用真实收敛报告。返回真实下载链接。',parameters:noArgs}}
];
function canonical(value){if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';return JSON.stringify(value)}
function createExcelSession(o){
 let saved=null,pending=null,epoch=0;
 const key=()=>canonical([epoch,o.getSessionId?.()||'',o.getTables?.()||null]);
 function state(){const tables=o.getTables?.();return {tables:tables||null,contextKey:key(),result:saved?.key===key()?saved.result:null}}
 function waitForCaller(promise,signal){
  if(!signal)return promise;
  if(signal.aborted)return Promise.reject(new DOMException('已停止','AbortError'));
  return new Promise((resolve,reject)=>{const abort=()=>{cleanup();reject(new DOMException('已停止','AbortError'))};const cleanup=()=>signal.removeEventListener('abort',abort);signal.addEventListener('abort',abort,{once:true});promise.then(value=>{cleanup();resolve(value)},error=>{cleanup();reject(error)})});
 }
 async function analyze({signal,force=false}={}){
  if(signal?.aborted)throw new DOMException('已停止','AbortError');
  const current=state();if(!current.tables)throw Error('请先上传Excel模型');
  const start=key();if(!force&&current.result)return summary(current.result);
  if(pending){if(pending.key!==start)throw Error('另一个Excel分析正在完成，请稍后重试');return waitForCaller(pending.promise,signal)}
  const snapshot=JSON.parse(JSON.stringify(current.tables));saved=null;
  const work=(async()=>{
   const gateway=typeof o.gateway==='function'?o.gateway():o.gateway;
   const response=await (o.fetch||root.fetch.bind(root))(gateway.replace(/\/$/,'')+'/workflow/explicit-model/run',{method:'POST',headers:{'Content-Type':'application/json'},signal,body:JSON.stringify({payload:{tables:snapshot}})});
   const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Excel接口 HTTP '+response.status);
   if(start!==key())throw Error('Excel或会话已改变，本次旧分析结果已丢弃，请重新分析');
   if(result.ok!==true)throw Error((result.errors||['Excel分析失败']).join('；'));
   if(!result.input_sha256||!result.analysis||!result.code_checks)throw Error('Excel分析返回不完整，未保存为可导出结果');
   const isCurrent=()=>start===key();saved={key:start,result};await o.onAnalysis?.(result,isCurrent);if(!isCurrent())throw Error('Excel或会话已改变，本次旧分析结果已丢弃，请重新分析');return summary(result);
  })();pending={key:start,promise:work};try{return await work}finally{pending=null}
 }
 function summary(r){const checks=r.code_checks||{};const ranked=[...(checks.members||[])].sort((a,b)=>Math.max(0,...b.checks.map(c=>Number(c.utilization)||0))-Math.max(0,...a.checks.map(c=>Number(c.utilization)||0)));return {ok:true,operation:'excel_analysis',status:r.status||'analysis_completed',input_sha256:r.input_sha256,scope:r.notice||'仅框架自重',upstream_check_summary:r.upstream_check_summary,summary:checks.summary,weight_kN:r.analysis.weight_kN,nodes:r.analysis.nodes.length,members:r.analysis.members.length,max_node_displacement_mm:Math.max(0,...r.analysis.nodes.map(n=>Math.hypot(...n.displacement_mm_rad.slice(0,3)))),controlling_members:ranked.slice(0,5).map(m=>({member_id:m.member_id,section_id:m.section_id,status:m.status,checks:m.checks})),project_pending:checks.project_pending||[],artifacts:r.artifacts||[]}}
 async function results(args={}){const r=state().result;if(!r)throw Error('请先分析当前Excel模型');const out=summary(r);out.operation='excel_results';if(args.member_id){const member=r.code_checks.members.find(m=>m.member_id===args.member_id);if(!member)throw Error('本次结果中没有构件 '+args.member_id);out.member=member}return out}
 return {state,analyze,results,invalidate:()=>{saved=null;epoch++}};
}
async function readModel(response,onText){
 if(!response.ok){let detail;try{const e=await response.json();detail=e.error?.message||e.detail}catch{}throw Error(`模型请求失败 HTTP ${response.status}：${detail||'请确认模型支持工具调用；也可使用工程文件输出按钮。'}`)}
 let content='',calls=new Map();
 function ingest(event){const choice=event.choices?.[0];const delta=choice?.delta||choice?.message||{};if(typeof delta.content==='string'){content+=delta.content;onText?.(content)}
  for(const call of delta.tool_calls||[]){const index=call.index??calls.size;let old=calls.get(index)||{id:'',type:'function',function:{name:'',arguments:''}};if(call.id)old.id=call.id;old.function.name+=call.function?.name||'';old.function.arguments+=call.function?.arguments||'';calls.set(index,old)}
 }
 if((response.headers.get('content-type')||'').includes('application/json'))ingest(await response.json());
 else{
  if(!response.body)throw Error('模型未提供响应体');const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
  function consume(chunk){const data=chunk.split(/\r?\n/).filter(x=>x.startsWith('data:')).map(x=>x.slice(5).trim()).join('\n');if(data&&data!=='[DONE]')ingest(JSON.parse(data))}
  while(true){const {done,value}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});const parts=buffer.split(/\r?\n\r?\n/);buffer=parts.pop()||'';for(const p of parts)consume(p);if(done){if(buffer.trim())consume(buffer);break}}
 }
 return {role:'assistant',content:content||null,tool_calls:[...calls.values()]};
}
async function runChatAgent(o){
 const request=o.fetch||root.fetch.bind(root);const messages=o.messages.map(m=>({...m}));const outputs=[];let cached=null;let answer='';
 const emit=()=>o.onText?.(answer);
 const toolSummary=()=>outputs.map(r=>r.ok!==true?`操作未完成：${r.error||r.status}`:((r.operation==='office_analysis'||r.operation==='excel_analysis'||r.operation==='excel_results')?`${r.operation==='office_analysis'?'办公楼':r.operation==='excel_analysis'?'Excel分析':'Excel结果'}：${r.status}；验算汇总 ${r.upstream_check_summary}；范围：${r.scope}。\n`:`工程成果状态：${r.status}；${r.draft?'草稿，保留缺项和限制':'请核对适用范围'}。\n`)+(r.artifacts||[]).map(a=>`[${a.name}](${a.url})`).join('\n')).join('\n\n');
 for(let turn=0;turn<8;turn++){
  const response=await request(o.modelBase.replace(/\/$/,'')+'/chat/completions',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+o.token},signal:o.signal,body:JSON.stringify({model:o.model,stream:true,messages,tools,tool_choice:turn===7?'none':'auto'})});
  const message=await readModel(response,text=>{answer=text;emit()});answer=message.content||'';
  if(!message.tool_calls.length){answer=[answer,toolSummary()].filter(Boolean).join('\n\n');emit();return {text:answer,outputs}}
  if(turn===7)break;
  messages.push(message);
  for(const call of message.tool_calls){
   if(o.signal?.aborted)throw new DOMException('已停止','AbortError');
   let result;
   try{
    const name=call.function.name;if(!call.id||!tools.some(t=>t.function.name===name))throw Error('不支持的工程工具');
    const args=JSON.parse(call.function.arguments||'{}');if(!args||Array.isArray(args)||typeof args!=='object'||Object.keys(args).some(k=>!['get_excel_results','get_office_results'].includes(name)||k!=='member_id')||(args.member_id!==undefined&&typeof args.member_id!=='string'))throw Error('工具不接受模型自拟的输入或报告');
    if(name==='analyze_office_case'||name==='get_office_results'||(name==='generate_engineering_package'&&o.officeSession?.state().bundle)){
     if(!o.officeSession?.state().bundle)throw Error('请先明确载入办公楼完整荷载课程案例，不替换Excel原模型');
     const value=name==='generate_engineering_package'?await o.officeSession.generate({signal:o.signal}):name==='analyze_office_case'?await o.officeSession.analyze({signal:o.signal}):await o.officeSession.results(args);
     result={...value,operation:name==='generate_engineering_package'?'office_exports':'office_analysis',status:value.status||'analysis_completed',scope:value.scope||'办公楼G/Q/W/水平地震，构造性能另交接',upstream_check_summary:value.upstream_check_summary||value.design_status};
     outputs.push(result);messages.push({role:'tool',tool_call_id:call.id,content:JSON.stringify(result)});continue;
    }
    if(name==='analyze_excel_model'||name==='get_excel_results'){
     if(!o.excelSession)throw Error('请先上传Excel模型');
     o.onStatus?.(name==='analyze_excel_model'?'正在分析Excel原始杆系…':'正在读取本次Excel验算结果…');
     result=name==='analyze_excel_model'?await o.excelSession.analyze({signal:o.signal}):await o.excelSession.results(args);
     outputs.push(result);messages.push({role:'tool',tool_call_id:call.id,content:JSON.stringify(result)});continue;
    }
    let payload;const excel=o.excelSession?.state();const exportKey=excel?.tables?excel.contextKey:canonical(o.getReport?.()||null);
    if(excel?.tables){await o.excelSession.analyze({signal:o.signal});const current=o.excelSession.state();if(current.contextKey!==exportKey||!current.result)throw Error('Excel已改变，请重新分析');payload={explicit_tables:current.tables}}
    else{const report=o.getReport?.();if(!report?.converged||report.status!=='converged'||report.construction_drawing_preflight?.valid!==true)throw Error((report?.construction_drawing_preflight?.draft_reasons||[]).join('；')||'请先在工作流2完成真实分析和截面迭代，并通过成果输入预检，再生成计算书或图纸。');payload={final_report:report}}
    if(cached?.key!==exportKey)cached=null;
    if(cached)result=cached.result;
    else{
     o.onStatus?.('正在执行工程成果工具…');
     const r=await request(o.gateway.replace(/\/$/,'')+'/workflow/engineering-outputs/run-stream',{method:'POST',headers:{'Content-Type':'application/json'},signal:o.signal,body:JSON.stringify({payload})});
     if(!r.ok)throw Error(`工具网关 HTTP ${r.status}`);
     const copy=o.onExportResponse?r.clone():null;const text=await r.text();let final=null;
     for(const chunk of text.split(/\r?\n\r?\n/)){const data=chunk.split(/\r?\n/).filter(x=>x.startsWith('data:')).map(x=>x.slice(5).trim()).join('\n');if(!data)continue;const event=JSON.parse(data);if(event.type==='workflow_error')throw Error(event.message||'成果执行失败');if(event.type==='workflow_completed')final=event.result}
     if(!final)throw Error('成果事件流提前结束，没有完成结果');
     if(final.ok!==true)throw Error((final.errors||[final.status||'生成失败']).map(x=>typeof x==='string'?x:JSON.stringify(x)).join('; '));
     const pkg=final.artifacts?.engineering_package;const artifacts=(pkg?.artifacts||[]).filter(a=>a&&typeof a.url==='string'&&/^https?:\/\//.test(a.url));
     if(!artifacts.length)throw Error('成果工具没有返回可下载文件');
     if(excel?.tables&&(o.excelSession.state().contextKey!==exportKey||!o.excelSession.state().result))throw Error('成果生成期间Excel已改变，请重新生成');
     result={ok:true,status:final.status,draft:pkg.draft,upstream_check_summary:pkg.upstream_check_summary,warnings:pkg.warnings,input_sha256:pkg.input_sha256,artifacts};cached={key:exportKey,result};
     if(copy)await o.onExportResponse(copy);
    }
   }catch(e){if(e.name==='AbortError')throw e;result={ok:false,error:e.message}}
   outputs.push(result);messages.push({role:'tool',tool_call_id:call.id||'invalid',content:JSON.stringify(result)});
  }
 }
 answer=[answer,'工具调用已达到本轮上限。',toolSummary()].filter(Boolean).join('\n\n');emit();return {text:answer,outputs};
}
const api={runChatAgent,createExcelSession};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.SteelMindAgent=api;
})(typeof window!=='undefined'?window:globalThis);
