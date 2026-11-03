/* Local engineering-tool bridge. No model code or arbitrary tool names execute. */
(function(root){
'use strict';
const tools=[{type:'function',function:{name:'generate_engineering_package',description:'仅在用户要求生成计算书或图纸时调用。使用当前会话中工作流2已收敛且预检通过的真实报告，生成DOCX/PDF/XLSX/DXF和ZIP。没有报告时返回待补充信息，不猜测参数。',parameters:{type:'object',properties:{},additionalProperties:false}}}];
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
 const toolSummary=()=>outputs.map(r=>r.ok===true?`工程成果状态：${r.status}；${r.draft?'草稿，保留缺项和限制':'请核对适用范围'}。\n`+(r.artifacts||[]).map(a=>`[${a.name}](${a.url})`).join('\n'):`工程文件未生成：${r.error||r.status}`).join('\n\n');
 for(let turn=0;turn<4;turn++){
  const response=await request(o.modelBase.replace(/\/$/,'')+'/chat/completions',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+o.token},signal:o.signal,body:JSON.stringify({model:o.model,stream:true,messages,tools,tool_choice:turn===3?'none':'auto'})});
  const message=await readModel(response,text=>{answer=text;emit()});answer=message.content||'';
  if(!message.tool_calls.length){answer=[answer,toolSummary()].filter(Boolean).join('\n\n');emit();return {text:answer,outputs}}
  if(turn===3)break;
  messages.push(message);
  for(const call of message.tool_calls){
   if(o.signal?.aborted)throw new DOMException('已停止','AbortError');
   let result;
   try{
    if(!call.id||call.function.name!=='generate_engineering_package')throw Error('不支持的工程工具');
    const args=JSON.parse(call.function.arguments||'{}');if(!args||Array.isArray(args)||typeof args!=='object'||Object.keys(args).length)throw Error('成果工具不接受模型自拟的参数或报告');
    const report=o.getReport?.();
    if(!report?.converged||report.status!=='converged'||report.construction_drawing_preflight?.valid!==true)throw Error((report?.construction_drawing_preflight?.draft_reasons||[]).join('；')||'请先在工作流2完成真实分析和截面迭代，并通过成果输入预检，再生成计算书或图纸。');
    if(cached)result=cached;
    else{
     o.onStatus?.('正在执行工程成果工具…');
     const r=await request(o.gateway.replace(/\/$/,'')+'/workflow/engineering-outputs/run-stream',{method:'POST',headers:{'Content-Type':'application/json'},signal:o.signal,body:JSON.stringify({payload:{final_report:report}})});
     if(!r.ok)throw Error(`工具网关 HTTP ${r.status}`);
     const copy=o.onExportResponse?r.clone():null;const text=await r.text();let final=null;
     for(const chunk of text.split(/\r?\n\r?\n/)){const data=chunk.split(/\r?\n/).filter(x=>x.startsWith('data:')).map(x=>x.slice(5).trim()).join('\n');if(!data)continue;const event=JSON.parse(data);if(event.type==='workflow_error')throw Error(event.message||'成果执行失败');if(event.type==='workflow_completed')final=event.result}
     if(!final)throw Error('成果事件流提前结束，没有完成结果');
     if(final.ok!==true)throw Error((final.errors||[final.status||'生成失败']).map(x=>typeof x==='string'?x:JSON.stringify(x)).join('; '));
     const pkg=final.artifacts?.engineering_package;const artifacts=(pkg?.artifacts||[]).filter(a=>a&&typeof a.url==='string'&&/^https?:\/\//.test(a.url));
     if(!artifacts.length)throw Error('成果工具没有返回可下载文件');
     result=cached={ok:true,status:final.status,draft:pkg.draft,upstream_check_summary:pkg.upstream_check_summary,warnings:pkg.warnings,artifacts};
     if(copy)await o.onExportResponse(copy);
    }
   }catch(e){if(e.name==='AbortError')throw e;result={ok:false,error:e.message}}
   outputs.push(result);messages.push({role:'tool',tool_call_id:call.id||'invalid',content:JSON.stringify(result)});
  }
 }
 answer=[answer,'工具调用已达到本轮上限。',toolSummary()].filter(Boolean).join('\n\n');emit();return {text:answer,outputs};
}
const api={runChatAgent};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.SteelMindAgent=api;
})(typeof window!=='undefined'?window:globalThis);
