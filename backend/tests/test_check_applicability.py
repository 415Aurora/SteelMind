"""Scope decisions must use actual force fields, not labels or desired outcomes."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_explicit_model import ExplicitModel
from explicit_model import run_explicit_model


def checks(tables):
    result = run_explicit_model(tables)
    assert result['ok'], result
    return result, {c['item']: c for c in result['code_checks']['members'][0]['checks']}


def beam():
    t = ExplicitModel().model()
    t['Nodes'][1].update(x=7, y=0, z=0, **dict.fromkeys(['ux','uy','uz','rx','ry','rz'],1))
    t['Members'][0].update(member_type='beam', release_i=1, release_j=1)
    t['Sections'][0] = dict(section_id='BOX',section_name='H550x200x6x10',shape='H',depth_mm=550,width_mm=200,tw_mm=6,tf_mm=10,area_mm2=7180,Ix_mm4=366071833.3333333,Iy_mm4=13342873.333333334)
    return t


def test_zero_axial_compression_is_not_pending_buckling():
    r, c = checks(beam())
    assert c['compression_stability']['status'] == 'NA'
    assert c['compression_stability']['inputs']['max_compression_kN'] <= 1e-8
    assert c['lateral_torsional_stability']['status'] == 'PENDING'  # no slab restraint
    assert r['upstream_check_summary'] == 'INCOMPLETE'


def test_box_column_deformation_and_beam_ltb_are_not_duplicate_pending_checks():
    _, c = checks(ExplicitModel().model())
    assert c['member_deformation_limit']['status'] == 'NA'
    assert c['lateral_torsional_stability']['status'] == 'NA'
    assert c['compression_stability']['status'] == 'PENDING'
    assert c['plate_local_stability']['status'] == 'PENDING'  # 38 > 45*sqrt(235/355)
    assert 'effective' in c['plate_local_stability']['reason']


def test_h_flange_is_calculated_but_slender_web_is_not_falsely_passed():
    _, c = checks(beam())
    assert c['flange_width_thickness']['status'] == 'PASS'
    assert abs(c['flange_width_thickness']['demand']-9.7) < 1e-9
    assert c['plate_local_stability']['status'] == 'PENDING'
    assert c['web_width_thickness']['status'] == 'PASS'  # S4 only; not entire local stability
    assert c['web_additional_stability']['status'] == 'PENDING'  # >80 eps


def test_no_compression_is_based_on_interior_force_not_endpoint_label():
    t = ExplicitModel().model()
    t['Members'][0]['member_type'] = 'beam'
    _, c = checks(t)
    assert c['compression_stability']['status'] == 'PENDING'


def test_oversized_flange_is_incomplete_never_silently_passed():
    t = beam();t['Sections'][0].update(width_mm=600)
    _, c = checks(t)
    assert c['flange_width_thickness']['status'] == 'PENDING'
    assert c['plate_local_stability']['status'] == 'PENDING'


def test_approved_orientation_changes_strong_axis_deflection_and_keeps_input_immutable():
    import copy
    t = beam();before = copy.deepcopy(t)
    t['Members'][0]['orientation_deg'] = 90
    old, _ = checks(t)
    t['Members'][0]['orientation_deg'] = 0
    new, c = checks(t)
    old_c = next(v for v in old['code_checks']['members'][0]['checks'] if v['item']=='beam_deflection')
    assert abs(old_c['demand']/c['beam_deflection']['demand'] - 366071833.3333333/13342873.333333334) < 1e-6
    assert before['Members'][0].get('orientation_deg') is None
    assert new['code_checks']['members'][0]['completed_check_status'] == 'PASS'


def test_welded_h_alias_uses_actual_plate_rules():
    t = beam();t['Sections'][0]['shape'] = 'H-welded'
    _, c = checks(t)
    assert c['flange_width_thickness']['status'] == 'PASS'
    assert c['web_width_thickness']['status'] == 'PASS'
    assert c['web_additional_stability']['status'] == 'PENDING'


def test_box_beam_does_not_use_more_permissive_column_s4_limit():
    t = beam();t['Sections'][0].update(shape='BOX',depth_mm=370,width_mm=370,tw_mm=10,tf_mm=10)
    _, c = checks(t)
    assert c['plate_local_stability']['status'] == 'PENDING'  # 35 > 42 eps, but <45 eps
    assert abs(c['plate_local_stability']['limit']-42*(235/355)**.5) < 1e-9


def test_report_representatives_keep_material_only_pending_without_crashing():
    from explicit_outputs import representative_members
    records=[{'member_id':'unknown','section_id':'S','checks':[{'item':'material_strength','status':'PENDING'}]}]
    assert representative_members(records) == records


def test_pending_geometry_screen_is_not_shown_as_failed_utilization():
    from explicit_viewer import build_scene
    t=ExplicitModel().model();r=run_explicit_model(t)
    scene=build_scene(t,r)
    assert scene['member_utilizations']['C001'] < 1
    assert scene['member_statuses']['C001'] is None


def test_closed_box_beam_does_not_inherit_box_column_ltb_exemption():
    t=beam();t['Sections'][0].update(shape='BOX')
    _, c=checks(t)
    assert c['lateral_torsional_stability']['status']=='PENDING'
