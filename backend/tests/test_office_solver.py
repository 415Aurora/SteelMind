import sys,math,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_explicit_model import ExplicitModel


def tiny():
 t=ExplicitModel().model();t['Members'][0].update(physical_member_id='C',unbraced_length_m=3.,length_m=3.)
 return {'tables':t,'diaphragm':'none','parameters':{},'assumptions':[]}


def test_general_static_horizontal_cantilever_and_global_actions():
 from office_solver import solve_static
 b=tiny();c={'case_id':'H','member_uniform_kN_m':{},'nodal_loads_kN_kNm':{'top':[10,0,0,0,0,0]}}
 r=solve_static(b,c,segments=4);assert r['ok'],r
 top=next(n for n in r['analysis']['nodes'] if n['node_id']=='top')
 assert math.isclose(top['displacement_mm_rad'][0],10000*3000**3/(3*206000*395720000),rel_tol=1e-7)
 assert r['numerical_audit']['status']=='PASS'


def test_pdelta_increases_lateral_displacement_and_preserves_load_case():
 from office_solver import solve_static
 b=tiny();c={'case_id':'P_H','member_uniform_kN_m':{},'nodal_loads_kN_kNm':{'top':[10,0,-1000,0,0,0]}}
 a=solve_static(b,c,segments=8);d=solve_static(b,c,method='PDelta',segments=8)
 assert a['ok'] and d['ok'],d
 assert d['analysis']['nodes'][1]['displacement_mm_rad'][0]>a['analysis']['nodes'][1]['displacement_mm_rad'][0]
 assert d['case_id']=='P_H' and d['method']=='PDelta'


def test_rigid_floor_modal_participation_and_mass_total():
 from office_contracts import reference_case
 from office_loads import build_load_cases,build_mass_source
 from office_solver import solve_modal
 b=reference_case();m=build_mass_source(b,build_load_cases(b));r=solve_modal(b,m,segments=2)
 assert r['ok'],r
 assert sum(v['effective_mass_x_t'] for v in r['modes'])/m['total_mass_t']>=.90
 assert sum(v['effective_mass_y_t'] for v in r['modes'])/m['total_mass_t']>=.90
 assert all(v['period_s']>0 and math.isfinite(v['period_s']) for v in r['modes'])


def test_condensed_floor_modes_match_cantilever_period():
 from office_solver import solve_modal
 b=tiny();b['diaphragm']='rigid_in_plane'
 m={'total_mass_t':100.,'floors':[{'floor':1,'z_m':3.,'centroid_m':[0.,0.],'mass_t':100.,'polar_mass_t_m2':1000.}]}
 r=solve_modal(b,m,segments=4);assert r['ok'],r
 mode=max(r['modes'],key=lambda v:v['effective_mass_x_t'])
 assert math.isclose(mode['period_s'],2*math.pi*math.sqrt(100*3000**3/(3*206000*395720000)),rel_tol=1e-7)
