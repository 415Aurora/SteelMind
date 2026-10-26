"""Archive supplied design data as an editable calculation book and workbook.

This module does not solve structures, infer missing results, or establish code
compliance. It preserves the supplied check decisions and validation report.
"""
from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile
from typing import Iterable

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_SECTION_START
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.utils import get_column_letter

from .models import DesignBundle, Check
from .validation import ValidationReport
from .results import ExportOutcome, GenerationOptions
from . import runtime

MISSING = '未提供'
RED = 'C00000'
AMBER = 'FFF2CC'
CHAPTERS = [
    '1 概况与边界', '2 模型及材料截面', '3 荷载及组合', '4 分析结果',
    '5 验算汇总', '6 控制构件详算', '7 缺项及使用限制', '8 追溯附录',
]


def _text(value) -> str:
    if value is None or value == '' or value == [] or value == {}:
        return MISSING
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, float):
        return format(value, '.6g')
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _status(check: Check) -> str:
    if check.status == 'NA':
        return f'NA({check.na_reason or MISSING})'
    if check.demand is None or check.limit is None:
        return f'{check.status}（上游声明；缺少数值判定）'
    return check.status


def _field(paragraph, instruction: str):
    field = OxmlElement('w:fldSimple')
    field.set(qn('w:instr'), instruction)
    paragraph._p.append(field)


def _math(doc, value: str):
    """Store supplied Unicode linear math in native editable Word OMML."""
    paragraph = doc.add_paragraph()
    math = OxmlElement('m:oMath')
    run = OxmlElement('m:r')
    text = OxmlElement('m:t')
    text.set(qn('xml:space'), 'preserve')
    text.text = value or MISSING
    run.append(text)
    math.append(run)
    paragraph._p.append(math)


def _paragraph(doc, text: str, *, red: bool = False):
    paragraph = doc.add_paragraph(text)
    if red:
        for run in paragraph.runs:
            run.font.color.rgb = RGBColor.from_string(RED)
    return paragraph


def _table(doc, headers, rows: Iterable, *, widths=None):
    rows = list(rows)
    if not rows:
        _paragraph(doc, MISSING)
        return None
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = 'Table Grid'
    table.autofit = False
    widths = widths or [16 / len(headers)] * len(headers)
    for cell, header, width in zip(table.rows[0].cells, headers, widths):
        cell.width = Cm(width)
        cell.text = str(header)
        shade = OxmlElement('w:shd')
        shade.set(qn('w:fill'), 'EEEEEE')
        cell._tc.get_or_add_tcPr().append(shade)
        for run in cell.paragraphs[0].runs:
            run.bold = True
    repeat = OxmlElement('w:tblHeader')
    table.rows[0]._tr.get_or_add_trPr().append(repeat)
    for row_values in rows:
        cells = table.add_row().cells
        failed = any(str(v) == 'FAIL' or str(v).startswith('FAIL（') for v in row_values)
        for cell, value, width in zip(cells, row_values, widths):
            cell.width = Cm(width)
            cell.text = _text(value)
            for p in cell.paragraphs:
                p.paragraph_format.space_after = Pt(2)
                p.paragraph_format.space_before = Pt(2)
                for run in p.runs:
                    run.font.size = Pt(8.5)
                    if failed:
                        run.font.color.rgb = RGBColor.from_string(RED)
    for row in table.rows:
        row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


def _geometry(bundle, destination: Path, font_path: Path):
    """Plot original XY geometry, without rescaling axes or inventing members."""
    with runtime.RENDER_LOCK:
        import matplotlib
        matplotlib.use('Agg')
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.font_manager import FontProperties
        font = FontProperties(fname=str(font_path), size=9)
        figure = Figure(figsize=(7.0, 4.2), dpi=180, layout='constrained')
        FigureCanvasAgg(figure)
        ax = figure.add_subplot(111)
        nodes = {n.id: n for n in bundle.model.nodes}
        for member in bundle.model.members:
            if member.node_i not in nodes or member.node_j not in nodes:
                continue
            a, b = nodes[member.node_i], nodes[member.node_j]
            ax.plot([a.x_m, b.x_m], [a.y_m, b.y_m], color='#263238', linewidth=1.7)
            ax.annotate(member.id, ((a.x_m+b.x_m)/2, (a.y_m+b.y_m)/2),
                        xytext=(4, 5), textcoords='offset points', fontproperties=font)
        for node in nodes.values():
            ax.plot(node.x_m, node.y_m, 'o', color='#263238', markersize=3)
            ax.annotate(node.id, (node.x_m, node.y_m), xytext=(4, -12),
                        textcoords='offset points', fontproperties=font)
        if not nodes:
            ax.text(.5, .5, MISSING, transform=ax.transAxes, fontproperties=font)
        ax.set_xlabel('x / m', fontproperties=font)
        ax.set_ylabel('y / m', fontproperties=font)
        ax.set_title('节点与构件实际坐标', fontproperties=font)
        ax.set_aspect('equal', adjustable='datalim')
        ax.margins(.15)
        ax.grid(True, color='#dddddd', linewidth=.5)
        figure.savefig(destination)
        figure.clear()


def _configure_document(font_family: str, validation: ValidationReport):
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    section.top_margin = section.bottom_margin = Cm(2.5)
    section.left_margin = section.right_margin = Cm(2.5)
    section.header_distance = section.footer_distance = Cm(1.2)
    section.different_first_page_header_footer = True
    for name in ('Normal', 'Title', 'Subtitle', 'Heading 1', 'Heading 2', 'Heading 3', 'Caption'):
        style = doc.styles[name]
        style.font.name = font_family
        style.font.color.rgb = RGBColor(0, 0, 0)
        fonts = style._element.get_or_add_rPr().get_or_add_rFonts()
        for key in list(fonts.attrib):
            if key.endswith('Theme'):
                del fonts.attrib[key]
        for key in ('ascii', 'hAnsi', 'eastAsia', 'cs'):
            fonts.set(qn('w:' + key), font_family)
        for border in list(style._element.iter(qn('w:pBdr'))):
            border.getparent().remove(border)
    normal = doc.styles['Normal']
    normal.font.size = Pt(10.5)
    normal.paragraph_format.line_spacing = 1.25
    normal.paragraph_format.space_after = Pt(5)
    doc.styles['Title'].font.size = Pt(24)
    doc.styles['Heading 1'].font.size = Pt(16)
    doc.styles['Heading 1'].paragraph_format.page_break_before = True
    doc.styles['Heading 2'].font.size = Pt(12)
    header = section.header.paragraphs[0]
    header.text = '草稿  数据及上游验算待复核' if validation.draft else '上游结果归档  需专业复核'
    header.style = doc.styles['Normal']
    for run in header.runs:
        run.font.size = Pt(8)
        if validation.draft:
            run.font.color.rgb = RGBColor.from_string(RED)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run('第 ')
    _field(footer, 'PAGE')
    footer.add_run(' 页')
    return doc


def _details_selection(bundle):
    selected = set()
    controlling = {}
    for check in bundle.checks:
        if check.status in ('FAIL', 'NA') or check.demand is None or check.limit is None or check.utilization is None:
            selected.add(check.id)
        if check.utilization is not None:
            key = (check.target_id, check.item)
            if key not in controlling or check.utilization > controlling[key].utilization:
                controlling[key] = check
    selected.update(c.id for c in controlling.values())
    return [check for check in bundle.checks if check.id in selected]


def _make_docx(bundle, validation, destination, diagram, font_family, font_path):
    doc = _configure_document(font_family, validation)
    project = bundle.project
    doc.add_paragraph('钢结构计算书与结果归档', style='Title')
    doc.add_paragraph(project.name, style='Subtitle')
    _paragraph(doc, '草稿  不完整资料需补充复核' if validation.draft else '上游结果归档  专业复核后使用', red=validation.draft)
    kind = bundle.provenance.data_kind
    _paragraph(doc, f'数据来源类别 {kind}', red=kind != 'upstream')
    if kind == 'demonstration':
        _paragraph(doc, 'DEMO 演示数据  人工编排结果，不构成工程验算。', red=True)
    elif kind == 'analytic_benchmark':
        _paragraph(doc, '解析基准数据  用于核对单位及符号，不构成完整规范验算。', red=True)
    _paragraph(doc, '本计算书整理输入模型、荷载、已提供分析结果和上游验算记录。未提供独立分析人员复核结论，不据此作出整体结构安全结论。')
    _table(doc, ['状态类别', '本文件记录'], [
        ['文件生成', '本文件已生成，完整生成状态见manifest.json'],
        ['数据校核', validation.data_validation_status],
        ['上游验算项汇总', validation.upstream_check_summary],
    ], widths=[4, 12])
    for key, label in (('phase', '设计阶段'), ('designer', '编制'), ('institution', '学校或单位'),
                       ('student_id', '学号'), ('date', '编制日期')):
        _paragraph(doc, f'{label}  {_text(getattr(project, key))}')
    body = doc.add_section(WD_SECTION_START.NEW_PAGE)
    body.different_first_page_header_footer = False
    page_numbers = OxmlElement('w:pgNumType')
    page_numbers.set(qn('w:start'), '1')
    body._sectPr.append(page_numbers)
    _paragraph(doc, '目录', red=False)
    _field(doc.add_paragraph(), 'TOC \\o "1-2" \\h \\z \\u')
    _paragraph(doc, '在 Word 中选择更新域以刷新目录和页码。以下静态章节表用于未更新域的阅读环境。')
    for chapter in CHAPTERS:
        _paragraph(doc, chapter)

    doc.add_heading(CHAPTERS[0], 1)
    _paragraph(doc, f'项目 {_text(project.name)}；schema_version {bundle.schema_version}；run_id {_text(bundle.provenance.run_id)}。')
    _paragraph(doc, '本文件为数据与结果归档。文件生成成功不等于数据完整或上游验算通过。PASS、FAIL、NA 均保留上游声明；INCOMPLETE 表示验算覆盖或资料未完整。NA 仅表示附带理由的排除，不表示通过。')
    for title, values in [('输入假定', project.assumptions), ('使用边界', project.limitations)]:
        doc.add_heading(title, 2)
        for value in values or [MISSING]:
            _paragraph(doc, value)
    _paragraph(doc, f'来源 {_text(bundle.provenance.source)}')

    doc.add_heading(CHAPTERS[1], 1)
    _paragraph(doc, '坐标采用全局 XY 平面，单位 m。材料与截面数值按输入保留，几何示意使用真实坐标。')
    doc.add_picture(str(diagram), width=Cm(15.5))
    doc.add_paragraph('图 1 节点与构件实际坐标', style='Caption')
    _table(doc, ['id', 'x_m', 'y_m'], [[n.id, n.x_m, n.y_m] for n in bundle.model.nodes])
    _table(doc, ['id', 'node_i', 'node_j', 'section_id', 'material_id', 'kind', 'release_i / release_j'],
           [[m.id, m.node_i, m.node_j, m.section_id, m.material_id, m.kind,
             f'{_text(m.release_i)} / {_text(m.release_j)}'] for m in bundle.model.members])
    _table(doc, ['node_id', 'ux', 'uy', 'rz'], [[s.node_id,s.ux,s.uy,s.rz] for s in bundle.model.supports])
    _paragraph(doc, '支座 true 表示对应位移或转角被约束；release_i / release_j 为杆端转动释放。')
    doc.add_heading('材料', 2)
    _table(doc, ['id', 'name', 'E_MPa', 'fy_MPa', 'source'],
           [[m.id,m.name,m.E_MPa,m.fy_MPa,m.source] for m in bundle.model.materials], widths=[2,3,2.5,2.5,6])
    doc.add_heading('截面', 2)
    _table(doc, ['id', 'name / shape', 'h_mm', 'b_mm', 'tw_mm', 'tf_mm'],
           [[s.id, f'{s.name} / {s.shape}',s.h_mm,s.b_mm,s.tw_mm,s.tf_mm] for s in bundle.model.sections], widths=[2,5,2.25,2.25,2.25,2.25])
    _table(doc, ['id', 'A_mm2', 'Ix_mm4', 'Iy_mm4', 'Wx_mm3', 'Wy_mm3', 'property_basis'],
           [[s.id,s.A_mm2,s.Ix_mm4,s.Iy_mm4,s.Wx_mm3,s.Wy_mm3,s.property_basis] for s in bundle.model.sections])
    for section in bundle.model.sections:
        _paragraph(doc, f'{section.id} source  {_text(section.source)}')

    doc.add_heading(CHAPTERS[2], 1)
    _paragraph(doc, '节点荷载使用全局轴；均布杆件荷载使用局部轴，按杆件实际长度计。未提供的分量显示未提供。组合系数为上游输入。')
    for case in bundle.load_cases:
        doc.add_heading(f'{case.id} {case.name}', 2)
        _paragraph(doc, f'kind {case.kind}；source {_text(case.source)}')
        _table(doc, ['kind', 'target_id', 'fx_kN / qx_kN_m', 'fy_kN / qy_kN_m', 'mz_kNm'],
               [[load.kind, load.target_id, getattr(load,'fx_kN',getattr(load,'qx_kN_m',None)),
                 getattr(load,'fy_kN',getattr(load,'qy_kN_m',None)),getattr(load,'mz_kNm',None)] for load in case.loads])
    if not bundle.load_cases:
        _paragraph(doc, '荷载记录 未提供')
    _table(doc, ['id', 'name', 'limit_state', 'factors', 'source'],
           [[c.id,c.name,c.limit_state,c.factors,c.source] for c in bundle.combinations], widths=[2,3,2,4,5])

    doc.add_heading(CHAPTERS[3], 1)
    _paragraph(doc, '以下为输入的原始分析结果，未追加求解或插值。位移 mm，转角 rad，力 kN，弯矩 kN*m。杆端力为作用在杆件上的端部作用；局部 x 由 I 指向 J，局部 y 为左法线。截面正 x 面上 N 为 +x 拉力，V 为 -y，M 为逆时针正弯矩；相邻截面端值 I 为 (-Ni, Vi, -Mi)，J 为 (Nj, -Vj, Mj)。全部沿程内力采样点列于追溯附录；未提供的采样位置不作补充。')
    doc.add_heading('节点位移', 2)
    _table(doc, ['node_id','combination_id','ux_mm','uy_mm','rz_rad'],
           [[a.node_id,a.combination_id,a.ux_mm,a.uy_mm,a.rz_rad] for a in bundle.analysis.node_displacements])
    doc.add_heading('支反力', 2)
    _table(doc, ['node_id','combination_id','fx_kN','fy_kN','mz_kNm'],
           [[a.node_id,a.combination_id,a.fx_kN,a.fy_kN,a.mz_kNm] for a in bundle.analysis.reactions])
    doc.add_heading('杆端力', 2)
    _table(doc, ['member_id','combination_id','端','N_kN','V_kN','M_kNm'],
           [[a.member_id,a.combination_id,end,getattr(a,f'N{end.lower()}_kN'),getattr(a,f'V{end.lower()}_kN'),getattr(a,f'M{end.lower()}_kNm')]
            for a in bundle.analysis.member_end_forces for end in ('I','J')])

    doc.add_heading(CHAPTERS[4], 1)
    _paragraph(doc, f'上游验算项汇总 {validation.upstream_check_summary}；数据校核 {validation.data_validation_status}。', red=validation.upstream_check_summary=='FAIL')
    _table(doc, ['id','对象 / 组合 / 项目','demand','comparator','limit / unit','utilization','status'],
           [[c.id,f'{c.target_id}\n{c.combination_id}\n{c.item}',c.demand,c.comparator,f'{_text(c.limit)} {c.unit}',c.utilization,_status(c)] for c in bundle.checks],
           widths=[2.4,3.1,1.8,1.8,2.5,1.9,2.5])
    _paragraph(doc, '表中数值显示至少六位有效数字；完整精度见结果工作簿和输入归档。utilization 为声明值，未用格式化后的数值重算判定。')

    doc.add_heading(CHAPTERS[5], 1)
    _paragraph(doc, '按对象及验算项目选择声明 utilization 最大的记录，并列出全部 FAIL、NA 和缺少数值判定或利用系数的记录。未提供推导、来源或条文时明确标识。')
    selected = _details_selection(bundle)
    traces = {t.id:t for t in bundle.traces}
    if not selected:
        _paragraph(doc, '验算详算 未提供')
    for check in selected:
        p = doc.add_heading(f'{check.id} {check.target_id} {check.item}', 2)
        if check.status == 'FAIL':
            for run in p.runs:
                run.font.color.rgb = RGBColor.from_string(RED)
        _paragraph(doc, f'combination_id {check.combination_id}；status {_status(check)}', red=check.status=='FAIL')
        _paragraph(doc, f'demand {_text(check.demand)} {check.unit}  {check.comparator}  limit {_text(check.limit)} {check.unit}；utilization {_text(check.utilization)}')
        _paragraph(doc, '公式').paragraph_format.keep_with_next = True
        _math(doc, check.formula_text)
        _paragraph(doc, f'代入过程 {_text(check.substitution)}')
        _paragraph(doc, f'source {_text(check.source)}；clause {_text(check.clause)}')
        _paragraph(doc, f'trace_ids {_text(check.trace_ids)}')
        for trace_id in check.trace_ids:
            trace = traces.get(trace_id)
            _paragraph(doc, f'{trace_id} → {trace.result_path if trace else MISSING}；完整输入与中间过程见附录。')

    doc.add_heading(CHAPTERS[6], 1)
    _paragraph(doc, '草稿状态 ' + ('是' if validation.draft else '否'))
    for reason in validation.draft_reasons or [MISSING]:
        _paragraph(doc, reason)
    _table(doc, ['级别','code','path','message'],
           [[level,i.code,i.path,i.message] for level,issues in [('ERROR',validation.errors),('WARNING',validation.warnings)] for i in issues], widths=[1.8,3.2,4,7])
    _paragraph(doc, '本归档不提供独立分析人员签署或整体结构安全判定。使用者须核对模型边界、荷载来源、组合依据、规范适用性、缺项、条文与追溯链后使用。')
    for limitation in project.limitations:
        _paragraph(doc, limitation)

    doc.add_heading(CHAPTERS[7], 1)
    doc.add_heading('沿程内力全部采样', 2)
    _table(doc, ['member_id','combination_id','x_m / side','N_kN','V_kN','M_kNm'],
           [[a.member_id,a.combination_id,f'{_text(a.x_m)} / {a.side}',a.N_kN,a.V_kN,a.M_kNm] for a in bundle.analysis.member_samples])
    doc.add_heading('计算追溯', 2)
    if not bundle.traces:
        _paragraph(doc, '追溯记录 未提供')
    for trace in bundle.traces:
        doc.add_heading(f'{trace.id} {trace.name}', 2)
        _math(doc, trace.formula_text)
        _table(doc, ['inputs 名称','输入值'], [[key,value] for key,value in trace.inputs.items()], widths=[6,10])
        _paragraph(doc, '中间过程').paragraph_format.keep_with_next = True
        for step in trace.intermediate or [MISSING]:
            _paragraph(doc, step)
        _paragraph(doc, f'result {_text(trace.result)}；unit {_text(trace.unit)}')
        _paragraph(doc, f'source {_text(trace.source)}')
        _paragraph(doc, f'result_path {_text(trace.result_path)}')
    doc.add_heading('来源与运行信息', 2)
    _paragraph(doc, f'data_kind {kind}；run_id {_text(bundle.provenance.run_id)}；source {_text(bundle.provenance.source)}')
    _table(doc, ['tool_versions 名称','版本'], list(bundle.provenance.tool_versions.items()), widths=[6,10])
    _paragraph(doc, f'实际排版字体 {font_family}；字体文件 {font_path}')
    _paragraph(doc, '输入中缺少的解释统一显示未提供。报告导出器仅处理归档及排版。')
    doc.core_properties.title = f'{project.name} 计算书'
    doc.core_properties.subject = '输入与上游结果归档'
    doc.core_properties.author = project.designer
    # A table spacer can overflow onto a fresh page immediately before a
    # chapter's page-break-before, leaving an otherwise empty printed page.
    for paragraph in doc.paragraphs:
        if paragraph.style.name == 'Heading 1':
            previous = paragraph._p.getprevious()
            while (previous is not None and previous.tag == qn('w:p')
                   and not ''.join(previous.itertext()).strip()
                   and previous.find(qn('w:pPr') + '/' + qn('w:sectPr')) is None):
                before = previous.getprevious()
                previous.getparent().remove(previous)
                previous = before
    doc.save(destination)


def _safe_cell(cell, value):
    """Force every user string to text, including =,+,-,@; numbers stay numeric."""
    if value is None or value == '' or value == [] or value == {}:
        value = MISSING
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and len(value) > 32767:
        raise ValueError(f'Excel单元格 {cell.parent.title}!{cell.coordinate} 文本超过32767字符；完整内容保留在input.json，未生成截断的XLSX。')
    cell.value = value
    if isinstance(value, str):
        cell.data_type = 's'


def _sheet(workbook, name, headers, records, font_family, index):
    sheet = workbook.create_sheet(name)
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
    sheet.cell(1,1,f'{name}  输入及上游结果归档')
    sheet.cell(1,1).font = Font(name=font_family,size=15,bold=True)
    for col, header in enumerate(headers,1):
        _safe_cell(sheet.cell(3,col), header)
        sheet.cell(3,col).font = Font(name=font_family,bold=True,color='000000')
        sheet.cell(3,col).fill = PatternFill('solid',fgColor='E7E6E6')
    records = list(records)
    for rowno, record in enumerate(records,4):
        failed = any(value == 'FAIL' for value in record)
        for col, value in enumerate(record,1):
            cell = sheet.cell(rowno,col)
            _safe_cell(cell,value)
            cell.font = Font(name=font_family,size=10,color=RED if failed else '000000')
            cell.alignment = Alignment(vertical='top',wrap_text=True)
            if failed:
                cell.fill = PatternFill('solid',fgColor='FCE4D6')
            elif cell.value == MISSING or cell.value in ('INCOMPLETE','草稿'):
                cell.fill = PatternFill('solid',fgColor=AMBER)
    for row in sheet.iter_rows(min_row=3,max_row=max(3,sheet.max_row)):
        for cell in row:
            cell.alignment = Alignment(vertical='top',wrap_text=True)
    for col, header in enumerate(headers,1):
        sheet.column_dimensions[get_column_letter(col)].width = 28 if any(w in header for w in ('source','formula','substitution','path','reason','message','value')) else 18
    sheet.freeze_panes = 'A4'
    end = max(3,sheet.max_row)
    sheet.auto_filter.ref = f'A3:{get_column_letter(len(headers))}{end}'
    if records:
        table = Table(displayName=f'Results{index}',ref=sheet.auto_filter.ref)
        table.tableStyleInfo = TableStyleInfo(name='TableStyleMedium2',showRowStripes=False)
        sheet.add_table(table)
    sheet.print_title_rows = '1:3'
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = 'landscape' if len(headers)>6 else 'portrait'
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    return sheet


def _make_workbook(bundle, validation, destination, font_family):
    workbook = Workbook()
    workbook.remove(workbook.active)
    overview = [
        ['用途','结果归档；非结构求解器'], ['文件生成','本文件已生成，完整生成状态见manifest.json'],
        ['数据校核',validation.data_validation_status], ['上游验算项汇总',validation.upstream_check_summary],
        ['草稿状态','草稿' if validation.draft else '否'],
        ['draft_reasons',f'{len(validation.draft_reasons)}项；逐项内容见本表WARNING记录及validation.json'],
        ['schema_version',bundle.schema_version],
    ]
    overview.extend([f'project.{key}',value] for key,value in bundle.project.model_dump().items())
    overview.extend([f'provenance.{key}',value] for key,value in bundle.provenance.model_dump().items())
    overview.extend([f'{level}.{i.code} {i.path}',i.message] for level,issues in [('ERROR',validation.errors),('WARNING',validation.warnings)] for i in issues)
    supports = {s.node_id:s for s in bundle.model.supports}
    nodes = [[n.id,n.x_m,n.y_m,*([supports[n.id].ux,supports[n.id].uy,supports[n.id].rz] if n.id in supports else [None,None,None])] for n in bundle.model.nodes]
    loads = []
    for case in bundle.load_cases:
        for load in case.loads or [None]:
            loads.append([case.id,case.name,case.kind,case.source,
                          *([load.kind,load.target_id,*[getattr(load,key,None) for key in ('fx_kN','fy_kN','mz_kNm','qx_kN_m','qy_kN_m')]] if load else [None]*7)])
    def values(records):
        return [list(record.model_dump().values()) for record in records]
    tabs = [
        ('概况',['field','value'],overview),
        ('节点',['id','x_m','y_m','support_ux','support_uy','support_rz'],nodes),
        ('构件',['id','node_i','node_j','section_id','material_id','kind','release_i','release_j'],values(bundle.model.members)),
        ('材料',['id','name','E_MPa','fy_MPa','source'],values(bundle.model.materials)),
        ('截面',['id','name','shape','h_mm','b_mm','tw_mm','tf_mm','A_mm2','Ix_mm4','Iy_mm4','Wx_mm3','Wy_mm3','property_basis','source'],values(bundle.model.sections)),
        ('荷载',['case_id','case_name','case_kind','case_source','kind','target_id','fx_kN','fy_kN','mz_kNm','qx_kN_m','qy_kN_m'],loads),
        ('组合',['id','name','factors','limit_state','source'],values(bundle.combinations)),
        ('位移',['node_id','combination_id','ux_mm','uy_mm','rz_rad'],values(bundle.analysis.node_displacements)),
        ('支反力',['node_id','combination_id','fx_kN','fy_kN','mz_kNm'],values(bundle.analysis.reactions)),
        ('杆端力',['member_id','combination_id','Ni_kN','Vi_kN','Mi_kNm','Nj_kN','Vj_kN','Mj_kNm'],values(bundle.analysis.member_end_forces)),
        ('沿程内力',['member_id','combination_id','x_m','side','N_kN','V_kN','M_kNm'],values(bundle.analysis.member_samples)),
        ('验算',['id','target_id','combination_id','item','status','demand','limit','comparator','unit','utilization','formula_text','substitution','source','clause','trace_ids','na_reason'],values(bundle.checks)),
        ('追溯',['id','name','formula_text','inputs','intermediate','result','unit','source','result_path'],values(bundle.traces)),
    ]
    for index,(name,headers,rows) in enumerate(tabs,1):
        _sheet(workbook,name,headers,rows,font_family,index)
    workbook.save(destination)
    _preserve_numeric_precision(workbook, destination)


def _preserve_numeric_precision(workbook, destination):
    """Preserve input float serialization beyond openpyxl's 16-digit writer.

    Cells remain numeric; applications can impose their own precision when a
    user later edits and saves the workbook. The export itself retains values.
    """
    from lxml import etree
    namespace = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    temporary = destination.with_suffix('.xlsx.tmp')
    try:
        with ZipFile(destination) as source, ZipFile(temporary, 'w') as target:
            sheet_values = {}
            for index, sheet in enumerate(workbook, 1):
                sheet_values[f'xl/worksheets/sheet{index}.xml'] = {
                    cell.coordinate: repr(cell.value)
                    for row in sheet for cell in row if isinstance(cell.value, float)
                }
            for entry in source.infolist():
                data = source.read(entry.filename)
                if entry.filename in sheet_values and sheet_values[entry.filename]:
                    root = etree.fromstring(data)
                    supplied = sheet_values[entry.filename]
                    for cell in root.findall('.//s:c', namespace):
                        if cell.get('r') in supplied and cell.get('t') == 'n':
                            value = cell.find('s:v', namespace)
                            if value is not None:
                                value.text = supplied[cell.get('r')]
                    data = etree.tostring(root, encoding='utf-8')
                target.writestr(entry, data)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def export_calculation_book(bundle: DesignBundle, validation: ValidationReport,
                            out: Path, options: GenerationOptions) -> ExportOutcome:
    """Generate independent formats and keep completed files on conversion failure."""
    outcome = ExportOutcome()
    reports = Path(out) / 'reports'
    assets = reports / 'assets'
    assets.mkdir(parents=True, exist_ok=True)
    try:
        font_path, font_family = runtime.resolve_font()
    except Exception as exc:
        outcome.errors.append(f'中文字体解析失败：{exc}')
        return outcome
    diagram = assets / 'geometry.png'
    docx = reports / '计算书.docx'
    try:
        _geometry(bundle, diagram, font_path)
        outcome.files.append(diagram)
        _make_docx(bundle, validation, docx, diagram, font_family, font_path)
        outcome.files.append(docx)
    except Exception as exc:
        outcome.errors.append(f'计算书 DOCX 生成失败：{exc}')
    xlsx = reports / '设计结果表.xlsx'
    try:
        _make_workbook(bundle, validation, xlsx, font_family)
        outcome.files.append(xlsx)
    except Exception as exc:
        outcome.errors.append(f'设计结果表 XLSX 生成失败：{exc}')
    if options.include_pdf and docx in outcome.files:
        try:
            outcome.files.append(runtime.convert_docx_to_pdf(docx,reports,timeout=options.office_timeout_s))
        except Exception as exc:
            outcome.errors.append(f'计算书 PDF 转换失败：{exc}')
    if validation.draft:
        outcome.warnings.append('计算书为草稿；缺项及使用限制见第7章。')
    return outcome
