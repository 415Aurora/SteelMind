"""Same-run office calculation book, archive tables and actual DXF layouts."""
from __future__ import annotations
import hashlib,json,os,sys
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from office_design import json_ready
from explicit_outputs import format_result_number as fmt

LABELS={'plate_class_S4_sufficient':'板件 S4 充分条件','elastic_section_strength':'弹性截面强度','combined_shear_and_torsion':'剪力与扭转共同作用','equivalent_stress':'折算应力','lateral_torsional_stability':'梁侧扭稳定','biaxial_compression_stability':'双轴压弯稳定','compression_slenderness':'受压长细比','web_no_intermediate_stiffener_threshold':'腹板稳定适用条件','support_stiffener_stability':'支承加劲肋稳定','support_stiffener_end_bearing':'加劲肋端面承压','stiffener_plate_slenderness':'加劲肋宽厚比','beam_deflection':'物理整梁挠度','strong_column_weak_beam_applicability':'强柱弱梁适用性'}


def sheet_value(value):
 if isinstance(value,(dict,list,tuple)):value=json.dumps(json_ready(value),ensure_ascii=False)
 return "'"+value if isinstance(value,str) and value[:1] in ('=','+','-','@') else value


def artifact_preview(name,roles):
 if not name.lower().endswith('.dxf'):return 'document'
 return 'planar' if roles.get(name) in ('plan','elevation','section') else 'download_only'


def write_office_outputs(run,output_dir,*,include_drawings=True,include_pdf=True):
 if run.get('ok') is not True or run.get('analysis_status')!='analysis_completed' or not run.get('code_checks'):raise ValueError('只能为实际完成分析的办公楼运行生成成果')
 from docx import Document
 from docx.shared import Cm,Pt,RGBColor
 from docx.oxml import OxmlElement
 from docx.oxml.ns import qn
 from openpyxl import Workbook
 from openpyxl.styles import Font,PatternFill,Alignment
 export_root=str(Path(__file__).parent/'engineering_export'/'src')
 if export_root not in sys.path:sys.path.insert(0,export_root)
 from steelmind_export.runtime import resolve_font,convert_docx_to_pdf
 from steelmind_export.reports import _table
 out=Path(output_dir).resolve()
 if out.exists() and any(out.iterdir()):raise ValueError('成果目录必须为空，禁止混入旧文件')
 out.mkdir(parents=True,exist_ok=True);files=[];warnings=[];drawing_roles={};b=run['bundle'];a=run['analysis'];checks=run['code_checks'];e=run['envelopes'];base=a['case_results']['G']['analysis'];nodes=base['nodes'];used={m['section_id'] for m in base['members']};sections={k:v for k,v in base['sections'].items() if k in used}
 def dump(name,value):
  p=out/name;p.write_text(json.dumps(json_ready(value),ensure_ascii=False,indent=2,allow_nan=False));files.append(p)
 dump('办公楼输入快照.json',b);dump('原始参考输入.json',run['original_bundle']);dump('办公楼完整运行.json',run);dump('规范验算记录.json',checks);dump('二阶对照验证.json',run['verification']);dump('截面调整记录.json',run['iterations']);dump('构造性能交接.json',checks['handoff'])
 wb=Workbook();wb.remove(wb.active)
 def tab(name,header,rows):
  ws=wb.create_sheet(name);ws.append(header)
  for row in rows:ws.append([sheet_value(v) for v in row])
  ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
  for c in ws[1]:c.font=Font(bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='244A70')
  for row in ws.iter_rows(min_row=2):
   for c in row:
    if isinstance(c.value,(int,float)):c.number_format='0.000E+00' if c.value and abs(c.value)<1e-3 else '0.0000'
  for col in ws.columns:ws.column_dimensions[col[0].column_letter].width=22
  return ws
 tab('范围与状态',['项目','值'],[['运行编号',run['run_id']],['输入SHA256',run['input_sha256']],['计算状态',run['analysis_status']],['上部框架数值验算',run['design_status']],['完整建筑状态',run['building_status']],['范围',run['scope']],['包络语义',e['method']]])
 tab('设计参数',['参数','值'],b['parameters'].items());tab('采用假定',['编号','采用内容','状态'],[[r['id'],r['description'],r['status']] for r in b['assumptions']])
 tab('节点',['节点','X_m','Y_m','Z_m'],[[r['node_id']]+r['xyz_m'] for r in nodes])
 tab('构件',['计算段','物理构件','I端','J端','截面','类型','完整无支撑长度_m','I释放','J释放'],[[r['member_id'],r['physical_member_id'],r['i_node'],r['j_node'],r['section_id'],r['member_type'],r['unbraced_length_m'],r['hinge_i'],r['hinge_j']] for r in base['members']])
 tab('截面',['编号','型号','h_mm','b_mm','tw_mm','tf_mm','A_mm2','Iy_mm4','Iz_mm4','来源'],[[k,s.get('section_name'),s['depth_mm'],s['width_mm'],s['tw_mm'],s['tf_mm'],s['A'],s['Iy'],s['Iz'],s.get('property_provenance',s.get('property_source'))] for k,s in sections.items()])
 tab('荷载来源',['工况','来源记录'],[[key,source] for key,c in a['cases'].items() for source in c['sources']])
 tab('质量源',['楼层','高度_m','质量_t','重心X_m','重心Y_m','极惯性_t_m2'],[[r['floor'],r['z_m'],r['mass_t']]+r['centroid_m']+[r['polar_mass_t_m2']] for r in a['mass_source']['floors']])
 tab('模态',['振型','周期_s','X有效质量_t','Y有效质量_t','X参与系数','Y参与系数'],[[r[k] for k in ('mode','period_s','effective_mass_x_t','effective_mass_y_t','participation_x','participation_y')] for r in a['modal']['modes']])
 tab('组合及二阶',['组合','极限状态','系数','地震方向','假想力上界_N_Nmm','二阶结论','theta上界'],[[r['id'],r['limit_state'],r['factors'],r.get('earthquake_direction'),r['notional_force_abs_N_Nmm'],r['second_order']['status'],r['second_order'].get('theta_upper_bound')] for r in e['combinations']])
 tab('节点位移',['工况','节点','ux_mm','uy_mm','uz_mm','rx_rad','ry_rad','rz_rad'],[[key,n['node_id']]+n['displacement_mm_rad'] for key,r in a['case_results'].items() for n in r['analysis']['nodes']])
 tab('实际工况杆端力',['工况','构件','分段','Ni_kN','Vyi_kN','Vzi_kN','Ti_kNm','Myi_kNm','Mzi_kNm','Nj_kN','Vyj_kN','Vzj_kN','Tj_kNm','Myj_kNm','Mzj_kNm'],[[key,m['member_id'],j+1]+f for key,r in a['case_results'].items() for m in r['analysis']['members'] for j,f in enumerate(m['segment_end_actions_kN_kNm'])])
 from office_responses import DEMAND_KEYS
 tab('承载验算分量上界',['物理构件']+list(DEMAND_KEYS),[[pid]+list(e['strength'][i]) for i,pid in enumerate(a['physical_ids'])])
 tab('构件验算',['物理构件','截面','验算项','结论','需求','限值','单位','利用率','公式','输入','代入','依据','定位','说明'],[[m['member_id'],m['section_id'],LABELS.get(c['item'],c['item']),c['status'],c.get('demand'),c.get('limit'),c.get('unit'),c.get('utilization'),c.get('formula'),c.get('inputs'),c.get('substitution'),c.get('basis'),c.get('data_location'),c.get('reason')] for m in checks['members'] for c in m['checks']])
 tab('整体检查',['检查','结论','需求','限值','依据','说明'],[[c['item'],c['status'],c['demand'],c['limit'],c['basis'],c.get('reason')] for c in checks['global_checks']])
 tab('加劲肋及位置',['编号','物理梁','宽_mm','厚_mm','高_mm','节点','构造要求'],[[r['id'],r['physical_member_id'],r['width_mm'],r['thickness_mm'],r['height_mm'],r['node_ids'],r['placement']] for r in b.get('stiffeners',[])])
 tab('交接性能',['构件','项目','状态','要求'],[[r.get('member_id','工程级'),r['item'],r['status'],r.get('performance',r.get('reason'))] for r in checks['handoff']])
 p=out/'办公楼分析与验算结果表.xlsx';wb.save(p);files.append(p)
 doc=Document();_,family=resolve_font();normal=doc.styles['Normal'];normal.font.name=family;normal.font.size=Pt(9);normal._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),family);normal.paragraph_format.space_after=Pt(5)
 for section in doc.sections:section.left_margin=section.right_margin=Cm(2);section.top_margin=section.bottom_margin=Cm(1.8)
 for name in ('Title','Heading 1','Heading 2'):doc.styles[name].font.name=family;doc.styles[name].font.color.rgb=RGBColor(0,0,0);doc.styles[name]._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),family)
 for border in list(doc.styles['Title']._element.iter(qn('w:pBdr'))):border.getparent().remove(border)
 def table(headers,rows):_table(doc,headers,rows)
 def equation(text):
  # Editable OMML linear math text; no formula/code evaluation.
  for offset in range(0,len(text),90):
   p=doc.add_paragraph();math=OxmlElement('m:oMath');r=OxmlElement('m:r');t=OxmlElement('m:t');t.text=text[offset:offset+90];r.append(t);math.append(r);p._p.append(math)
 doc.add_paragraph('龙岩办公楼上部钢框架计算书',style='Title');doc.add_paragraph('参考布置课程设计 方案计算记录')
 doc.add_paragraph(f"上部杆系数值验算 {run['design_status']}；完整建筑状态 {run['building_status']}。本报告供课程案例与小组集成复核使用，连接、柱脚、基础、楼板及楼梯本体另行设计。计算成功或文件生成成功均不代表上述构造已经验证。")
 doc.add_paragraph('输入 SHA256 '+run['input_sha256']);doc.add_paragraph('运行编号 '+run['run_id'])
 doc.add_heading('工程概况与模型边界',1);doc.add_paragraph(f"四层，层高4m，平面38m×16.5m；{len(nodes)}个原始节点、{len(base['members'])}个计算段、{len(a['physical_ids'])}个物理构件。参考清晰二层图作为标准层重复，楼梯开洞和屋面补梁为已确认的新课程设计条件，不凑原3D3S的552根杆件。旧Excel为120节点248杆件，仅自重模型，两者分别留档。")
 for row in b['assumptions']:doc.add_paragraph(row['description'])
 doc.add_heading('材料截面与调整记录',1)
 table(['角色','最终截面','A mm²','Iy mm⁴','Iz mm⁴'],[[next(m['role'] for m in base['members'] if m['section_id']==sid),s.get('section_name'),fmt(s['A']),fmt(s['Iy']),fmt(s['Iz'])] for sid,s in sections.items()])
 doc.add_paragraph('原始截面权威值原样保存；改型截面以明确的焊接板件理想几何计算，不计圆角。箱柱采用焊接钢板产品假定。Q355材料强度按板厚组取值；采用公开转载勘误表已核对数值，归档来源并保留非出版社原发认证说明。')
 table(['方案','数值状态','最大利用率','调整说明'],[[str(r['scheme']),r['design_status'],fmt(r['max_utilization']),r['reason']] for r in run['iterations']])
 doc.add_heading('作用与质量源',1);table(['参数','采用值'],[[k,str(v)] for k,v in b['parameters'].items()])
 table(['工况','荷载审查','合计或分量'],[[key,c.get('audit',{}).get('status','见来源'),json.dumps(c.get('audit',{}).get('force_kN',c.get('audit',{}).get('weight_kN','见结果表')),ensure_ascii=False)] for key,c in a['cases'].items()])
 doc.add_paragraph('G包括钢构件、加劲肋、楼面或屋面、墙及楼梯承托荷载。前三层各扣除112m²楼梯洞口，楼面515m²；屋面627m²。洞口内不重复施加楼板荷载。办公活载按已采用3.5kPa，不使用未提供的用途分区进行减载。')
 doc.add_paragraph(f"质量源G+0.5Q办公+0.5Q楼梯，屋面活载不计；总质量 {fmt(a['mass_source']['total_mass_t'])} t。柱自重上层集中；节点质量、重心和转动惯量见结果表。")
 doc.add_heading('静力模态与反应谱',1)
 table(['振型','周期 s','X有效质量 t','Y有效质量 t'],[[r['mode'],fmt(r['period_s']),fmt(r['effective_mass_x_t']),fmt(r['effective_mass_y_t'])] for r in a['modal']['modes']])
 doc.add_paragraph(f"水平有效质量覆盖 X={a['modal']['coverage_x']:.6f}，Y={a['modal']['coverage_y']:.6f}。全部楼层水平与扭转集中质量自由度均保留，质量为零的杆件自由度经静力凝聚；不是剪切楼模型拟合。阻尼0.04，采用Tg=0.90s作为平台延长设计条件，第二组IV类表值0.75s另存。")
 doc.add_paragraph('风按C类地面和明确的封闭低坡屋面矩形体型，包含四个方向墙面压力及屋面吸力。水平地震采用带符号模态响应、CQC相关、双向效应及±5%偶然质量偏心；满足最低层剪力调整。完整来源、模态贡献和调整值见运行JSON。')
 doc.add_heading('组合与二阶稳定方法',1);doc.add_paragraph(f"本次{len(e['combinations'])}个组合，含ULS、标准/频遇/准永久SLS及水平地震。G不利1.3/有利1.0，变量1.5，地震Eh1.4。{a['live_regions_analyzed']}个独立活载分区响应取绝对充分上界，覆盖未同时满布的情形；不把各分量包络伪装为同时内力。")
 doc.add_paragraph('整体采用刚性楼层柱弦P-Δ及GB50017 5.2.1假想水平力；构件P-δ仍由第8章稳定公式处理。正算子与可验证轴力上界形成二阶充分包络，失败不等于真实结构失稳。只有该路线成立后按5.4.1及8.3.1采用柱μ=1。梁段划分不缩短物理侧扭无支撑长度。')
 doc.add_paragraph(f"二阶指标最大上界 {fmt(e['maximum_theta_upper_bound'])}，控制0.25；10组直接OpenSees PDelta控制对照 {run['verification']['status']}。数值零的单位相关容差仅用于对照验证，不修改设计需求或通过条件。")
 doc.add_heading('整体控制与适用性',1);table(['检查','结论','需求','限值'],[[c['item'],c['status'],fmt(c['demand']),fmt(c['limit'])] for c in checks['global_checks']])
 doc.add_paragraph('扭转位移比1.2为不规则分类阈值，超过后计入空间扭转、双向和偶然偏心，采用1.5控制；不将1.2直接当作承载力极限。层刚度按明确的m_i z_i水平力模式下层剪力/层间侧移计算。竖向地震与罕遇非弹性变形的不适用判断仅在已声明普通6度16m等条件内成立。')
 doc.add_heading('构件验算汇总',1);doc.add_paragraph(json.dumps(checks['summary'],ensure_ascii=False));table(['物理构件','截面','数值状态','最大利用率'],[[m['member_id'],m['section_id'],m['status'],fmt(m['max_utilization'])] for m in checks['members']])
 selected={}
 for role in ('GZ1','GL2','GL3'):
  group=[m for m in checks['members'] if m['role']==role]
  for item in ('elastic_section_strength','biaxial_compression_stability','lateral_torsional_stability','beam_deflection'):
   candidates=[(m,c) for m in group for c in m['checks'] if c['item']==item]
   if candidates:
    m,c=max(candidates,key=lambda pair:pair[1].get('utilization',0.));selected[m['member_id']]=m
 doc.add_heading('控制构件详算',1)
 for m in selected.values():
  doc.add_heading(m['member_id']+' '+m['section_id'],2)
  doc.add_paragraph('分量控制组合 '+json.dumps(m['control_combinations'],ensure_ascii=False))
  for c in m['checks']:
   doc.add_paragraph(LABELS.get(c['item'],c['item'])+'  '+c['status']);equation(c.get('formula','见适用条件'))
   doc.add_paragraph('代入 '+str(c.get('substitution','')));doc.add_paragraph('结果 '+fmt(c.get('demand'))+' / 限值 '+fmt(c.get('limit'))+' '+str(c.get('unit',''))+'；利用率 '+fmt(c.get('utilization')))
   doc.add_paragraph('依据 '+str(c.get('basis',''))+'；定位 '+str(c.get('data_location',''))+'；'+str(c.get('reason','')))
 doc.add_heading('构造性能与小组交接',1)
 for row in checks['handoff'][-4:]:doc.add_paragraph(row['item']+'  '+row['status']+'：'+row['reason'])
 doc.add_paragraph('每根H梁端防扭、潜在塑性铰区双翼缘侧向支承和加劲肋传力焊缝均需由连接组验证。加劲肋按列明节点双面成对布置、刨平顶紧，稳定/承压采用忽略有效腹板面积的保守计算；其自重和质量已计入。完整逐梁性能和力上界见构造性能交接JSON及结果表。')
 doc.add_heading('追溯与复现',1);doc.add_paragraph('原始输入SHA256 '+run['original_input_sha256']);doc.add_paragraph('最终输入SHA256 '+run['input_sha256']);doc.add_paragraph('模块SHA256 '+run['engine_sha256']);doc.add_paragraph('公式为可编辑Word线性数学文本。程序不执行输入公式代码，不调用模型API补造计算过程。完整节点、杆端力、模态响应、组合系数及验算输入在同一运行JSON与XLSX中归档。')
 p=out/'办公楼上部钢框架计算书.docx';doc.save(p);files.append(p)
 if include_pdf:
  try:files.append(convert_docx_to_pdf(p,out))
  except Exception as exc:warnings.append('计算书PDF转换失败：'+str(exc))
 import ezdxf
 raw=ezdxf.new('R2018');raw.units=4;raw.appids.new('SOURCE');space=raw.modelspace();by_node={n['node_id']:n for n in nodes}
 for member in base['members']:
  entity=space.add_line([v*1000 for v in by_node[member['i_node']]['xyz_m']],[v*1000 for v in by_node[member['j_node']]['xyz_m']]);entity.set_xdata('SOURCE',[(1000,member['member_id']),(1000,member['physical_member_id']),(1000,member['section_id'])])
 p=out/'90_原始XYZ空间杆系.dxf';raw.saveas(p)
 if ezdxf.readfile(p).audit().has_errors:raise ValueError('原始XYZ图审查失败')
 files.append(p)
 drawing_status='not_requested'
 if include_drawings:
  try:
   from explicit_cad import generate_explicit_cad
   drawing_analysis={**base,'sections':sections};cad_files,quality=generate_explicit_cad(b['tables'],drawing_analysis,out/'cad',include_pdf=include_pdf,upstream_status=run['design_status']+' / 构造交接待核',compact_marks=True)
   files.extend(cad_files);drawing_roles={row['file']:row['kind'] for row in quality['sheets']};drawing_status='success' if quality['status']=='PASS' else 'partial'
   if drawing_status!='success':warnings.append('部分CAD质量检查或PDF渲染未完成')
  except Exception as exc:drawing_status='partial';warnings.append('图纸生成失败：'+str(exc))
 generation='partial' if warnings else 'success';dump('生成日志.json',{'run_id':run['run_id'],'file_generation_status':generation,'drawing_generation_status':drawing_status,'warnings':warnings,'dwg_status':'not_generated_optional_converter_not_configured'})
 entries=[{'path':str(p.relative_to(out)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]
 manifest={'run_id':run['run_id'],'input_sha256':run['input_sha256'],'engine_sha256':run['engine_sha256'],'file_generation_status':generation,'drawing_generation_status':drawing_status,'design_status':run['design_status'],'building_status':run['building_status'],'warnings':warnings,'files':entries,'manifest_scope':'entries exclude manifest itself and ZIP; callers hash both separately'};dump('manifest.json',manifest)
 target=out/'办公楼完整荷载课程设计成果.zip'
 with ZipFile(target,'w',ZIP_DEFLATED) as z:
  for p in files:z.write(p,p.relative_to(out))
 files.append(target)
 return {'manifest':manifest,'files':files,'output_dir':out,'drawing_roles':drawing_roles}


def publish_office_outputs(run):
 from uuid import uuid4
 from app import LocalArtifactStorage
 out=Path(os.getenv('STEELMIND_OUTPUT_ROOT',str(Path(__file__).parent/'artifacts')))/('office-'+uuid4().hex);generated=write_office_outputs(run,out);storage=LocalArtifactStorage();artifacts=[]
 for p in generated['files']:
  raw=p.read_bytes();media={'.pdf':'application/pdf','.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','.dxf':'application/dxf','.json':'application/json','.zip':'application/zip'}.get(p.suffix,'application/octet-stream');key=storage.upload_file(file_content=raw,file_name=p.name,content_type=media)
  artifacts.append({'name':p.name,'url':storage.generate_presigned_url(key=key),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'preview_mode':artifact_preview(p.name,generated['drawing_roles']),'drawing_role':generated['drawing_roles'].get(p.name,''),'media_type':media})
 return {**generated['manifest'],'ok':True,'draft':True,'upstream_check_summary':run['design_status'],'artifacts':artifacts}
