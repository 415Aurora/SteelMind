"""Report supplied spatial results with native tables and editable supplied linear math."""
from __future__ import annotations
import json
import unicodedata
from pathlib import Path
from docx import Document
from docx.shared import Cm,Pt,RGBColor
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from openpyxl import Workbook
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.utils import get_column_letter
from steelmind_export import runtime
from steelmind_export.reports import _table,_math,_field
from tool_sources.spatial_export import END_KEYS,DOFS,REACTIONS

def text(v):
 if v is None:return '未提供'
 if isinstance(v,float):return f'{v:.6g}'
 if isinstance(v,(dict,list)):return json.dumps(v,ensure_ascii=False)
 return str(v)

def editable_math(doc,value):
 # A Word linear-math run does not reliably wrap in LibreOffice. Keep supplied
 # characters editable in bounded continuation lines, and retain raw text in JSON.
 line='';width=0
 for ch in str(value):
  step=2 if unicodedata.east_asian_width(ch) in 'WF' else 1
  if width+step>70 or ch=='\n':
   if line:_math(doc,line)
   line='';width=0
  if ch!='\n':line+=ch;width+=step
 if line:_math(doc,line)


def write_workbook(bundle,path):
 wb=Workbook();wb.remove(wb.active)
 def sheet(name,headers,rows):
  ws=wb.create_sheet(name);ws.append(headers)
  for row in rows:
   ws.append([text(v) if isinstance(v,(dict,list)) else v for v in row])
   for cell in ws[ws.max_row]:
    if isinstance(cell.value,str):cell.data_type='s' # supplied formulas remain inert text
  ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
  for cell in ws[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='254B63')
  for idx in range(1,len(headers)+1):ws.column_dimensions[get_column_letter(idx)].width=22 if idx<5 else 18
  for row in ws.iter_rows(min_row=2):
   for c in row:c.alignment=Alignment(vertical='top',wrap_text=True);c.number_format='0.000000' if isinstance(c.value,float) else 'General'
  ws.sheet_properties.pageSetUpPr.fitToPage=True;ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A3;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0;ws.print_title_rows='1:1'
  return ws
 sheet('成果说明',['项目','内容'],[['项目名称',bundle['project_name']],['文件状态','生成与结构验算分别报告'],['上游验算汇总','INCOMPLETE'],['成果范围','三维方案草稿'],['坐标/单位',bundle['units']],['正号',bundle['axis_convention']]]+[['缺项及限制',r] for r in bundle['draft_reasons']])
 sheet('节点位移',['节点','X(m)','Y(m)','Z(m)','ux(mm)','uy(mm)','uz(mm)','rx(rad)','ry(rad)','rz(rad)'],[[n['node_id']]+[n[k] for k in ('x_m','y_m','z_m')+DOFS] for n in bundle['nodes']])
 sheet('构件模型',['构件','I节点','J节点','方向','截面','长度(m)','局部轴'],[[m['member_id'],m['node_i'],m['node_j'],m['member_axis'],m['section'],m['span_m'],m['local_axes']] for m in bundle['members']])
 sheet('支座与反力',['节点','ux约束','uy约束','uz约束','rx约束','ry约束','rz约束']+list(REACTIONS),[[s['node_id']]+[s[k] for k in ('ux','uy','uz','rx','ry','rz')]+[next(r for r in bundle['reactions'] if r['node_id']==s['node_id'])[k] for k in REACTIONS] for s in bundle['supports']])
 sheet('杆端力',['构件']+list(END_KEYS),[[m['member_id']]+[m['end_actions_local'][k] for k in END_KEYS] for m in bundle['members']])
 sheet('构件验算',['构件','类型','截面','上游利用率','上游通过','N(kN)','Mx(kN·m)','My(kN·m)','Vy(kN)','Vz(kN)','T(kN·m)','挠度(mm)'],[[c['member_id'],c['member_type'],c['section'],c['utilization'],c['passed']]+[(c.get('analysis_demands') or {}).get(k) for k in ('N_kn','Mx_kNm','My_kNm','Vy_kn','Vz_kn','T_kNm','deflection_mm')] for c in bundle['checks']])
 sheet('验算原文',['构件','记录序号','上游结论','原始公式及代入','依据定位'],[[c['member_id'],i,v.get('passed'),v.get('text') or v.get('item'),f"/checks/{ci}/checks/{i-1}"] for ci,c in enumerate(bundle['checks']) for i,v in enumerate(c.get('checks',[]),1)])
 sheet('截面属性',['截面','h(mm)','b(mm)','tw(mm)','tf(mm)','A(mm2)','Iy(mm4)','Iz(mm4)','J(mm4)','来源'],[[name]+[p[k] for k in ('h_mm','b_mm','tw_mm','tf_mm','A_mm2','Iy_mm4','Iz_mm4','J_mm4')]+[p.get('catalog_standard','上游未提交')] for name,p in bundle['sections'].items()])
 sheet('荷载与迭代',['数据定位','输入值'],[['/parameters/loads',bundle['parameters'].get('loads')],['/parameters/material',bundle['parameters'].get('material')]]+[[f'/iterations/{i}',v] for i,v in enumerate(bundle['iterations'])])
 sheet('追溯',['字段','内容'],[['schema_version',bundle['schema_version']],['source_run_id',bundle['source_run_id']],['source',bundle['source']],['原始输入','input_snapshot.json'],['归一化数据','spatial_bundle.json']])
 wb.save(path)

def write_book(bundle,path):
 doc=Document();font_path,family=runtime.resolve_font()
 for section in doc.sections:
  section.page_width=Cm(21);section.page_height=Cm(29.7);section.left_margin=section.right_margin=Cm(2);section.top_margin=Cm(1.8);section.bottom_margin=Cm(1.7)
  section.header.paragraphs[0].text='SteelMind  三维钢框架方案草稿  待复核'
  footer=section.footer.paragraphs[0];footer.add_run('三维结果归档  ·  ');_field(footer,'PAGE');footer.add_run(' / ');_field(footer,'NUMPAGES')
 for name in ('Normal','Title','Heading 1','Heading 2','Heading 3'):
  style=doc.styles[name];style.font.name=family;style._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),family)
  style.font.color.rgb=RGBColor(0,0,0)
  for border in list(style._element.iter(qn('w:pBdr'))):border.getparent().remove(border)
  fonts=style._element.get_or_add_rPr().rFonts
  for key in list(fonts.attrib):
   if 'theme' in key.lower():del fonts.attrib[key]
 doc.styles['Normal'].font.size=Pt(10);doc.styles['Normal'].paragraph_format.space_after=Pt(5)
 doc.styles['Title'].font.size=Pt(23)
 doc.add_paragraph('三维钢框架结构计算书',style='Title');doc.add_paragraph(bundle['project_name'])
 doc.add_paragraph('方案草稿  上游验算汇总 INCOMPLETE  待独立复核')
 doc.add_paragraph('本书归档同一轮最终三维分析、逐构件验算与绘图数据。文件生成成功仅表示成果已写出；所有“通过”均为上游已提交验算项结论。')
 doc.add_heading('1 工程概况与适用范围',level=1)
 for reason in bundle['draft_reasons']:doc.add_paragraph(reason)
 doc.add_heading('2 模型及材料截面',level=1)
 g=bundle['parameters']['geometry'];doc.add_paragraph(f"X向 {g.get('bays_x',g.get('bays'))} 跨，Z向 {g.get('bays_z')} 跨，{g['stories']} 层；{len(bundle['nodes'])} 个实体节点，{len(bundle['members'])} 根实体构件。全局 Y 轴竖向，X/Z 为平面方向。")
 doc.add_paragraph('几何坐标 m；位移 mm；转角 rad；力 kN；力矩 kN·m；应力 MPa。DXF模型空间按 mm 1:1。')
 _table(doc,['输入项','已提交值'],[[k,text(v)] for k,v in bundle['parameters'].get('geometry',{}).items()],widths=[5,11])
 _table(doc,['材料参数','已提交值'],[[k,text(v)] for k,v in bundle['parameters'].get('material',{}).items()],widths=[5,11])
 _table(doc,['最终截面','尺寸 h×b×tw×tf mm','A mm²','Iy / Iz mm⁴'],[[name,'×'.join(text(p[k]) for k in ('h_mm','b_mm','tw_mm','tf_mm')),text(p['A_mm2']),text(p['Iy_mm4'])+' / '+text(p['Iz_mm4'])] for name,p in bundle['sections'].items()],widths=[4.2,4.7,2.4,4.7])
 doc.add_paragraph('截面采用逐构件最终属性快照；不以名义尺寸反算值覆盖型钢表值。H截面 J 采用上游薄壁近似，来源见结果表。')
 doc.add_heading('3 荷载及组合',level=1)
 _table(doc,['上游字段','提交值'],[[k,text(v)] for k,v in bundle['parameters'].get('loads',{}).items()],widths=[8,8])
 doc.add_paragraph('本次内力对应上游单一静力输入，不代表全部承载力与正常使用组合的包络。未提供正式组合来源和适用限值，保留为缺项。X/Z楼层侧力是楼层总值，分配遵循上游模型。')
 doc.add_heading('4 分析结果与正号约定',level=1)
 doc.add_paragraph('局部 x 从 I 指向 J；OpenSees vecXZ 定义局部 x-z 平面，局部 y = vecXZ × x，局部 z = x × y。X向梁 vecXZ=(0,0,1)；Z向梁及柱 vecXZ=(1,0,0)。各构件实际局部轴单位向量列于结果表与 JSON。')
 doc.add_paragraph('杆端 Ni/Vyi/Vzi/Ti/Myi/Mzi 及 J端值为作用于构件的局部节点端力；端力正号不是沿程截面内力正号。不对无采样数据的沿程曲线作插值。上游验算字段 Mx/My 对应其强弱轴需求命名，原值与端力分列保留。')
 # Inline vector sketch: native text remains editable and avoids a deceptive planar projection.
 _math(doc,'I → J : +x ; +y = vecXZ × x ; +z = x × y ; +M follows the right-hand rule')
 _table(doc,['整体指标','提交值'],[[k,text(v)] for k,v in bundle['summary'].items() if not isinstance(v,(dict,list))],widths=[10,6])
 _table(doc,['节点','ux mm','uy mm','uz mm'],[[n['node_id'],text(n['ux_mm']),text(n['uy_mm']),text(n['uz_mm'])] for n in bundle['nodes']],widths=[6.5,3.1,3.2,3.2])
 _table(doc,['支座','Fx kN','Fy kN','Fz kN'],[[n['node_id'],text(n['fx_kN']),text(n['fy_kN']),text(n['fz_kN'])] for n in bundle['reactions']],widths=[6.5,3.1,3.2,3.2])
 doc.add_paragraph('全部节点六自由度、六分量反力、十二项杆端力及原始分段端力见 XLSX 和 JSON；此处只列平移与反力摘要。')
 doc.add_heading('5 构件验算汇总',level=1)
 _table(doc,['构件','最终截面','利用率','上游结论'],[[c['member_id'],c['section'],text(c['utilization']),'通过' if c['passed'] else 'FAIL'] for c in bundle['checks']],widths=[4.7,5.5,2.3,3.5])
 doc.add_paragraph('利用率沿用上游定义，局部稳定和整体稳定可能为筛查；不得将该列表解释为完整结构规范验算通过。')
 doc.add_heading('6 控制构件详算',level=1)
 # Keep the controlling member of each physical direction, rather than dropping Z beams.
 selected=[]
 for axis in ('X','Y','Z'):
  ids={m['member_id'] for m in bundle['members'] if m['member_axis']==axis};items=[c for c in bundle['checks'] if c['member_id'] in ids]
  if items:selected.append(max(items,key=lambda c:c['utilization']))
 for selected_index,c in enumerate(selected):
  if selected_index:doc.add_page_break()
  doc.add_heading(c['member_id']+' 控制记录',level=2)
  doc.add_paragraph('截面 '+c['section']+'；上游利用率 '+text(c['utilization'])+'；上游结论 '+('通过' if c['passed'] else 'FAIL'))
  _table(doc,['需求及单位','采用值'],[[k,text(v)] for k,v in (c.get('analysis_demands') or {}).items()],widths=[8,8])
  for idx,item in enumerate(c.get('checks',[])):
   editable_math(doc,item.get('text') or item.get('item') or '未提交公式')
   doc.add_paragraph(f"记录定位 /checks/{bundle['checks'].index(c)}/checks/{idx}；判定 {item.get('passed')}。公式与代入为上游原文；逐项条文、限值和数值字段未结构化提交时，需补充独立复核。")
  doc.add_paragraph('完整上游记录：')
  for line in (c.get('result_text') or '未提供').splitlines():doc.add_paragraph(line)
 doc.add_heading('7 图纸索引及缺项',level=1)
 doc.add_paragraph('配套DXF包含各层 XZ 平面、各Z轴 XY立面和各X轴 ZY立面，均标明切片范围；真实三维线框保留原XYZ坐标。投影图仅含同一轴面内构件，不推断节点连接、楼板或支撑。构件表将短标记映射至完整编号和截面。')
 for reason in bundle['draft_reasons']:doc.add_paragraph(reason)
 doc.add_heading('8 追溯附录',level=1)
 doc.add_paragraph('数据契约 '+bundle['schema_version']+'；上游运行编号 '+bundle['source_run_id'])
 doc.add_paragraph('input_snapshot.json 为原始最终报告；spatial_bundle.json 为同源归一化输入；validation.json 记录校核范围；manifest.json 记录各文件 SHA-256。生成过程不调用模型API，不执行输入公式。')
 doc.save(path)
