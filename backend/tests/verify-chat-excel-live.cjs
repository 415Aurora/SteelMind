/* Run against a locally started gateway. Provider tool decisions are simulated;
   all engineering computation, generation and downloads use the real API. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {createExcelSession,runChatAgent}=require('../../dist/chat-tools.js');
const gateway=process.env.STEEL_CHAT_TEST_GATEWAY||'http://127.0.0.1:8000';
const tables=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../examples/longyan-selfweight/input.json'),'utf8'));
let analysis,turn=0,requests=[];
const api=createExcelSession({getTables:()=>tables,getSessionId:()=> 'live-verification',gateway,onAnalysis:r=>analysis=r});
(async()=>{
 const output=await runChatAgent({modelBase:'https://simulated-provider.invalid',model:'simulated-tool-provider',token:'NOT-A-REAL-KEY',gateway,messages:[{role:'user',content:'分析上传的Excel，查看第一根构件的验算，并生成计算书和图纸'}],excelSession:api,fetch:async(url,o)=>{
  if(url.startsWith('https://simulated-provider.invalid')){
   const names=['analyze_excel_model','get_excel_results','generate_engineering_package'];const name=names[turn++];
   return Response.json({choices:[{message:name?{tool_calls:[{id:'actual-'+turn,type:'function',function:{name,arguments:name==='get_excel_results'?JSON.stringify({member_id:tables.Members[0].member_id}):'{}'}}]}:{content:'实际工具已返回结果。'}}]});
  }
  assert(!o.headers?.Authorization,'Model API credential must not reach gateway');requests.push(url);return fetch(url,o);
 }});
 assert.equal(analysis?.ok,true);assert.equal(analysis.analysis.members.length,tables.Members.length);
 assert.equal(output.outputs[1].member.member_id,tables.Members[0].member_id);
 const pkg=output.outputs.at(-1);assert(pkg.ok,JSON.stringify(pkg));assert.equal(pkg.draft,true);assert.equal(pkg.upstream_check_summary,analysis.upstream_check_summary);
 for(const ext of ['docx','pdf','xlsx','dxf'])assert(pkg.artifacts.some(a=>a.name.endsWith('.'+ext)),ext+' missing');
 assert(pkg.artifacts.some(a=>a.preview_mode==='planar'));
 const verified=[];
 for(const a of pkg.artifacts){const r=await fetch(a.url);assert.equal(r.status,200,a.name);const data=Buffer.from(await r.arrayBuffer());assert.equal(data.length,a.bytes,a.name);assert.equal(crypto.createHash('sha256').update(data).digest('hex'),a.sha256,a.name);verified.push(a.name)}
 const record={provider:'simulated tool-calling provider; no real LLM API tested',backend:'real local HTTP gateway',input_sha256:analysis.input_sha256,nodes:analysis.analysis.nodes.length,members:analysis.analysis.members.length,summary:analysis.code_checks.summary,upstream_check_summary:pkg.upstream_check_summary,generation_status:pkg.status,download_sha256_verified:verified.length,files:verified};
 if(process.env.STEEL_CHAT_TEST_RECORD)fs.writeFileSync(process.env.STEEL_CHAT_TEST_RECORD,JSON.stringify(record,null,2));console.log(JSON.stringify(record,null,2));
})().catch(e=>{console.error(e);process.exit(1)});
