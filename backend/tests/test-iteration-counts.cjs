// Regression: the actual workflow-2 button must accept the X/Z geometry schema.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(new URL('../../dist/index.html',`file://${__filename}`),'utf8');
const reader=source.slice(source.indexOf('function setParamPath('),source.indexOf('function renderToolParameterTable('));
const handler=source.split('\n').find(line=>line.startsWith("$('#runSectionIteration').onclick="));
async function submit(geometry,inputs=[]){
 const payload={geometry,candidate_sections:{beam:['HN400x200'],column:['HW250x250']},model_sections:{beam_section:'HN400x200',column_section:'HW250x250'}};
 const nodes={'#iterationParams':{querySelectorAll:()=>inputs},'#toolBase':{value:'http://localhost:8000'},'#runSectionIteration':{disabled:false},'#iterationStatus':{},'#iterationTrace':{},'#iterationResult':{},'#iterationArtifacts':{replaceChildren(){}}};
 let sent=null,consumed=false;
 const ctx={structuredClone,sectionIterationDraft:payload,$:key=>nodes[key],gatewayError:e=>e.message,fetch:async(url,options)=>{sent=JSON.parse(options.body);return {ok:true}},consumeSectionIteration:async()=>{consumed=true}};
 vm.createContext(ctx);vm.runInContext(reader+'\n'+handler,ctx);await nodes['#runSectionIteration'].onclick();
 return {sent,consumed,status:nodes['#iterationStatus'].textContent,disabled:nodes['#runSectionIteration'].disabled};
}
(async()=>{
 const current=await submit({bays_x:2,bays_z:1,stories:3},[{dataset:{path:'geometry.bays_x',kind:'number'},value:'2'}]);
 assert(current.sent,'Valid 3D integer counts must reach workflow 2; got '+current.status);
 assert.equal(current.sent.payload.geometry.bays_x,2);assert(current.consumed);assert.equal(current.disabled,false);
 assert((await submit({bays:2,stories:3})).sent,'Legacy bays remains supported');
 // New schema takes precedence if a session still contains the old bays field.
 assert((await submit({bays_x:2,bays_z:1,bays:1.5,stories:3})).sent);
 for(const [key,value] of [['bays_x',1.5],['bays_z',0],['stories',31],['bays_x',true],['stories','']]){
  const result=await submit({bays_x:2,bays_z:1,stories:3,[key]:value});
  assert.equal(result.sent,null,'Invalid '+key+' must not reach analysis');assert(result.status.includes(key),'Error must identify '+key+': '+result.status);
 }
 console.log('Workflow-2 submit accepts X/Z integer counts and legacy bays; rejects invalid counts with field-specific errors');
})().catch(e=>{console.error(e);process.exit(1)});
