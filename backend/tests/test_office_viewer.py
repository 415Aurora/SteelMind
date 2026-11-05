import sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))


def test_viewer_recovers_non_gravity_distributed_load_moment():
 from test_explicit_model import ExplicitModel
 from office_solver import solve_static
 from explicit_viewer import force_envelope
 t=ExplicitModel().model();t['Nodes'][1].update(x=6,y=0,z=0,**dict.fromkeys(['ux','uy','uz','rx','ry','rz'],1));t['Members'][0].update(member_type='beam',release_i=1,release_j=1,physical_member_id='B',unbraced_length_m=6.)
 r=solve_static({'tables':t,'diaphragm':'none'},{'case_id':'W','member_uniform_kN_m':{'C001':[0,10,0]},'nodal_loads_kN_kNm':{}})
 assert r['ok'],r
 assert math.isclose(abs(force_envelope(r['analysis']['members'][0])['My_kNm']),45.,rel_tol=1e-7)


def test_office_viewer_replaces_inherited_selfweight_banner(monkeypatch):
 import explicit_viewer
 from office_viewer import build_office_viewer
 monkeypatch.setattr(explicit_viewer,'build_html',lambda *a:({},"const withAnalysis=M.analysis_scope==='self_weight';document.querySelector('.notice').textContent=withAnalysis?'仅框架自重（1.0G），规范验算未闭合。各内力分量的控制位置可能不同。':'几何预览';"))
 run={'bundle':{'tables':{}},'analysis':{'case_results':{'W_XP':{'analysis':{'members':[]}}}},'code_checks':{'members':[]},'design_status':'PASS'}
 _,document=build_office_viewer(run,'W_XP')
 assert '仅框架自重（1.0G）' not in document
 assert 'W_XP' in document and '构造' in document
