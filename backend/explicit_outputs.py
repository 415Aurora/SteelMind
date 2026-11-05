"""Archive explicit static results without promoting them to design-check PASS."""
import json,hashlib,os
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile,ZIP_DEFLATED

def publish_explicit_outputs(tables,result):
 from app import LocalArtifactStorage
 import ezdxf
 from openpyxl import Workbook
 from docx import Document
 from docx.shared import Cm,Pt
 from docx.oxml.ns import qn
 from tool_sources.engineering_drawings import EXPORT_PACKAGE_ROOT
 from steelmind_export.runtime import resolve_font,convert_docx_to_pdf
 from steelmind_export.reports import _table
 out=Path(os.getenv('STEELMIND_OUTPUT_ROOT',str(Path(__file__).parent/'artifacts')))/('explicit-'+uuid4().hex);out.mkdir(parents=True);files=[]
 def dump(name,data):
  p=out/name;p.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False));files.append(p)
 dump('原模型输入.json',tables);dump('自重分析结果.json',result)
 if result.get('code_checks'):dump('规范验算记录.json',result['code_checks'])
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
 for ws in wb:
  ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
  for col in ws.columns:ws.column_dimensions[col[0].column_letter].width=22
 p=out/'显式模型自重结果表.xlsx';wb.save(p);files.append(p)
 doc=Document();font,family=resolve_font();normal=doc.styles['Normal'];normal.font.name=family;normal.font.size=Pt(10);normal._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),family)
 for s in doc.sections:s.left_margin=s.right_margin=Cm(2)
 for border in list(doc.styles['Title']._element.iter(qn('w:pBdr'))):border.getparent().remove(border)
 doc.add_paragraph('原模型框架自重计算记录',style='Title');doc.add_paragraph('方案草稿  '+result.get('upstream_check_summary','INCOMPLETE')+'  完整规范验算未闭合');doc.add_paragraph(result['notice'])
 doc.add_heading('模型与输入保持',1);doc.add_paragraph(f'{len(nodes)}个原始节点，{len(analysis["members"])}根原始杆件。XYZ沿用Excel坐标，Z竖向；截面、材料、朝向和端部释放按逐构件记录。未使用教学默认荷载。')
 doc.add_heading('自重与平衡验证',1);doc.add_paragraph('q = A × 10⁻⁶ × ρ × 9.80665 × 自重系数，单位kN/m。按每根构件局部轴分解全局竖向重力，采用均布单元荷载。')
 doc.add_paragraph(f'框架自重合计 {analysis["weight_kN"]:.9g} kN；竖向反力残差 {analysis["vertical_balance_error_kN"]:.6g} kN。')
 doc.add_heading('材料与截面来源',1)
 _table(doc,['截面','A mm²','Iy mm⁴','Iz mm⁴'],[[k,v['A'],v['Iy'],v['Iz']] for k,v in analysis['sections'].items() if 'A' in v])
 doc.add_paragraph('面积与惯性矩保留工作簿值或完整型号匹配的型钢表值；H/箱形截面扭转常数J为薄壁近似。材质及刚度采用原工作簿；未把屈服强度fy当作规范设计强度f。')
 doc.add_heading('节点位移与支反力',1)
 _table(doc,['节点','ux mm','uy mm','uz mm'],[[n['node_id']]+[f'{v:.6g}' for v in n['displacement_mm_rad'][:3]] for n in nodes.values()],widths=[7,3,3,3])
 _table(doc,['支座','Fx kN','Fy kN','Fz kN'],[[r['node_id']]+[f'{r[k]:.6g}' for k in ('Fx_kN','Fy_kN','Fz_kN')] for r in analysis['reactions']],widths=[7,3,3,3])
 doc.add_heading('已实施的规范数值验算',1)
 checks=result.get('code_checks') or {}
 doc.add_paragraph('本次逐项统计 '+json.dumps(checks.get('summary',{}),ensure_ascii=False)+'；总体 '+str(checks.get('status','INCOMPLETE'))+'。PASS只表示该项在声明的输入与假定下满足限值。')
 for a in checks.get('assumptions',[]):doc.add_paragraph(a)
 _table(doc,['构件','截面','强度利用率','构件结论'],[[m['member_id'],m['section_id'],next((f"{c['utilization']:.5g}" for c in m['checks'] if c['item']=='section_strength'),'未提供'),m['status']] for m in checks.get('members',[])],widths=[4,5,3,4])
 ranked=sorted(checks.get('members',[]),key=lambda m:max([c.get('utilization') or 0 for c in m['checks']]),reverse=True)
 for m in ranked[:3]:
  doc.add_heading('控制构件 '+m['member_id'],2)
  for c in m['checks']:
   doc.add_paragraph(c['item']+'  '+c['status'])
   if c.get('demand') is not None:
    doc.add_paragraph('公式 '+str(c.get('formula')));doc.add_paragraph('代入 '+str(c.get('substitution')));doc.add_paragraph('采用值 '+json.dumps(c.get('inputs',{}),ensure_ascii=False));doc.add_paragraph('数据定位 '+str(c.get('data_location')))
   doc.add_paragraph('依据 '+str(c.get('basis','未提供'))+'；'+str(c.get('reason','')))
 doc.add_heading('未完成项',1);doc.add_paragraph('仅执行框架自重。未执行风、地震、模态、反应谱及完整荷载组合；构件截面强度、抗剪保守上界和梁挠度已计算，稳定与有效截面等项尚待闭合。未计楼板自重。不得据此与原3D3S风震组合结果直接比较并宣布通过。完整杆端力与分段位移见JSON/XLSX。')
 p=out/'框架自重计算记录.docx';doc.save(p);files.append(p)
 try:files.append(convert_docx_to_pdf(p,out))
 except Exception as e:dump('PDF转换缺项.json',{'error':str(e),'docx_preserved':True})
 storage=LocalArtifactStorage();artifacts=[]
 for p in files:
  raw=p.read_bytes();key=storage.upload_file(file_content=raw,file_name=p.name,content_type='application/octet-stream');artifacts.append({'preview_mode':'download_only' if p.suffix=='.dxf' else 'document','name':p.name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'url':storage.generate_presigned_url(key=key)})
 dump('manifest.json',{'status':'analysis_completed','upstream_check_summary':result.get('upstream_check_summary','INCOMPLETE'),'artifacts':[{k:v for k,v in a.items() if k!='url'} for a in artifacts]})
 z=out/'原模型自重分析成果.zip'
 with ZipFile(z,'w',ZIP_DEFLATED) as archive:
  for p in files:archive.write(p,p.name)
 raw=z.read_bytes();key=storage.upload_file(file_content=raw,file_name=z.name,content_type='application/zip');artifacts.append({'name':z.name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'url':storage.generate_presigned_url(key=key)})
 return artifacts
