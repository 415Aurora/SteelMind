from zipfile import ZipFile
from xml.etree import ElementTree as ET

from pypdf import PdfReader
import pytest

from steelmind_export import generate_calculation_book
from steelmind_export.examples import minimal_bundle, analytic_bundle
from steelmind_export.runtime import ConversionError, find_soffice

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


def test_cover_has_no_inherited_theme_border_or_font(tmp_path):
    result = generate_calculation_book(minimal_bundle(), {'include_pdf': False}, tmp_path)
    with ZipFile(tmp_path / result.run_id / 'reports/计算书.docx') as z:
        styles = ET.fromstring(z.read('word/styles.xml'))
    for name in ['Title', 'Heading1', 'Heading2', 'Normal']:
        style = styles.find(f"w:style[@w:styleId='{name}']", NS)
        assert style is not None
        assert style.find('.//w:pBdr', NS) is None
        for fonts in style.findall('.//w:rFonts', NS):
            assert not any(key.endswith('Theme') for key in fonts.attrib)


def test_excel_cell_limit_never_silently_truncates_source(tmp_path):
    bundle = minimal_bundle()
    bundle['model']['materials'][0]['source'] = '完整来源' * 9000
    result = generate_calculation_book(bundle, {'include_pdf': False}, tmp_path)
    assert result.generation_status == 'partial'
    assert any('32767' in e for e in result.errors)
    assert any(a.name.endswith('.docx') for a in result.artifacts)
    assert not any(a.name.endswith('.xlsx') for a in result.artifacts)


def test_fail_without_numeric_result_is_red_in_summary(tmp_path):
    bundle = analytic_bundle()
    bundle['checks'].append(dict(id='FAIL_MISSING_NUMERIC', target_id='B1', combination_id='ULS1', item='stability', status='FAIL', unit='ratio'))
    result = generate_calculation_book(bundle, {'include_pdf': False}, tmp_path)
    with ZipFile(tmp_path / result.run_id / 'reports/计算书.docx') as z:
        root = ET.fromstring(z.read('word/document.xml'))
    rows = root.findall('.//w:tr', NS)
    row = next(r for r in rows if 'FAIL_MISSING_NUMERIC' in ''.join(r.itertext()))
    assert any(c.attrib.get('{'+NS['w']+'}val') == 'C00000' for c in row.findall('.//w:color', NS))


def test_real_pdf_keeps_searchable_chinese_content(tmp_path):
    try:
        find_soffice()
    except ConversionError:
        pytest.skip('LibreOffice not installed')
    result = generate_calculation_book(minimal_bundle(), {}, tmp_path)
    assert result.generation_status == 'success', result.errors
    text = '\n'.join(p.extract_text() for p in PdfReader(tmp_path / result.run_id / 'reports/计算书.pdf').pages)
    assert '钢结构计算书与结果归档' in text
    assert '数据校核' in text
