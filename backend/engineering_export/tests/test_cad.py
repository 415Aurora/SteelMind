"""CAD boundary tests: editable geometry, true dimensions, printed size and conversion integrity."""
from copy import deepcopy
import json
from pathlib import Path

import ezdxf
import pytest
from pypdf import PdfReader
from steelmind_export.examples import minimal_bundle, demo_bundle
from steelmind_export.models import DesignBundle
from steelmind_export.results import GenerationOptions
from steelmind_export.validation import validate_bundle


def generate(tmp_path, data=None, **options):
    from steelmind_export.cad import export_design_files
    bundle = DesignBundle.model_validate(data or minimal_bundle())
    return export_design_files(bundle, validate_bundle(bundle), tmp_path, GenerationOptions(**options))


def texts(doc):
    return [e.dxf.text if e.dxftype() == 'TEXT' else e.plain_text()
            for layout in doc.layouts for e in layout if e.dxftype() in ('TEXT', 'MTEXT')]


def test_saved_dxf_retains_mm_endpoints_true_dimensions_and_a3_paperspace(tmp_path):
    outcome = generate(tmp_path, include_pdf=False)
    assert not outcome.errors
    paths = [p for p in outcome.files if p.suffix == '.dxf']
    assert len(paths) >= 3
    assert {p.name[:2] for p in paths} >= {'01', '02', '03'}
    doc = ezdxf.readfile(next(p for p in paths if p.name.startswith('01')))
    assert doc.dxfversion == 'AC1032' and doc.units == 4
    lines = list(doc.modelspace().query('LINE[layer=="S-OUTLINE"]'))
    assert any(tuple(e.dxf.start) == (0,0,0) and tuple(e.dxf.end) == (6000,0,0) for e in lines)
    dimensions = list(doc.modelspace().query('DIMENSION'))
    assert dimensions and any(d.get_measurement() == 6000 for d in dimensions)
    assert all(d.dxf.text in ('', '<>') for d in dimensions)
    layout = doc.layouts.get('A3')
    assert (layout.dxf.paper_width, layout.dxf.paper_height) == (420,297)
    viewport = [v for v in layout.viewports() if v.dxf.id > 1][0]
    assert viewport.dxf.view_height / viewport.dxf.height in (50,100,200,500,1000,2000)
    assert doc.layers.get('P-VPORT').dxf.plot == 0
    assert any('草稿' in t and '非施工图' in t for t in texts(doc))
    all_text = '\n'.join(t for p in paths for t in texts(ezdxf.readfile(p)))
    for value in ('N1','N2','B1','H300','Q235','A_mm2','Ix_mm4','Iy_mm4','Wx_mm3','Wy_mm3','idealized'):
        assert value in all_text
    audit = json.loads((tmp_path/'drawing_audit.json').read_text())
    assert audit['dwg']['status'] == 'disabled'
    assert audit['font']['file']
    assert all(not sheet['errors'] for sheet in audit['sheets'])
    assert all(sheet['modelunits'] == 4 and sheet['paper_mm'] == [420,297] for sheet in audit['sheets'])
    assert all(m['actual_mm'] == pytest.approx(m['expected_mm']) for s in audit['sheets'] for m in s['measurements'])


def test_pdf_is_rendered_from_saved_layout_and_has_exact_a3_size(tmp_path):
    outcome = generate(tmp_path)
    assert not outcome.errors
    pdfs = [p for p in outcome.files if p.suffix == '.pdf']
    dxfs = [p for p in outcome.files if p.suffix == '.dxf']
    assert len(pdfs) == len(dxfs) >= 3
    for pdf in pdfs:
        assert pdf.read_bytes().startswith(b'%PDF-')
        page = PdfReader(pdf).pages[0]
        assert float(page.mediabox.width) == pytest.approx(420/25.4*72, abs=2)
        assert float(page.mediabox.height) == pytest.approx(297/25.4*72, abs=2)


def test_many_assignments_sections_long_metadata_are_paginated_without_loss(tmp_path):
    data = minimal_bundle()
    data['project']['name'] = '超长项目名称与真实坐标保留' * 12
    data['model']['nodes'][0].update(x_m=-4.0, y_m=-2.0)
    data['model']['nodes'][1].update(x_m=2.0, y_m=1.0)
    for n in range(1,15):
        section = deepcopy(data['model']['sections'][0]); section.update(id=f'S{n}', name=f'截面{n}', property_basis='catalog', source='正式目录来源 ' * 12)
        data['model']['sections'].append(section)
        data['model']['members'].append(dict(id=f'M{n}', node_i='N1',node_j='N2',section_id=f'S{n}',material_id='Q235',kind='beam'))
    outcome = generate(tmp_path, data, include_pdf=False)
    assert not outcome.errors
    paths = [p for p in outcome.files if p.suffix == '.dxf']
    assert len([p for p in paths if '截面示意' in p.name]) == 15
    all_text = '\n'.join(t for p in paths for t in texts(ezdxf.readfile(p)))
    for n in range(1,15):
        assert f'M{n}' in all_text and f'S{n}' in all_text
    assert len([p for p in paths if '构件表' in p.name]) >= 2
    doc = ezdxf.readfile(next(p for p in paths if p.name.startswith('01')))
    assert any(tuple(e.dxf.start) == (-4000,-2000,0) and tuple(e.dxf.end) == (2000,1000,0)
               for e in doc.modelspace().query('LINE[layer=="S-OUTLINE"]'))
    assert '简化示意未表示轧制圆角' in all_text


def test_missing_oda_is_explicit_partial_preserves_dxf(tmp_path, monkeypatch):
    monkeypatch.setenv('STEELMIND_ODA','/missing/ODAFileConverter')
    outcome = generate(tmp_path, include_pdf=False, include_dwg=True)
    assert outcome.errors and 'ODA' in '\n'.join(outcome.errors)
    assert len([p for p in outcome.files if p.suffix == '.dxf']) >= 3
    assert not any(p.suffix == '.dwg' for p in outcome.files)


@pytest.mark.parametrize('corruption', ['units','override','text','scale','layer','font'])
def test_roundtrip_rejects_changes_to_drawing_semantics(tmp_path, corruption):
    from steelmind_export.cad import compare_roundtrip
    outcome = generate(tmp_path, include_pdf=False)
    original = next(p for p in outcome.files if p.suffix == '.dxf' and p.name.startswith('01'))
    doc = ezdxf.readfile(original)
    if corruption == 'units': doc.units = 6
    elif corruption == 'override': next(iter(doc.modelspace().query('DIMENSION'))).dxf.text = '6000'
    elif corruption == 'text': next(iter(doc.modelspace().query('TEXT'))).dxf.text = 'corrupted'
    elif corruption == 'scale': [v for v in doc.layouts.get('A3').viewports() if v.dxf.id > 1][0].dxf.view_height *= 2
    elif corruption == 'layer': doc.layers.get('S-OUTLINE').dxf.lineweight = 70
    else: doc.styles.get('STEELMIND').dxf.font = 'missing.ttf'
    changed = tmp_path/'changed.dxf'; doc.saveas(changed)
    assert compare_roundtrip(original, changed)


def test_native_section_dimensions_are_real_h_b_tw_tf_and_catalog_values_remain(tmp_path):
    data = minimal_bundle(); data['model']['sections'][0].update(property_basis='catalog', A_mm2=7000.0, source='目录页23 原始舍入值')
    outcome = generate(tmp_path, data, include_pdf=False)
    assert not outcome.errors
    doc = ezdxf.readfile(next(p for p in outcome.files if '截面示意' in p.name))
    assert sorted(d.get_measurement() for d in doc.modelspace().query('DIMENSION')) == [8,12,200,300]
    content = '\n'.join(texts(doc))
    assert '7000.0' in content and 'catalog' in content
    assert all(e.dxf.text in ('','<>') for e in doc.modelspace().query('DIMENSION'))


def test_fail_warning_is_on_every_title_strip_and_supports_encode_actual_dofs(tmp_path):
    data = demo_bundle()
    outcome = generate(tmp_path, data, include_pdf=False)
    assert not outcome.errors
    for path in (p for p in outcome.files if p.suffix == '.dxf'):
        assert any('FAIL' in t and '警告' in t for t in texts(ezdxf.readfile(path)))
    doc=ezdxf.readfile(next(p for p in outcome.files if p.name.startswith('01') and p.suffix=='.dxf'))
    for support in data['model']['supports']:
        assert any(f"{support['node_id']} ux={int(support['ux'])} uy={int(support['uy'])} rz={int(support['rz'])}" in t for t in texts(doc))


def test_unavailable_font_and_unrenderable_glyph_are_explicit_failures(tmp_path, monkeypatch):
    monkeypatch.setenv('STEELMIND_FONT','/missing/font.ttc')
    outcome=generate(tmp_path/'missing', include_pdf=True)
    assert outcome.errors and '字体' in '\n'.join(outcome.errors)
    monkeypatch.delenv('STEELMIND_FONT')
    data=minimal_bundle(); data['project']['name']='rare glyph \U0010ffff'
    outcome=generate(tmp_path/'glyph', data, include_pdf=True)
    assert any('缺少字形' in e for e in outcome.errors)
    assert any(p.suffix=='.dxf' for p in outcome.files)
    assert not any(p.suffix=='.pdf' for p in outcome.files)


def test_large_frame_tiles_keep_all_model_lines_and_label_extents(tmp_path):
    data=minimal_bundle()
    data['model']['nodes'].append(dict(id='N3',x_m=60.0,y_m=0.0))
    data['model']['members'].append(dict(id='B2',node_i='N2',node_j='N3',section_id='H300',material_id='Q235',kind='beam'))
    outcome=generate(tmp_path,data,include_pdf=False)
    assert not outcome.errors
    paths=[p for p in outcome.files if p.suffix=='.dxf' and p.name.startswith('01')]
    assert len(paths)>1
    for path in paths:
        doc=ezdxf.readfile(path)
        assert len(doc.modelspace().query('LINE[layer=="S-OUTLINE"]'))==2
        assert any('分幅' in t and '视窗 mm' in t for t in texts(doc))


def test_roundtrip_rejects_entity_lineweight_corruption(tmp_path):
    from steelmind_export.cad import compare_roundtrip
    outcome=generate(tmp_path,include_pdf=False)
    original=next(p for p in outcome.files if p.suffix=='.dxf' and p.name.startswith('01'))
    doc=ezdxf.readfile(original)
    next(iter(doc.modelspace().query('LINE[layer=="S-OUTLINE"]'))).dxf.lineweight=80
    changed=tmp_path/'lineweight.dxf'; doc.saveas(changed)
    assert compare_roundtrip(original,changed)


def test_long_metadata_and_section_names_stay_inside_paper_frame(tmp_path):
    from ezdxf import bbox
    data=minimal_bundle()
    data['project'].update(name='项目名称' * 55, designer='设计者姓名' * 20, institution='大学学院机构' * 22)
    data['model']['sections'][0]['name']='长截面名称' * 22
    outcome=generate(tmp_path,data)
    assert not outcome.errors
    for path in (p for p in outcome.files if p.suffix=='.dxf'):
        doc=ezdxf.readfile(path)
        for entity in doc.layouts.get('A3').query('TEXT'):
            bounds=bbox.extents([entity])
            if not bounds.has_data: continue
            assert bounds.extmax.x<=410.5, (path.name,entity.dxf.text,bounds.extmax.x)
            assert bounds.extmin.y>=9.5, (path.name,entity.dxf.text,bounds.extmin.y)


@pytest.mark.parametrize('mode',['valid_mock','bad_header','bad_roundtrip'])
def test_external_conversion_publishes_only_after_header_and_real_roundtrip_checks(tmp_path, monkeypatch, mode):
    """Only ODA process execution is mocked; comparison reads real saved DXFs."""
    import shutil
    import subprocess
    from steelmind_export import cad
    monkeypatch.setattr(cad,'_find_oda',lambda:'/operator/ODAFileConverter')
    def external(args, **kwargs):
        assert kwargs['shell'] is False and kwargs['timeout'] <= 180
        assert args[3]=='ACAD2018'
        source,target=Path(args[1]),Path(args[2])
        if args[4]=='DWG':
            (target/'drawing.dwg').write_bytes((b'AC1032' if mode!='bad_header' else b'AC1027')+b'\x00'*100)
        else:
            original=source.parent/'in/drawing.dxf'; back=target/'drawing.dxf'
            shutil.copyfile(original,back)
            if mode=='bad_roundtrip':
                doc=ezdxf.readfile(back); doc.units=6; doc.saveas(back)
        return subprocess.CompletedProcess(args,0,b'',b'')
    monkeypatch.setattr(cad.subprocess,'run',external)
    outcome=generate(tmp_path,include_pdf=False,include_dwg=True)
    dwgs=[p for p in outcome.files if p.suffix=='.dwg']
    if mode=='valid_mock':
        assert not outcome.errors
        assert len(dwgs)==len([p for p in outcome.files if p.suffix=='.dxf'])
    else:
        assert outcome.errors and not dwgs
        assert any(p.suffix=='.dxf' for p in outcome.files)


def test_demo_member_and_node_label_bboxes_do_not_collide(tmp_path):
    """Regression: midpoint-anchored rotated assignments overlapped storeys."""
    from ezdxf import bbox
    outcome=generate(tmp_path,demo_bundle(),include_pdf=False)
    assert not outcome.errors
    path=next(p for p in outcome.files if p.suffix=='.dxf' and p.name.startswith('02_001'))
    doc=ezdxf.readfile(path)
    labels=list(doc.modelspace().query('TEXT[layer=="S-TEXT"]'))
    collisions=[]
    for i,a in enumerate(labels):
        aa=bbox.extents([a])
        for b in labels[i+1:]:
            bb=bbox.extents([b])
            if aa.extmin.x < bb.extmax.x and aa.extmax.x > bb.extmin.x and aa.extmin.y < bb.extmax.y and aa.extmax.y > bb.extmin.y:
                collisions.append((a.dxf.text,b.dxf.text))
    assert not collisions, collisions
    for member in demo_bundle()['model']['members']:
        assert member['id']+' / '+member['section_id'] in [e.dxf.text for e in labels]


@pytest.mark.parametrize('change',['member_endpoint','section_vertex','circle','dimension_anchor','text_position','viewport_twist'])
def test_roundtrip_rejects_geometry_changes_without_changed_counts_or_measurements(tmp_path,change):
    from steelmind_export.cad import compare_roundtrip
    outcome=generate(tmp_path,include_pdf=False)
    needle='截面示意' if change=='section_vertex' else '01_001'
    original=next(p for p in outcome.files if p.suffix=='.dxf' and needle in p.name)
    doc=ezdxf.readfile(original); model=doc.modelspace()
    if change=='member_endpoint': next(iter(model.query('LINE[layer=="S-OUTLINE"]'))).dxf.end=(123456,654321,0)
    elif change=='section_vertex':
        poly=next(iter(model.query('LWPOLYLINE[layer=="S-OUTLINE"]')))
        points=list(poly.get_points()); p=list(points[0]); p[0]+=12; points[0]=p; poly.set_points(points)
    elif change=='circle': next(iter(model.query('CIRCLE'))).dxf.radius+=12
    elif change=='dimension_anchor':
        dim=next(iter(model.query('DIMENSION'))); dim.dxf.defpoint=dim.dxf.defpoint+(0,500,0)
    elif change=='text_position':
        text=next(iter(model.query('TEXT'))); text.dxf.insert=text.dxf.insert+(123,456,0)
    else: [v for v in doc.layouts.get('A3').viewports() if v.dxf.id>1][0].dxf.view_twist_angle=30
    changed=tmp_path/'geometry.dxf'; doc.saveas(changed)
    assert compare_roundtrip(original,changed)


def test_roundtrip_accepts_unchanged_reordered_geometry_and_numeric_noise(tmp_path):
    from steelmind_export.cad import compare_roundtrip
    outcome=generate(tmp_path,include_pdf=False)
    original=next(p for p in outcome.files if p.suffix=='.dxf' and p.name.startswith('01_001'))
    doc=ezdxf.readfile(original)
    doc.modelspace().entity_space.entities.reverse()
    line=next(iter(doc.modelspace().query('LINE[layer=="S-OUTLINE"]')))
    line.dxf.end=line.dxf.end+(0.000002,0,0)
    changed=tmp_path/'same.dxf'; doc.saveas(changed)
    assert not compare_roundtrip(original,changed)


@pytest.mark.parametrize('prefix', ['01_001', '02_001'])
def test_default_demo_support_text_has_clearance_from_adjacent_labels(tmp_path, prefix):
    from ezdxf import bbox
    outcome = generate(tmp_path, demo_bundle(), include_pdf=False)
    path = next(p for p in outcome.files if p.suffix == '.dxf' and p.name.startswith(prefix))
    doc = ezdxf.readfile(path)
    labels = [e for e in doc.modelspace().query('TEXT') if e.dxf.layer in ('S-TEXT','S-SUPPORT')]
    for i, a in enumerate(labels):
        aa = bbox.extents([a])
        for b in labels[i+1:]:
            bb = bbox.extents([b])
            if aa.extmin.y < bb.extmax.y and aa.extmax.y > bb.extmin.y:
                assert aa.extmax.x < bb.extmin.x or bb.extmax.x < aa.extmin.x, (a.dxf.text, b.dxf.text)
