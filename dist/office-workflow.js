(function(root){'use strict';
async function readEvents(response,onEvent){
 if(!response.ok){let d;try{d=await response.json()}catch{}throw Error(typeof d?.detail==='string'?d.detail:JSON.stringify(d?.detail||'HTTP '+response.status))}
 if(!response.body)throw Error('事件流不可读');const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='',result;
 function consume(chunk){const data=chunk.split(/\r?\n/).filter(l=>l.startsWith('data:')).map(l=>l.slice(5).trim()).join('\n');if(!data)return;const event=JSON.parse(data);onEvent?.(event);if(event.type==='workflow_completed')result=event.result;if(event.type==='workflow_error')throw Error(event.message||'运行失败')}
 while(true){const {done,value}=await reader.read();buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});const chunks=buffer.split(/\r?\n\r?\n/);buffer=chunks.pop()||'';for(const c of chunks)consume(c);if(done){if(buffer.trim())consume(buffer);break}}
 if(!result)throw Error('办公楼分析事件流提前结束');return result;
}
function createOfficeClient(o){
 let saved=null,epoch=0,pending=null;const key=()=>JSON.stringify([epoch,o.getBundle(),o.getOptions?.()||{}]);const base=()=>o.gateway().replace(/\/$/,'');const request=(url,options)=> (o.fetch||root.fetch.bind(root))(url,options);
 function state(){return {bundle:o.getBundle(),result:saved?.key===key()?saved.result:null}}
 async function analyze({signal}={}){
  if(!o.getBundle())throw Error('请先载入办公楼课程案例');if(state().result)return state().result;const start=key();if(pending)throw Error('办公楼分析正在运行');
  pending=true;try{const response=await request(base()+'/workflow/office-design/run-stream',{method:'POST',headers:{'Content-Type':'application/json'},signal,body:JSON.stringify({payload:{bundle:o.getBundle(),options:o.getOptions?.()||{}}})});const result=await readEvents(response,event=>{if(key()===start)o.onEvent?.(event)});if(key()!==start)throw Error('案例输入已改变，旧结果已丢弃');if(result.ok!==true)throw Error((result.errors||[result.status]).join('；'));saved={key:start,result};return result}finally{pending=false}
 }
 async function generate({signal}={}){const result=await analyze({signal});const start=key();const response=await request(base()+'/workflow/office-design/outputs',{method:'POST',headers:{'Content-Type':'application/json'},signal,body:JSON.stringify({payload:{run_id:result.run_id}})});const pkg=await response.json();if(!response.ok||!pkg.ok)throw Error(typeof pkg.detail==='string'?pkg.detail:'成果接口 HTTP '+response.status);if(start!==key())throw Error('案例已改变，旧成果不会载入');return pkg}
 return {state,analyze,generate,results:async(args={})=>{const r=state().result;if(!r)throw Error('请先分析办公楼案例');if(!args.member_id)return r;const response=await request(base()+'/workflow/office-design/runs/'+encodeURIComponent(r.run_id)+'/members/'+encodeURIComponent(args.member_id));const value=await response.json();if(!response.ok)throw Error(value.detail||'构件不存在');return value},invalidate:()=>{saved=null;epoch++},viewer:async(caseId='G')=>{const r=state().result;if(!r)throw Error('请先运行办公楼分析');const response=await request(base()+'/workflow/office-design/runs/'+encodeURIComponent(r.run_id)+'/viewer/'+encodeURIComponent(caseId));const value=await response.json();if(!response.ok)throw Error(value.detail||'工况图读取失败');return value}};
}
const api={readEvents,createOfficeClient};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.SteelMindOffice=api;
})(typeof window!=='undefined'?window:globalThis);
