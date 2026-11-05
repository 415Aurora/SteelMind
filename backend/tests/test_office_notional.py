import sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np


def test_notional_load_uses_factored_floor_weight_and_eccentric_centroid():
 from office_second_order import notional_force_bound
 floors=[{'floor':1,'weight_kN':1000.,'centroid_m':[2.,3.]},{'floor':2,'weight_kN':500.,'centroid_m':[2.,3.]}]
 masters={'@F1':{'xyz_m':[1.,1.,3.]},'@F2':{'xyz_m':[1.,1.,6.]}}
 v=notional_force_bound(floors,masters)
 coefficient=math.sqrt(.2+1/2)/250
 assert math.isclose(v[0],1000*coefficient*1000)
 assert math.isclose(v[2],1000*coefficient*1000*3000)
 assert len(v)==6 and min(v)>=0


def test_floor_chord_solver_matches_condensed_geometric_stiffness():
 from test_office_solver import tiny
 from office_solver import solve_static,solve_modal
 b=tiny();b['diaphragm']='rigid_in_plane';b['analysis_options']={'column_chord':True}
 m={'total_mass_t':100.,'floors':[{'floor':1,'z_m':3.,'centroid_m':[0.,0.],'mass_t':100.,'polar_mass_t_m2':1000.}]}
 case={'case_id':'P_H','member_uniform_kN_m':{},'nodal_loads_kN_kNm':{'top':[10,0,-1000,0,0,0]}}
 r=solve_static(b,case,method='PDelta',mass_source=m);assert r['ok'],r
 F=np.array(solve_modal(b,m)['floor_flexibility_mm_N']);K=np.diag([1e6/3000,1e6/3000,0.]);u=np.linalg.solve(np.eye(3)-F@K,F@np.array([10000.,0.,0.]))
 actual=r['analysis']['master_results']['@F1']['displacement_mm_rad'][0]
 assert math.isclose(actual,u[0],rel_tol=1e-7)
 assert len(r['analysis']['members'][0]['segment_end_actions_kN_kNm'])==1


def test_column_chord_pdelta_audit_uses_solver_equilibrium_not_displaced_beam_loads():
 from test_office_solver import tiny
 from office_solver import solve_static
 b=tiny();b['analysis_options']={'column_chord':True}
 r=solve_static(b,{'case_id':'PH','member_uniform_kN_m':{},'nodal_loads_kN_kNm':{'top':[10,0,-1000,0,0,0]}},method='PDelta')
 assert r['ok'],r
 audit=r['numerical_audit'];assert audit['moment_tolerance_kNm']<.001
 assert 'column geometric' in audit['moment_method']
 assert max(abs(x) for x in audit['moment_residual_kNm'])<1e-6
