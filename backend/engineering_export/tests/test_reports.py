"""Verify the report's data boundary: no lost values, false verdicts or formulas."""
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from openpyxl import load_workbook
from steelmind_export.examples import analytic_bundle, demo_bundle, minimal_bundle
from steelmind_export.models import DesignBundle
from steelmind_export.results import GenerationOptions
from steelmind_export.validation import validate_bundle


def generate(tmp_path, data, **options):
    from steelmind_export.reports import export_calculation_book
    bundle = DesignBundle.model_validate(data)
    outcome = export_calculation_book(bundle, validate_bundle(bundle), tmp_path, GenerationOptions(**options))
    return outcome


def xml_document(path):
    with ZipFile(path) as z:
        return ET.fromstring(z.read('word/document.xml')), z.read('word/document.xml').decode()


def test_calculation_book_preserves_failure_editable_math_and_source(tmp_path):
    data = demo_bundle()
    outcome = generate(tmp_path, data, include_pdf=False)
    assert not outcome.errors
    assert {p.name for p in outcome.files} >= {'计算书.docx', '设计结果表.xlsx'}
    docx = tmp_path / 'reports/计算书.docx'
    root, xml = xml_document(docx)
    text = ''.join(root.itertext())
    for value in ['FAIL', 'C_DEMO_2', '270', '235', '草稿', 'demonstration',
                  '文件生成', '数据校核', '上游验算项汇总', 'manifest.json',
                  'H300×200×8×12', '1.13607e+08', 'node_i', 'T_DEMO_2']:
        assert value in text
    assert root.findall('.//{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath')
    assert 'w:val="C00000"' in xml
    assert 'tblHeader' in xml and 'cantSplit' in xml
    assert 'TOC' in xml
    assert (tmp_path / 'reports/assets/geometry.png').is_file()
    assert '结构通过' not in text


def test_workbook_keeps_exact_values_ids_units_and_safe_strings(tmp_path):
    data = analytic_bundle()
    data['project']['designer'] = '=HYPERLINK("https://example.com")'
    data['model']['sections'][0]['source'] = '+source'
    data['traces'][0]['inputs']['injected'] = '@external'
    outcome = generate(tmp_path, data, include_pdf=False)
    assert not outcome.errors
    book = load_workbook(tmp_path / 'reports/设计结果表.xlsx')
    assert set(book.sheetnames) >= {'概况','节点','构件','材料','截面','荷载','组合','位移','支反力','杆端力','沿程内力','验算','追溯'}
    assert book['节点']['A4'].value == 'N1'
    assert book['节点']['B5'].value == 6
    section = {c.value: c.column for c in book['截面'][3]}
    loads = {c.value: c.column for c in book['荷载'][3]}
    assert book['截面'].cell(4, section['Ix_mm4']).value == 113606784
    assert book['荷载'].cell(4, loads['qy_kN_m']).value == -10
    all_cells = [c for sheet in book for row in sheet for c in row]
    assert any(c.value == '=HYPERLINK("https://example.com")' and c.data_type == 's' for c in all_cells)
    assert any(c.value == '+source' and c.data_type == 's' for c in all_cells)
    assert not any(c.data_type == 'f' for c in all_cells)
    for name in ('节点', '构件', '验算'):
        assert book[name].freeze_panes == 'A4'
        assert book[name].auto_filter.ref
    for value in ['Wx_mm3', 'release_i', 'result_path', 'Ni_kN']:
        assert any(c.value == value for c in all_cells)


def test_truncated_input_is_draft_and_absence_never_zero_or_pass(tmp_path):
    outcome = generate(tmp_path, minimal_bundle(), include_pdf=False)
    assert not outcome.errors
    root, _ = xml_document(tmp_path / 'reports/计算书.docx')
    text = ''.join(root.itertext())
    assert 'INCOMPLETE' in text and '草稿' in text and '未提供' in text
    assert 'No analysis results supplied' in text
    assert '结构通过' not in text
    book = load_workbook(tmp_path / 'reports/设计结果表.xlsx')
    assert any(c.value == 'INCOMPLETE' for row in book['概况'] for c in row)


def test_na_reason_and_checks_without_numeric_determination_are_detailed(tmp_path):
    data = analytic_bundle()
    data['checks'].append(dict(id='NA_CHECK', target_id='B1', combination_id='ULS1',
        item='stability', status='NA', unit='ratio', na_reason='无面外约束信息'))
    data['checks'].append(dict(id='NO_NUMERIC', target_id='B1', combination_id='ULS1',
        item='custom', status='PASS', unit='ratio'))
    outcome = generate(tmp_path, data, include_pdf=False)
    assert not outcome.errors
    root, _ = xml_document(tmp_path / 'reports/计算书.docx')
    text = ''.join(root.itertext())
    assert text.count('NA_CHECK') >= 2 and 'NA(无面外约束信息)' in text
    assert text.count('NO_NUMERIC') >= 2 and '缺少数值判定' in text


def test_pdf_failure_preserves_successful_files_and_returns_error(tmp_path, monkeypatch):
    monkeypatch.setenv('STEELMIND_SOFFICE', '/missing/soffice')
    outcome = generate(tmp_path, minimal_bundle(), include_pdf=True)
    assert outcome.errors and 'LibreOffice' in outcome.errors[0]
    assert {p.name for p in outcome.files} >= {'计算书.docx', '设计结果表.xlsx'}
    assert all(p.is_file() for p in outcome.files)
    assert not any(p.suffix == '.pdf' for p in outcome.files)


def test_workbook_round_trips_every_reference_and_exact_result_number(tmp_path):
    """Dropping a dimension, release, factor, source, or result field breaks this."""
    import json
    data = analytic_bundle()
    data['model']['nodes'][1]['x_m'] = 6.123456789
    data['model']['members'][0]['release_j'] = False
    outcome = generate(tmp_path, data, include_pdf=False)
    assert not outcome.errors
    book = load_workbook(tmp_path / 'reports/设计结果表.xlsx')
    for tab, records in [
        ('构件', data['model']['members']), ('材料', data['model']['materials']),
        ('截面', data['model']['sections']), ('组合', data['combinations']),
        ('位移', data['analysis']['node_displacements']), ('支反力', data['analysis']['reactions']),
        ('杆端力', data['analysis']['member_end_forces']), ('沿程内力', data['analysis']['member_samples']),
        ('验算', data['checks']), ('追溯', data['traces']),
    ]:
        headers = [c.value for c in book[tab][3]]
        rows = list(book[tab].iter_rows(min_row=4, values_only=True))
        assert len(rows) == len(records)
        for source, row in zip(records, rows):
            exported = dict(zip(headers, row))
            assert source.keys() <= exported.keys()
            for key, expected in source.items():
                actual = exported[key]
                if isinstance(expected, (list, dict)) and expected:
                    assert json.loads(actual) == expected
                elif expected is None or expected == '' or expected == [] or expected == {}:
                    assert actual == '未提供'
                else:
                    assert actual == expected, (tab,key,actual,expected)


def test_detail_selection_retains_controlling_and_all_exceptions(tmp_path):
    data = analytic_bundle()
    low = deepcopy(data['checks'][0]); low.update(id='LOWER',demand=20,utilization=20/235)
    high = deepcopy(data['checks'][0]); high.update(id='HIGHER',demand=200,utilization=200/235)
    failed = deepcopy(data['checks'][0]); failed.update(id='FAIL_LOW',item='custom',status='FAIL',demand=250,utilization=250/235)
    worse = deepcopy(failed); worse.update(id='FAIL_HIGH',demand=300,utilization=300/235)
    data['checks'].extend([low,high,failed,worse])
    outcome = generate(tmp_path, data, include_pdf=False)
    assert not outcome.errors
    root, _ = xml_document(tmp_path / 'reports/计算书.docx')
    text = ''.join(root.itertext())
    assert text.count('LOWER') == 1
    for identifier in ('HIGHER', 'FAIL_LOW', 'FAIL_HIGH'):
        assert text.count(identifier) >= 2


def test_chapter_page_breaks_have_no_preceding_empty_spacer(tmp_path):
    generate(tmp_path, analytic_bundle(), include_pdf=False)
    root, _ = xml_document(tmp_path / 'reports/计算书.docx')
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    body=root.find('w:body',ns)
    for i,element in enumerate(body):
        style=element.find('w:pPr/w:pStyle',ns)
        if style is not None and style.get('{'+ns['w']+'}val')=='Heading1' and i:
            previous=body[i-1]
            assert previous.tag!='{'+ns['w']+'}p' or ''.join(previous.itertext()).strip(), 'Empty spacer before chapter can spill to a blank page'
