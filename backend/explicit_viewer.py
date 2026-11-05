"""Build a canvas scene from actual workbook nodes and edges, with no generated grid members."""
import html,json,re
from explicit_model import normalize,InputIssue,input_hash
import numpy as np
from numpy.polynomial import polynomial as poly
from explicit_checks import roots_in

def force_envelope(member):
 """Signed component extrema of section forces in local xyz, 1.0G.
 Independent extrema are not a simultaneous force vector at one section.
 """
 result=dict.fromkeys(['N_kn','My_kNm','Mz_kNm','Vy_kn','Vz_kn','T_kNm'],0.)
 ell=member['length_m']*1000/len(member['segment_end_actions_kN_kNm'])
 q=np.array(member['axes'])@np.array([0.,0.,-member['self_weight_kN_m']])
 for F in member['segment_end_actions_kN_kNm']:
  fields={'N_kn':([F[0]*1000,q[0]],1000),'My_kNm':([F[4]*1e6,F[2]*1000,q[2]/2],1e6),'Mz_kNm':([-F[5]*1e6,F[1]*1000,q[1]/2],1e6),'Vy_kn':([F[1]*1000,q[1]],1000),'Vz_kn':([F[2]*1000,q[2]],1000),'T_kNm':([F[3]],1)}
  for key,(coeff,divisor) in fields.items():
   for x in [0.,ell]+roots_in(poly.polyder(coeff),ell):
    value=float(poly.polyval(x,coeff)/divisor)
    if abs(value)>abs(result[key]):result[key]=value
 return result

def deformation_curve(member,analysis,point):
 """Sample the actual elastic displacement field, including released beams."""
 axes=np.array(member['axes']);D=np.array(member['segment_displacements_mm_rad'])[:,:3]@axes.T
 nseg=len(member['segment_end_actions_kN_kNm']);L=member['length_m']*1000;ell=L/nseg
 q=axes@np.array([0.,0.,-member['self_weight_kN_m']]);section=analysis['sections'][member['section_id']];E=analysis['materials'][member['material_id']]['E_MPa']
 origin=next(n['xyz_m'] for n in analysis['nodes'] if n['node_id']==member['i_node']);points=[]
 for k,F in enumerate(member['segment_end_actions_kN_kNm']):
  coefficients=[]
  for axis,I,moment,shear,load in [(1,section['Iz'],-F[5]*1e6,F[1]*1000,q[1]),(2,section['Iy'],F[4]*1e6,F[2]*1000,q[2])]:
   a2=moment/(2*E*I);a3=shear/(6*E*I);a4=load/(24*E*I);a1=(D[k+1,axis]-D[k,axis]-a2*ell**2-a3*ell**3-a4*ell**4)/ell
   coefficients.append([D[k,axis],a1,a2,a3,a4])
  for j in range(9):
   if k and j==0:continue
   x=ell*j/8;station=k*ell+x;a2=-q[0]/(2*E*section['A']);a1=(D[k+1,0]-D[k,0]-a2*ell**2)/ell
   u=np.array([D[k,0]+a1*x+a2*x*x,poly.polyval(x,coefficients[0]),poly.polyval(x,coefficients[1])])@axes
   if j in (0,8):u=np.array(member['segment_displacements_mm_rad'][k+(j==8)][:3])
   points.append({'point':point(np.array(origin)+axes[0]*station/1000),'u_mm':[float(u[0]),float(u[2]),float(-u[1])]})
 return points

def build_scene(tables,result=None):
 model,errors=normalize(tables)
 if errors:raise InputIssue('；'.join(errors))
 raw=list(model['nodes'].values());xmin=min(n['xyz'][0] for n in raw);ymax=max(n['xyz'][1] for n in raw);zmin=min(n['xyz'][2] for n in raw)
 def point(xyz):return [xyz[0]-xmin,xyz[2]-zmin,ymax-xyz[1]]
 nodes=[{'id':nid,'point':point(n['xyz']),'source_xyz_m':n['xyz']} for nid,n in model['nodes'].items()];lookup={n['id']:n for n in nodes};members=[];shapes={};checks={}
 for mid,m in model['members'].items():
  section=model['sections'][m['section_id']];material=model['materials'][m['material_id']];kind='column' if 'column' in str(m.get('member_type')) else 'beam'
  members.append({'id':mid,'checkId':mid,'kind':kind,'pair':[lookup[m['i_node']]['point'],lookup[m['j_node']]['point']],'i_node':m['i_node'],'j_node':m['j_node'],'release_i':m['hinge_i'],'release_j':m['hinge_j']})
  shapes[mid]={'name':str(section.get('section_name') or m['section_id']),'shape':str(section['shape']).upper(),'h_mm':float(section['depth_mm']),'b_mm':float(section['width_mm']),'tw_mm':float(section['tw_mm']),'tf_mm':float(section['tf_mm']),'A_mm2':section['A'],'Ix_mm4':section['Iz'],'Iy_mm4':section['Iy'],'root_radius_mm':'未绘制','catalog_standard':'Excel原始属性','catalog_id':m['section_id']}
  checks[mid]={'section':html.escape(shapes[mid]['name']),'steel':html.escape(str(material.get('grade') or '未提供')),'span_m':m['length_m'],'demands':{},'source_nodes':m['i_node']+' → '+m['j_node']}
 statuses={};utilizations={};displacements=[];curves={};deformation_summary={}
 if result is not None:
  if not result.get('ok') or result.get('input_sha256')!=input_hash(tables):raise InputIssue('分析结果与当前输入不一致，请重新运行工作流2')
  records={m['member_id']:m for m in result['analysis']['members']};norms={m['member_id']:m for m in result['code_checks']['members']}
  if set(records)!=set(checks):raise InputIssue('分析构件编号与当前模型不一致')
  for mid,item in checks.items():
   norm=norms[mid];curves[mid]=deformation_curve(records[mid],result['analysis'],point);item['end_displacements_mm']={'i':records[mid]['segment_displacements_mm_rad'][0][:3],'j':records[mid]['segment_displacements_mm_rad'][-1][:3]};item.update(demands=force_envelope(records[mid]),checks=norm['checks'],overall_status=norm['status'],completed_check_status=norm.get('completed_check_status','NOT_CHECKED'),coverage=norm.get('coverage',{}))
   for c in norm['checks']:
    if c['item']=='beam_deflection':item['demands']['deflection_mm']=c.get('demand')
    if c['item']=='section_strength':item['max_stress_N_mm2']=c.get('demand')
   statuses[mid]=False if norm['status']=='FAIL' else True if norm['status']=='PASS' else None
   vals=[c['utilization'] for c in norm['checks'] if c.get('utilization') is not None and c['status'] in ('PASS','FAIL')];
   if vals:utilizations[mid]=max(vals)
  for n in result['analysis']['nodes']:
   xyz=point(n['xyz_m']);u=n['displacement_mm_rad'];displacements.append(dict(zip(['x_m','y_m','z_m','ux_mm','uy_mm','uz_mm'],xyz+[u[0],u[2],-u[1]])))
  deformation_summary={'max_node_displacement_mm':max((float(np.linalg.norm(n['displacement_mm_rad'][:3])) for n in result['analysis']['nodes']),default=0.),'max_beam_relative_deflection_mm':max((v['demands'].get('deflection_mm') or 0 for v in checks.values()),default=0.)}
 unique=lambda k:sorted(set(n['point'][k] for n in nodes))
 axes=[unique(k) for k in range(3)];spans=lambda values:[b-a for a,b in zip(values,values[1:])] or [1]
 return {'explicit_nodes':nodes,'explicit_members':members,'bays_x':len(spans(axes[0])),'bays_z':len(spans(axes[2])),'stories':max(1,len(axes[1])-1),'spans_x_m':spans(axes[0]),'spans_z_m':spans(axes[2]),'story_heights_m':spans(axes[1]),'base_support':'source','beam_name':'逐构件原始截面','column_name':'箱柱等实际截面','steel_grade':'逐构件原材料','member_shapes':shapes,'member_checks':checks,'deformation_curves':curves,'deformation_summary':deformation_summary,'analysis_scope':'self_weight' if result is not None else 'geometry_only','member_statuses':statuses,'member_utilizations':utilizations,'node_displacements':displacements,'member_check_csv_url':'','member_check_csv_text':'','member_check_run_id':''}

def build_html(tables,result=None):
 from tool_sources.opensees_visualize import _build_html
 scene=build_scene(tables,result);document=_build_html(scene)
 def swap(pattern,new):
  nonlocal document
  document,n=re.subn(pattern,lambda _:new,document,count=1,flags=re.S)
  if n!=1:raise ValueError('原始杆系预览模板未匹配：'+pattern[:50])
 swap(r'const nodes=\[\];for\(let j=0;.*?nodes.push\(\[xs\[i\],ys\[j\],zs\[k\]\]\);','const nodes=M.explicit_nodes.map(n=>n.point);')
 swap(r' const columns=\[\],beams=\[\];.*?\n const allMembers='," const columns=M.explicit_members.filter(m=>m.kind==='column'),beams=M.explicit_members.filter(m=>m.kind==='beam');\n const allMembers=")
 document=document.replace('beamCount=M.stories*(M.bays_x*(M.bays_z+1)+M.bays_z*(M.bays_x+1)),columnCount=(M.bays_x+1)*(M.bays_z+1)*M.stories',"beamCount=M.explicit_members.filter(m=>m.kind==='beam').length,columnCount=M.explicit_members.filter(m=>m.kind==='column').length")
 document=document.replace("isBeam=id.startsWith('B')", "isBeam=M.explicit_members.find(m=>m.id===id)?.kind==='beam'")
 document=document.replace("const role=id.startsWith('B')?'梁':'柱'", "const role=M.explicit_members.find(m=>m.id===id)?.kind==='beam'?'梁':'柱'")
 document=document.replace('综合结论：有验算记录，状态未明确','该原始构件尚未执行规范验算')
 document=document.replace('X/Z 双向柱网　·　Y 竖向','Excel原XYZ杆系　·　原Z竖向')
 document=document.replace('SteelMind 双向柱网空间几何视图','Excel原始节点与逐构件截面')
 # Insert at end so no earlier CSV loader can paint unrelated checks onto a new model.
 extra=r'''
const sourceSubtitle=document.getElementById('subtitle');sourceSubtitle.textContent=`Excel原始杆系：${M.explicit_nodes.length}节点 / ${M.explicit_members.length}杆件；Z竖向`;
document.getElementById('support').textContent='支座及释放见原Excel；未作规范验算';
document.querySelector('.notice').textContent='原始杆系几何预览；点击梁柱查看实际截面。未进行规范验算，不显示通过结论。';
document.getElementById('loadValidationCsv').hidden=true;
applyValidationCsv=function(){document.getElementById('csvStatus').textContent='原模型预览保持未验算；不自动套用其他模型CSV';};
applyValidationCsv('');
const sourceSectionDraw=showSectionForMember;
showSectionForMember=function(id,checkId=id){
 const shape=M.member_shapes[checkId],member=M.explicit_members.find(m=>m.id===id);
 if(!shape||!['BOX','RHS','SHS'].includes(shape.shape)){sourceSectionDraw(id,checkId);}
 else{
  const svg=document.getElementById('sectionDrawing');svg.replaceChildren();
  const scale=Math.min(230/shape.b_mm,120/shape.h_mm),w=shape.b_mm*scale,h=shape.h_mm*scale,x=(260-w)/2,y=(150-h)/2,tw=shape.tw_mm*scale,tf=shape.tf_mm*scale;
  const p=document.createElementNS('http://www.w3.org/2000/svg','path');
  p.setAttribute('d',`M${x} ${y}h${w}v${h}h${-w}z M${x+tw} ${y+tf}v${h-2*tf}h${w-2*tw}v${-h+2*tf}z`);p.setAttribute('fill-rule','evenodd');p.setAttribute('fill','#39d0bd');p.setAttribute('stroke','#e8f1f7');svg.append(p);
  document.getElementById('sectionDimensions').textContent=`${shape.name}（箱形原截面，圆角未深化）\nh=${shape.h_mm} b=${shape.b_mm} tw=${shape.tw_mm} tf=${shape.tf_mm} mm\nA=${shape.A_mm2} mm²；Ix=${shape.Ix_mm4}；Iy=${shape.Iy_mm4} mm⁴`;
 }
 const sourceNode=nid=>M.explicit_nodes.find(n=>n.id===nid);
 if(member){const meta=document.getElementById('inspectorMeta'),p=document.createElement('p');p.textContent=`原编号 ${id}；I=${member.i_node} XYZ=${sourceNode(member.i_node).source_xyz_m.join(',')}m；J=${member.j_node} XYZ=${sourceNode(member.j_node).source_xyz_m.join(',')}m；I/J端弯矩释放=${member.release_i}/${member.release_j}`;meta.append(p)}
};
'''
 extra+=r'''
const withAnalysis=M.analysis_scope==='self_weight';
document.getElementById('csvStatus').hidden=true;
document.getElementById('support').textContent='原Excel支座与释放；'+(withAnalysis?'已载入自重分析':'尚未分析');
document.querySelector('.notice').textContent=withAnalysis?'仅框架自重（1.0G），规范验算未闭合。各内力分量的控制位置可能不同。':'几何预览；运行工作流2获取内力与验算。';
document.getElementById('csvStatus').textContent=withAnalysis?'本次自重结果已载入':'尚未分析';
showMember=function(id,checkId=id){
 selectedMember=id;const item=M.member_checks[checkId],member=M.explicit_members.find(m=>m.id===id),panel=document.getElementById('memberInspector'),checks=document.getElementById('inspectorChecks'),meta=document.getElementById('inspectorMeta');
 const f=(v,u)=>v!==null&&v!==undefined&&Number.isFinite(Number(v))?legendNumber(v)+' '+u:(withAnalysis?'不适用或待补充':'尚未分析');
 document.getElementById('inspectorTitle').textContent=id+' · '+(member.kind==='beam'?'梁':'柱');
 const d=item.demands||{};
 meta.textContent=(withAnalysis?'自重分析已完成；'+(item.overall_status==='FAIL'?'有验算未通过':item.overall_status==='PASS'?'本次构件验算通过':'已验项'+(item.completed_check_status==='PASS'?'通过':'待核')+' · 尚有缺项'):'当前仅有几何与截面；请运行工作流2')+'\n截面：'+item.section+'；钢材：'+item.steel+'；长度：'+f(item.span_m,'m')+'\n轴力 N：'+f(d.N_kn,'kN')+'\n局部弯矩 My：'+f(d.My_kNm,'kN·m')+'；Mz：'+f(d.Mz_kNm,'kN·m')+'\n局部剪力 Vy：'+f(d.Vy_kn,'kN')+'；Vz：'+f(d.Vz_kn,'kN')+'\n扭矩 T：'+f(d.T_kNm,'kN·m')+'\n梁相对挠度：'+f(d.deflection_mm,'mm')+'\n承载力验算应力（γ0γG）：'+f(item.max_stress_N_mm2,'MPa')+'\n稳定计算长度：待确认，未用几何长度替代';
 checks.replaceChildren();
 if(!withAnalysis){const p=document.createElement('p');p.textContent='内力由分析计算产生，不从截面尺寸或历史汇总结果推断。';checks.append(p)}
 const labels={section_strength:'截面强度',strong_axis_shear_bound:'强轴抗剪（保守界）',weak_axis_shear_bound:'弱轴抗剪（保守界）',combined_stress_bound:'折算应力（保守界）',beam_deflection:'梁挠度',member_deformation_limit:'整体变形适用性',compression_stability:'压弯稳定',lateral_torsional_stability:'整体/侧扭稳定',flange_width_thickness:'翼缘宽厚比 S4',web_width_thickness:'腹板宽厚比 S4',web_additional_stability:'腹板区格稳定',plate_local_stability:'板件局部稳定汇总',torsion_interaction:'扭转共同作用'};
 const items=item.checks||[],counts={PASS:0,FAIL:0,PENDING:0,NA:0};for(const c of items)counts[c.status]=(counts[c.status]||0)+1;
 const summary=document.createElement('div');summary.className='check-summary';summary.textContent=`单项：通过 ${counts.PASS} · 未通过 ${counts.FAIL} · 待补充 ${counts.PENDING} · 不适用 ${counts.NA}`;checks.append(summary);
 const actions={compression_stability:'你/计算组：确认双向支撑、侧移条件、计算长度及屈曲曲线。程序：还需实现完整压弯稳定判定，当前不会因补值自动变为通过。',lateral_torsional_stability:'你/计算组：确认构件用途、受压翼缘侧向支承位置、无支撑长度及扭转约束。程序：尚需完成适用性和稳定公式。',plate_local_stability:'计算组：按H/箱形截面的应力分布判定板件等级及有效截面。程序：已按实际受力作S4保守筛查；超出筛查门槛需精算有效截面，不能修改名称来消除提示。',member_deformation_limit:'计算组：确认整体变形的比较层、控制条件和限值。柱相对变形不能直接套梁挠度限值；节点位移已计算。',torsion_interaction:'计算组：核对扭矩、翘曲和边界；存在扭矩时需补充共同作用验算。',combined_stress_bound:'保守界超限时需精算；不代表真实应力已超限。'};
 for(const c of [...items].sort((a,b)=>({FAIL:0,PENDING:1,PASS:2,NA:3}[a.status]-{FAIL:0,PENDING:1,PASS:2,NA:3}[b.status]))){
  const card=document.createElement('details'),heading=document.createElement('summary'),badge=document.createElement('span'),text=document.createElement('p');card.className='check-item';card.open=c.status==='FAIL';heading.textContent=labels[c.item]||c.item;badge.textContent=({PASS:'通过',FAIL:'未通过',PENDING:'待补充',NA:'不适用'})[c.status]||'待补充';badge.className=c.status==='PASS'?'check-pass':c.status==='FAIL'?'check-fail':'check-pending';heading.append(badge);
  if(c.utilization!==null&&c.utilization!==undefined){const ratio=document.createElement('small');ratio.textContent=' 利用率 '+legendNumber(c.utilization);heading.append(ratio)}
  text.textContent=[c.substitution,c.reason,c.formula,c.basis].filter(Boolean).join('\n');card.append(heading,text);
  if(c.status==='PENDING'){const todo=document.createElement('p');todo.className='check-action';todo.textContent='如何处理：'+(actions[c.item]||'按本项原因补充适用条件或精算结果，由计算组复核；不能直接改成通过。');card.append(todo)}checks.append(card);
 }
 const guide=document.createElement('details'),title=document.createElement('summary'),body=document.createElement('p');guide.className='check-item pending-guide';title.textContent='待补充项处理指引';body.textContent='① 输入可配置：Design_Controls支持permanent_load_factor（默认1.3）、importance_factor（默认1）、beam_deflection_denominator（默认400），仅按已确认设计条件修改并重算。② 支撑、计算长度、局部稳定等既需专业确认，也有尚未实现的公式；单填Excel不能消除这些待办。③ 已标为不适用的分项保留原因，无需强行补值。风震、完整组合、节点连接/基础不在本次仅自重范围，保留缺项即可。④ 报告保留INCOMPLETE，可导出；不要用0或“通过”替代缺失信息。';guide.append(title,body);checks.append(guide);

 showSectionForMember(id,checkId);panel.classList.add('open');draw();
};
updateLegend();
'''
 document=document.replace('</script>',extra+'\n</script>',1)
 document=document.replace('<option value="Mx_kNm">弯矩 Mx</option>', '<option value="My_kNm">局部弯矩 My</option><option value="Mz_kNm">局部弯矩 Mz</option><option value="Vy_kn">局部剪力 Vy</option><option value="Vz_kn">局部剪力 Vz</option><option value="T_kNm">扭矩 T</option>')
 document=document.replace('forceMode="Mx_kNm"','forceMode="N_kn"')
 document=document.replace('<option value="V_kn">剪力 V</option>','')
 document=document.replace('点击构件查看截面与已有验算数据　·　拖动旋转　·　滚轮缩放　·　Shift/右键拖动平移','点击构件查看结果 · 拖动旋转 · 滚轮缩放')
 document=document.replace("else if(data.type==='steelmind-load-embedded-validation-csv'){", "else if(data.type==='steelmind-load-embedded-validation-csv'){if(M.analysis_scope){document.getElementById('csvStatus').textContent=M.analysis_scope==='self_weight'?'本次自重结果已载入':'运行工作流2获取结果';return;}")
 # Draw member curves through the same scene projection, without applying nodal displacement twice.
 document=document.replace('function project(p){let [px,py,pz]=p;if(renderMode===', 'function project(p,skipDisplacement=false){let [px,py,pz]=p;if(!skipDisplacement&&renderMode===')
 document=document.replace('return{...item,a,b,depth:(a[2]+b[2])/2}', 'const curve=renderMode==="deformed"?(M.deformation_curves?.[item.id]||[]).map(d=>project(d.point.map((v,i)=>v+d.u_mm[i]/1000*Number(document.getElementById("deformScale").value)),true)):[];return{...item,a,b,curve,depth:(a[2]+b[2])/2}')
 a=document.index('function member(item){');b=document.index(' allMembers.forEach(member);',a)
 part=document[a:b]
 part=part.replace('ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);', 'strokeMemberPath(item);').replace('ctx.moveTo(a[0],a[1]-width*.18);ctx.lineTo(b[0],b[1]-width*.18);', 'strokeMemberPath(item,-width*.18);')
 document=document[:a]+' function strokeMemberPath(item,dy=0){const points=item.curve?.length?item.curve:[item.a,item.b];ctx.moveTo(points[0][0],points[0][1]+dy);for(const p of points.slice(1))ctx.lineTo(p[0],p[1]+dy);}' +part+document[b:]
 document=document.replace('function distanceToSegment(px,py,item){', 'function distanceToSegment(px,py,item){if(item.curve?.length){return Math.min(...item.curve.slice(1).map((b,i)=>distanceToSegment(px,py,{a:item.curve[i],b})));}')
 document=document.replace("<span>未通过</span></div>`;","<span>未通过</span></div><div class=stat><b style=color:#f2b85b>${Object.values(M.member_checks||{}).filter(m=>m.overall_status==='INCOMPLETE').length}</b><span>待完成</span></div>`;")
 document=document.replace('梁 · 未验算','梁 · 验算未闭合').replace('柱 · 未验算','柱 · 验算未闭合')
 document=document.replace('</style>', '.check-item summary{cursor:pointer;font-size:12px;line-height:1.8}.check-item summary span{float:right;margin-left:8px}.check-item summary small{display:block;color:#a9c1d0}.check-item[open]{border-color:#63819a}.check-pending{color:#f2b85b}.check-summary{font-size:12px;line-height:1.8;color:#c1d6e4;padding:7px 0}.check-action{border-left:2px solid #f2b85b;padding-left:8px}.legend{max-width:300px;line-height:1.7}.member-meta{white-space:pre-line}.pending-guide{border-color:#947036}</style>',1)
 return scene,document

def publish_viewer(tables,include_analysis=False,result=None):
 from app import LocalArtifactStorage
 if include_analysis and result is None:
  from explicit_model import run_explicit_model
  result=run_explicit_model(tables)
  if not result.get('ok'):raise InputIssue('；'.join(result.get('errors',[])))
 scene,document=build_html(tables,result);storage=LocalArtifactStorage();key=storage.upload_file(file_content=document.encode(),file_name='Excel原始杆系三维预览.html',content_type='text/html')
 return {'ok':True,'html_url':storage.generate_presigned_url(key=key),'html_content':document,'nodes':len(scene['explicit_nodes']),'members':len(scene['explicit_members']),'scope':scene['analysis_scope'],'upstream_check_summary':result['upstream_check_summary'] if result else 'INCOMPLETE','file_name':'Excel原始杆系三维预览.html'}
