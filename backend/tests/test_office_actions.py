import sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def test_spectrum_damping_and_adopted_period_are_explicit():
 from office_spectrum import spectrum_alpha,cqc_matrix,cqc
 import numpy as np
 assert math.isclose(spectrum_alpha(.5,.9,.04),.04277777777777778,rel_tol=1e-10)
 assert spectrum_alpha(1.,.9,.04)>spectrum_alpha(1.,.75,.04)
 r=cqc_matrix([1.,1.,.2],.04);assert np.allclose(r,r.T);assert np.allclose(np.diag(r),1)
 assert math.isclose(cqc([2.,3.],cqc_matrix([1.,1.],.04)),5.)
 assert math.isclose(cqc([2.,-3.],cqc_matrix([1.,1.],.04)),1.)


def test_wind_face_mapping_conserves_force_and_overturning():
 from office_contracts import reference_case
 from office_actions import build_wind_cases,wind_height_factor
 b=reference_case();c=build_wind_cases(b)
 assert math.isclose(wind_height_factor(16),.668,abs_tol=1e-10)
 assert set(c)=={'W_XP','W_XN','W_YP','W_YN'}
 for v in c.values():assert v['audit']['status']=='PASS'
 assert math.isclose(c['W_YP']['audit']['total_force_kN'][1],.35*1.3*38*(.65*15+(.65+.668)/2),rel_tol=1e-9)
 assert math.isclose(c['W_YP']['audit']['total_force_kN'][1],-c['W_YN']['audit']['total_force_kN'][1],rel_tol=1e-9)


def test_combinations_have_current_factors_and_separate_sls():
 from office_combinations import build_combinations
 combos=build_combinations();uls=[c for c in combos if c['limit_state']=='ULS'];sls=[c for c in combos if c['limit_state']=='SLS']
 assert uls and sls
 assert all(c['factors']['G'] in (1.,1.3) for c in uls)
 assert any(c['factors'].get('W_XP')==1.5 for c in uls)
 assert all(max(c['factors'].values())<=1 for c in sls)
 assert any(c['limit_state']=='SEISMIC' and c['earthquake_factor']==1.4 for c in combos)


def test_wind_includes_roof_suction_without_losing_vertical_equilibrium():
 from office_contracts import reference_case
 from office_actions import build_wind_cases
 b=reference_case();c=build_wind_cases(b)
 for case in c.values():
  assert case['audit']['total_force_kN'][2]>0
  assert case['member_uniform_kN_m']
  assert case['wind_parameters']['normative_evidence_status']=='verified_official_table_image'
