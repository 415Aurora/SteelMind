const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync(new URL('../tool_sources/viewer_result_legend.js',`file://${__filename}`),'utf8');
const elements={legend:{},deformScale:{value:'20'}},ctx={M:{member_checks:{a:{demands:{N_kn:-12}},b:{demands:{N_kn:4}},c:{demands:{N_kn:null}},d:{demands:{N_kn:0}}},member_statuses:{},member_utilizations:{},node_displacements:[]},renderMode:'force',forceMode:'N_kn',document:{getElementById:id=>elements[id]},applyValidationCsv(){},memberColor(){},heat(){return 'color'},draw(){}};vm.createContext(ctx);vm.runInContext(source,ctx);
assert.equal(vm.runInContext('forceLegendRange().count',ctx),3);assert.equal(vm.runInContext('forceLegendRange().min',ctx),-12);assert.equal(vm.runInContext('forceLegendRange().max',ctx),4);assert(elements.legend.innerHTML.includes('12'));assert(elements.legend.innerHTML.includes('kN'));
ctx.M.member_checks={a:{demands:{N_kn:0}}};vm.runInContext('updateLegend()',ctx);assert(elements.legend.innerHTML.includes('全部为 0'));
ctx.M.member_checks={a:{demands:{N_kn:null}}};vm.runInContext('updateLegend()',ctx);assert(elements.legend.innerHTML.includes('无可用数据'));assert(!elements.legend.innerHTML.includes('NaN'));
console.log('Signed range, magnitude colour scale, zero and missing values are distinct');
