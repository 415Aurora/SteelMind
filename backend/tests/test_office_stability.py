import sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def test_column_phi_has_complete_c_and_d_piecewise_curves():
 from office_stability import compression_phi
 for curve in ('a','b','c','d'):
  assert compression_phi(0,355,206000,curve)==1
  assert 0<compression_phi(150,355,206000,curve)<compression_phi(50,355,206000,curve)<1
 assert compression_phi(100,355,206000,'d')<compression_phi(100,355,206000,'c')


def test_ltb_uses_squared_grade_factor_and_physical_length():
 from office_contracts import reference_case,geometry_model
 from office_stability import beam_phi
 s=geometry_model(reference_case())['sections']['SEC_HN600']
 a=beam_phi(s,8000,355);b=beam_phi(s,2000,355)
 assert a['phi_b']<b['phi_b'];assert a['grade_factor']==235/355
 assert a['beta_b']==.69 and 0<a['phi_b']<=1


def test_box_effective_section_is_separate_and_preserves_authority():
 from office_contracts import reference_case,geometry_model
 from office_stability import box_effective_section
 import copy
 s=geometry_model(reference_case())['sections']['SEC_COL_BOX_ASSUMED'];before=copy.deepcopy(s);e=box_effective_section(s,355)
 assert s==before and 0<e['A_mm2']<s['A'] and 0<e['Iz_mm4']<s['Iz']
 assert e['basis'].startswith('GB50017 8.4.2')


def test_amended_q355_strength_thickness_groups():
 from office_stability import material_strength
 expected=[(10,305,175,355),(17,295,170,345),(50,290,165,335),(70,280,160,325),(90,270,155,315)]
 for t,f,fv,fy in expected:
  r=material_strength('Q355B',t)
  assert (r['f_MPa'],r['fv_MPa'],r['fy_MPa'])==(f,fv,fy)
