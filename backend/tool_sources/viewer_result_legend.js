// Legend and rendering share the same range; missing values are never zero.
function hasResult(v){return v!==null&&v!==undefined&&v!==''&&Number.isFinite(Number(v))}
function legendNumber(v){return Number(v).toLocaleString('zh-CN',{maximumSignificantDigits:5})}
function forceLegendRange(){const values=Object.values(M.member_checks||{}).map(r=>r.demands?.[forceMode]).filter(hasResult).map(Number);return {count:values.length,min:values.length?Math.min(...values):null,max:values.length?Math.max(...values):null,magnitudeMax:values.length?Math.max(...values.map(Math.abs)):null}}
function updateLegend(){
 const box=document.getElementById('legend'),bar='<div style="height:7px;margin:7px 0;background:linear-gradient(90deg,#3b82f6,#facc15,#ef4444)"></div>';
 if(renderMode==='force'){
  const r=forceLegendRange(),labels={N_kn:'轴力 N',Mx_kNm:'弯矩 Mx',My_kNm:'局部弯矩 My',Mz_kNm:'局部弯矩 Mz',Vy_kn:'局部剪力 Vy',Vz_kn:'局部剪力 Vz',V_kn:'剪力 V',T_kNm:'扭矩 T'},unit=forceMode.endsWith('_kNm')?'kN·m':'kN';
  box.innerHTML='<b>'+(labels[forceMode]||forceMode)+'</b><div>'+(M.analysis_scope==='self_weight'?'工况 1.0G · 框架自重':'当前载入分析结果')+'</div>';
  if(!r.count){box.innerHTML+='<div>无可用数据 · 灰色</div>';return}
  box.innerHTML+='<div>有符号控制值：'+legendNumber(r.min)+' ～ '+legendNumber(r.max)+' '+unit+'</div>';
  box.innerHTML+=r.magnitudeMax===0?'<div style="color:#3b82f6">全部为 0 '+unit+'</div>':bar+'<div>颜色按绝对值 / '+unit+'</div><div style="display:flex;justify-content:space-between;gap:14px"><span>0</span><span>'+legendNumber(r.magnitudeMax/2)+'</span><span>'+legendNumber(r.magnitudeMax)+'</span></div>';
  box.innerHTML+='<div>构件控制值着色，非沿杆内力图</div>';return;
 }
 if(renderMode==='utilization'){const values=Object.values(M.member_utilizations||{}).filter(hasResult).map(Number);box.innerHTML='<b>已实施验算项最大利用率</b>'+bar+'<div>色标 0　　0.575　　1.15</div><div>1.0 为限值参考；超色标上限按红色</div><div>'+(values.length?'实际范围 '+legendNumber(Math.min(...values))+' ～ '+legendNumber(Math.max(...values)):'无可用数据 · 灰色')+'</div><div>未覆盖项不参与，不能代表完整规范通过</div>';return}
 if(renderMode==='deformed'){const s=M.deformation_summary||{},nodes=M.node_displacements||[];box.innerHTML='<b>变形显示 '+document.getElementById('deformScale').value+'×</b><div>'+(nodes.length?'已载入 '+nodes.length+' 个节点位移':'尚未载入位移结果')+'</div>';if(hasResult(s.max_node_displacement_mm))box.innerHTML+='<div>节点最大总位移 '+legendNumber(s.max_node_displacement_mm)+' mm</div>';if(hasResult(s.max_beam_relative_deflection_mm))box.innerHTML+='<div>梁最大相对挠度 '+legendNumber(s.max_beam_relative_deflection_mm)+' mm</div>';box.innerHTML+='<div>'+(M.deformation_curves?'分段连续位移场取样绘制；图形已放大':'节点连线示意；图形已放大')+'</div><div>图中放大不改变上述实际数值</div>';return}
 const statuses=Object.values(M.member_statuses||{}),fail=statuses.filter(s=>s===false).length,pass=statuses.filter(s=>s===true).length,pending=Object.keys(M.member_checks||{}).length-fail-pass;
 box.innerHTML='<b>构件验算状态</b><div style="color:#f2a94b">● 待完成 '+pending+'</div><div style="color:#ff5c67">● 未通过 '+fail+'</div><div style="color:#44dec5">● 已提交项通过 '+pass+'</div><div>待完成项详见点击后的补充指引</div>';
}
function resultHeat(value,max){if(max<=0)return '#3b82f6';const t=Math.min(1,Math.max(0,Math.abs(value)/max)),stops=[[59,130,246],[250,204,21],[239,68,68]],s=t<.5?0:1,u=t<.5?t*2:(t-.5)*2;return 'rgb('+stops[s].map((a,i)=>Math.round(a+(stops[s+1][i]-a)*u)).join(',')+')'}
function resultMemberColor(item,status,baseColor){if(renderMode==='force'){const v=M.member_checks?.[item.checkId]?.demands?.[forceMode];if(!hasResult(v))return '#7b8994';const r=forceLegendRange();return resultHeat(Number(v),r.magnitudeMax)}if(renderMode==='utilization'){const v=M.member_utilizations?.[item.checkId];return hasResult(v)?resultHeat(Number(v),1.15):'#7b8994'}if(renderMode==='status'){if(status===false)return '#ff5c67';if(status===true)return '#44dec5';if(M.analysis_scope==='self_weight')return '#f2a94b'}return baseColor}
const scaleInput=document.getElementById('deformScale');scaleInput.oninput=e=>{document.getElementById('deformScaleValue').textContent=e.target.value+'×';updateLegend();draw()};
updateLegend();

const legendCsvLoader=applyValidationCsv;applyValidationCsv=function(text){legendCsvLoader(text);updateLegend()};
