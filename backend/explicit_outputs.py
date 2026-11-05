"""Archive explicit static results without promoting them to design-check PASS."""
import json,hashlib,os,math
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile,ZIP_DEFLATED

def format_result_number(value):
 if value is None:return '—'
 n=float(value)
 if not math.isfinite(n):return '—'
 if n==0:return '0'
 return f'{n:.3e}' if abs(n)<1e-3 else f'{n:.6g}'

def representative_members(members):
 ranked=sorted(members,key=lambda m:max((c.get('utilization') or 0 for c in m['checks'] if c['item']=='section_strength'),default=0),reverse=True)
 selected={}
 for member in ranked:
  selected.setdefault(member['section_id'],member)
 return list(selected.values())

def publish_explicit_outputs(tables,result, *, include_drawings=True):
 from app import LocalArtifactStorage
 import ezdxf
 from openpyxl import Workbook
 from docx import Document
 from docx.shared import Cm,Pt,RGBColor
 from docx.oxml.ns import qn
 from tool_sources.engineering_drawings import EXPORT_PACKAGE_ROOT
 from steelmind_export.runtime import resolve_font,convert_docx_to_pdf
 from steelmind_export.reports import _table
 out=Path(os.getenv('STEELMIND_OUTPUT_ROOT',str(Path(__file__).parent/'artifacts')))/('explicit-'+uuid4().hex);out.mkdir(parents=True);files=[]
 def dump(name,data):
  p=out/name;p.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False));files.append(p)
 dump('原模型输入.json',tables);dump('自重分析结果.json',result)
 if result.get('code_checks'):dump('规范验算记录.json',result['code_checks'])
 if result.get('numerical_audit'):dump('数值复核记录.json',result['numerical_audit'])
 analysis=result['analysis'];nodes={n['node_id']:n for n in analysis['nodes']}
 d=ezdxf.new('R2018');d.units=4;d.appids.new('SOURCE');model=d.modelspace()
 for m in analysis['members']:
  e=model.add_line([v*1000 for v in nodes[m['i_node']]['xyz_m']],[v*1000 for v in nodes[m['j_node']]['xyz_m']]);e.set_xdata('SOURCE',[(1000,m['member_id']),(1000,m['section_id']),(1070,m['hinge_i']),(1070,m['hinge_j'])])
 p=out/'原始XYZ三维杆系.dxf';d.saveas(p)
 if ezdxf.readfile(p).audit().has_errors:raise ValueError('原始杆系DXF审查失败')
 files.append(p)
 wb=Workbook();ws=wb.active;ws.title='范围与平衡';ws.append(['项目','值']);ws.append(['范围',result['notice']]);ws.append(['自重kN',analysis['weight_kN']]);ws.append(['平衡残差kN',analysis['vertical_balance_error_kN']]);ws.append(['规范验算',result.get('upstream_check_summary','INCOMPLETE')]);ws.append(['验算统计',json.dumps(result.get('code_checks',{}).get('summary',{}),ensure_ascii=False)])
 ws=wb.create_sheet('节点六自由度');ws.append(['节点','X_m','Y_m','Z_m','ux_mm','uy_mm','uz_mm','rx_rad','ry_rad','rz_rad'])
 for n in nodes.values():ws.append([n['node_id']]+n['xyz_m']+n['displacement_mm_rad'])
 ws=wb.create_sheet('支反力');ws.append(['节点','Fx_kN','Fy_kN','Fz_kN','Mx_kNm','My_kNm','Mz_kNm'])
 for r in analysis['reactions']:ws.append(list(r.values()))
 ws=wb.create_sheet('分段杆端力');ws.append(['构件','截面','分段','Ni_kN','Vyi_kN','Vzi_kN','Ti_kNm','Myi_kNm','Mzi_kNm','Nj_kN','Vyj_kN','Vzj_kN','Tj_kNm','Myj_kNm','Mzj_kNm'])
 for m in analysis['members']:
  for i,f in enumerate(m['segment_end_actions_kN_kNm'],1):ws.append([m['member_id'],m['section_id'],i]+f)
 checks=result.get('code_checks') or {}
 ws=wb.create_sheet('规范验算明细');ws.append(['构件','截面','验算项','结论','需求','限值','单位','利用率','公式','采用值JSON','代入','依据','数据定位','缺项说明'])
 for member in checks.get('members',[]):
  for c in member['checks']:ws.append([member['member_id'],member['section_id'],c['item'],c['status'],c.get('demand'),c.get('limit'),c.get('unit'),c.get('utilization'),c.get('formula'),json.dumps(c.get('inputs',{}),ensure_ascii=False),c.get('substitution'),c.get('basis'),c.get('data_location'),c.get('reason')])
 ws=wb.create_sheet('规范适用范围');ws.append(['类别','内容'])
 for a in checks.get('assumptions',[]):ws.append(['采用假定',a])
 for a in checks.get('project_pending',[]):ws.append([a['item'],a['reason']])
 audit=result.get('numerical_audit') or {}
 ws=wb.create_sheet('整体六分量平衡');ws.append(['分量','输入荷载合计','支反力合计','残差','容差','单位','数值结论'])
 for c in audit.get('global_equilibrium',[]):ws.append([c[k] for k in ('component','external','reaction','residual','tolerance','unit','status')])
 ws=wb.create_sheet('单元平衡与释放');ws.append(['类型','构件','位置','力残差kN','力矩残差kNm','容差','数值结论'])
 for c in audit.get('segment_equilibrium',[]):ws.append(['单元平衡',c['member_id'],c['segment'],json.dumps(c['force_residual_kN']),json.dumps(c['moment_residual_kNm']),json.dumps({'force_kN':c['force_tolerance_kN'],'moment_kNm':c['moment_tolerance_kNm']}),c['status']])
 for c in audit.get('interface_equilibrium',[]):ws.append(['细分节点平衡',c['member_id'],c['interface'],json.dumps(c['force_residual_kN']),json.dumps(c['moment_residual_kNm']),None,c['status']])
 for c in audit.get('joint_equilibrium',[]):ws.append(['原始节点平衡',c['node_id'],None,json.dumps(c['force_residual_kN']),json.dumps(c['moment_residual_kNm']),None,c['status']])
 for c in audit.get('release_checks',[]):ws.append(['释放端',c['member_id'],c['end'],None,c['max_released_moment_kNm'],c['tolerance_kNm'],c['status']])
 for ws in wb:
  for row in ws.iter_rows():
   for cell in row:
    if isinstance(cell.value,(int,float)) and not isinstance(cell.value,bool) and 0<abs(cell.value)<1e-3:cell.number_format='0.000E+00'
  ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
  for col in ws.columns:ws.column_dimensions[col[0].column_letter].width=22
 p=out/'显式模型自重结果表.xlsx';wb.save(p);files.append(p)
 doc=Document();font,family=resolve_font();normal=doc.styles['Normal'];normal.font.name=family;normal.font.size=Pt(10);normal._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),family)
 for s in doc.sections:s.left_margin=s.right_margin=Cm(2)
 doc.styles['Title'].font.color.rgb=RGBColor(0,0,0)
 for border in list(doc.styles['Title']._element.iter(qn('w:pBdr'))):border.getparent().remove(border)
 doc.add_paragraph('原模型框架自重计算记录',style='Title');doc.add_paragraph('方案草稿  '+result.get('upstream_check_summary','INCOMPLETE')+'  完整规范验算未闭合');doc.add_paragraph(result['notice'])
 doc.add_heading('模型与输入保持',1);doc.add_paragraph(f'{len(nodes)}个原始节点，{len(analysis["members"])}根原始杆件。XYZ沿用Excel坐标，Z竖向；截面、材料、朝向和端部释放按逐构件记录。未使用教学默认荷载。')
 approved=[r for name,rows in tables.items() if name.lower()=='members' for r in rows if '截面转角90°改为0°' in str(r.get('notes','')) and float(r.get('orientation_deg') or 0)==0]
 if approved:doc.add_paragraph(f'用户已确认修正{len(approved)}根次梁截面转角90°为0°，H梁腹板竖直；未采用组合楼板侧向约束。原输入及逐杆修改对照另存案例包，不能将旧90°分析与本结果混用。')
 doc.add_heading('自重与平衡验证',1);doc.add_paragraph('q = A × 10⁻⁶ × ρ × 9.80665 × 自重系数，单位kN/m。按每根构件局部轴分解全局竖向重力，采用均布单元荷载。')
 doc.add_paragraph(f'框架自重合计 {analysis["weight_kN"]:.9g} kN；竖向反力残差 {format_result_number(analysis["vertical_balance_error_kN"])} kN。')
 audit=result.get('numerical_audit') or {}
 doc.add_heading('数值一致性复核',1)
 doc.add_paragraph(f"数值复核 {audit.get('status','未提供')}；检查{audit.get('segments_checked',0)}个细分单元、{audit.get('released_ends_checked',0)}个释放端、{len(audit.get('interface_equilibrium',[]))}个细分节点和{len(audit.get('joint_equilibrium',[]))}个原始节点。此结论只表示静力平衡与释放条件一致，不代表完整规范通过。")
 _table(doc,['分量','残差','容差','单位','数值结论'],[[c['component'],format_result_number(c['residual']),format_result_number(c['tolerance']),c['unit'],c['status']] for c in audit.get('global_equilibrium',[])],widths=[2,4,4,2,4])
 doc.add_paragraph('外荷载按输入截面面积、材料密度、构件长度独立重算；力矩绕原XYZ坐标原点求和。完整单元平衡和释放端数据见数值复核记录JSON及结果表。')
 doc.add_heading('材料与截面来源',1)
 _table(doc,['截面','A mm²','Iy mm⁴','Iz mm⁴'],[[k,v['A'],v['Iy'],v['Iz']] for k,v in analysis['sections'].items() if 'A' in v])
 doc.add_paragraph('面积与惯性矩保留工作簿值或完整型号匹配的型钢表值；H/箱形截面扭转常数J为薄壁近似。材质及刚度采用原工作簿；未把屈服强度fy当作规范设计强度f。')
 doc.add_heading('节点位移与支反力',1)
 _table(doc,['节点','ux mm','uy mm','uz mm'],[[n['node_id']]+[format_result_number(v) for v in n['displacement_mm_rad'][:3]] for n in nodes.values()],widths=[7,3,3,3])
 _table(doc,['支座','Fx kN','Fy kN','Fz kN'],[[r['node_id']]+[format_result_number(r[k]) for k in ('Fx_kN','Fy_kN','Fz_kN')] for r in analysis['reactions']],widths=[7,3,3,3])
 doc.add_heading('已实施的规范数值验算',1)
 checks=result.get('code_checks') or {}
 doc.add_paragraph('本次逐项统计 '+json.dumps(checks.get('summary',{}),ensure_ascii=False)+'；总体 '+str(checks.get('status','INCOMPLETE'))+'。PASS只表示该项在声明的输入与假定下满足限值。')
 for a in checks.get('assumptions',[]):doc.add_paragraph(a)
 doc.add_paragraph('NA表示本次受力或构件类型下不适用，保留判定理由；不是未计算项的替代。S4板件门槛通过不代表已完成梁侧扭或柱压弯稳定；毛截面应力通过亦不能替代待核的有效截面强度。')
 _table(doc,['构件','截面','毛截面应力比','通过/待补/不适用'],[[m['member_id'],m['section_id'],next((format_result_number(c['utilization']) for c in m['checks'] if c['item']=='section_strength'),'未提供'),'/'.join(str(m.get('coverage',{}).get(k,0)) for k in ('PASS','PENDING','NA'))+' '+m['status']] for m in checks.get('members',[])],widths=[4,5,3,4])
 ranked=representative_members(checks.get("members",[]))
 for m in ranked[:3]:
  doc.add_heading('控制构件 '+m['member_id'],2)
  for c in m['checks']:
   doc.add_paragraph(c['item']+'  '+c['status'])
   if c.get('demand') is not None:
    doc.add_paragraph('公式 '+str(c.get('formula')));doc.add_paragraph('代入 '+str(c.get('substitution')));doc.add_paragraph('采用值 '+json.dumps(c.get('inputs',{}),ensure_ascii=False));doc.add_paragraph('数据定位 '+str(c.get('data_location')))
   doc.add_paragraph('依据 '+str(c.get('basis','未提供'))+'；'+str(c.get('reason','')))
 doc.add_heading('未完成项',1);
 for gap in checks.get('project_pending',[]):doc.add_paragraph(gap['item']+'：'+gap['reason'])
 doc.add_paragraph('仅执行框架自重。未执行风、地震、模态、反应谱及完整荷载组合；构件截面强度、抗剪保守上界和梁挠度已计算，稳定与有效截面等项尚待闭合。未计楼板自重。不得据此与原3D3S风震组合结果直接比较并宣布通过。完整杆端力与分段位移见JSON/XLSX。')
 p=out/'框架自重计算记录.docx';doc.save(p);files.append(p)
 try:files.append(convert_docx_to_pdf(p,out))
 except Exception as e:dump('PDF转换缺项.json',{'error':str(e),'docx_preserved':True})
 drawing_quality=None
 if include_drawings:
  try:
   from explicit_cad import generate_explicit_cad
   cad_files,drawing_quality=generate_explicit_cad(tables,analysis,out/'cad',upstream_status=result.get('upstream_check_summary','INCOMPLETE'))
   files.extend(cad_files)
   if drawing_quality['status']!='PASS':dump('图纸生成缺项.json',drawing_quality)
  except Exception as e:dump('图纸生成缺项.json',{'error':str(e),'original_xyz_dxf_preserved':True})
 roles={r['file']:r['kind'] for r in (drawing_quality or {}).get('sheets',[])}
 storage=LocalArtifactStorage();artifacts=[]
 for p in files:
  media={'.dxf':'application/dxf','.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.json':'application/json'}.get(p.suffix,'application/octet-stream')
  preview='planar' if p.suffix=='.dxf' and roles.get(p.name) in ('plan','elevation','section') else 'download_only' if p.suffix=='.dxf' else 'document'
  raw=p.read_bytes();key=storage.upload_file(file_content=raw,file_name=p.name,content_type=media);artifacts.append({'preview_mode':preview,'drawing_role':roles.get(p.name,''),'media_type':media,'name':p.name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'url':storage.generate_presigned_url(key=key)})
 dump('manifest.json',{'status':'analysis_completed','drawing_generation_status':('not_requested' if not include_drawings else 'partial' if any(p.name=='图纸生成缺项.json' for p in files) else 'success'),'numerical_audit_status':result.get('numerical_audit',{}).get('status','INCOMPLETE'),'upstream_check_summary':result.get('upstream_check_summary','INCOMPLETE'),'artifacts':[{k:v for k,v in a.items() if k!='url'} for a in artifacts]})
 z=out/'原模型自重分析成果.zip'
 with ZipFile(z,'w',ZIP_DEFLATED) as archive:
  for p in files:archive.write(p,p.name)
 raw=z.read_bytes();key=storage.upload_file(file_content=raw,file_name=z.name,content_type='application/zip');artifacts.append({'name':z.name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'url':storage.generate_presigned_url(key=key)})
 return artifacts
