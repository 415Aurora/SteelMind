import sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np


def test_free_warping_uniform_torsion_reduces_to_saint_venant():
 from office_warping import torsion_chain,evaluate_chain
 L=7000.;GJ=1.4e10;EIw=2.0e17;c=torsion_chain([0.,L],GJ,EIw)
 assert np.allclose(c['K_theta'],GJ/L*np.array([[1,-1],[-1,1]]),rtol=1e-6,atol=1e-3)
 v=evaluate_chain(c,[0.,.01],L/2)
 assert abs(v['B_N_mm2'])<1e-3
 assert math.isclose(v['T_N_mm'],GJ*.01/L,rel_tol=1e-6)


def test_midspan_torque_has_analytical_warping_and_twist():
 from office_warping import torsion_chain,evaluate_chain
 L=8000.;GJ=7.2e10;EIw=4.0e17;P=1e6;c=torsion_chain([0.,L/2,L],GJ,EIw);K=np.asarray(c['K_theta']);theta=P/K[1,1];k=math.sqrt(GJ/EIw)
 expected=P/(2*GJ)*(L/2-math.tanh(k*L/2)/k)
 assert math.isclose(theta,expected,rel_tol=1e-6)
 v=evaluate_chain(c,[0,theta,0],L/2-1e-6)
 assert math.isclose(abs(v['B_N_mm2']),P/(2*k)*math.tanh(k*L/2),rel_tol=1e-6)
 assert np.max(abs(K.sum(axis=1)))<.01


def test_frame_midspan_torque_uses_vlasov_stiffness_and_returns_bimoment():
 from office_solver import solve_static
 from test_explicit_model import ExplicitModel
 t=ExplicitModel().model();t['Nodes']=[{'node_id':'a','x':0,'y':0,'z':3,**dict.fromkeys(['ux','uy','uz','rx','ry','rz'],1)},{'node_id':'b','x':4,'y':0,'z':3},{'node_id':'c','x':8,'y':0,'z':3,**dict.fromkeys(['ux','uy','uz','rx','ry','rz'],1)}]
 t['Sections']=[{'section_id':'S','shape':'H','section_name':'H600x200x11x17'}]
 t['Members']=[dict(member_id=f'P{i}',physical_member_id='P',i_node=a,j_node=b,section_id='S',material_id='Q',member_type='beam',role='GL2',release_i=0,release_j=0,unbraced_length_m=8.,length_m=4.) for i,(a,b) in enumerate([('a','b'),('b','c')])]
 r=solve_static({'tables':t,'diaphragm':'none'},{'case_id':'T','member_uniform_kN_m':{},'nodal_loads_kN_kNm':{'b':[0,0,0,1.,0,0]}},segments=2)
 assert r['ok'],r
 assert 'P' in r['analysis']['warping_results']
 result=r['analysis']['warping_results']['P'];assert result['max_bimoment_N_mm2']>0
 s=r['analysis']['sections']['S'];GJ=79000*s['J'];EIw=206000*result['properties']['Iw_mm6'];k=math.sqrt(GJ/EIw);expected=1e6/(2*GJ)*(4000-math.tanh(k*4000)/k)
 mid=next(n for n in r['analysis']['nodes'] if n['node_id']=='b');assert math.isclose(mid['displacement_mm_rad'][3],expected,rel_tol=1e-5)
