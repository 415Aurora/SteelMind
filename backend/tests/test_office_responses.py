import sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_explicit_model import ExplicitModel


def test_physical_beam_deflection_not_reset_at_mesh_split():
 from office_solver import solve_static
 from office_responses import physical_demands,combine_results
 t=ExplicitModel().model();t['Nodes']=[{'node_id':'a','x':0,'y':0,'z':3,**dict.fromkeys(['ux','uy','uz','rx','ry','rz'],1)},{'node_id':'b','x':3,'y':0,'z':3},{'node_id':'c','x':6,'y':0,'z':3,**dict.fromkeys(['ux','uy','uz','rx','ry','rz'],1)}]
 t['Members']=[dict(member_id='B1',physical_member_id='B',i_node='a',j_node='b',section_id='BOX',material_id='Q',member_type='beam',role='GL2',release_i=1,release_j=0,unbraced_length_m=6.,length_m=3.),dict(member_id='B2',physical_member_id='B',i_node='b',j_node='c',section_id='BOX',material_id='Q',member_type='beam',role='GL2',release_i=0,release_j=1,unbraced_length_m=6.,length_m=3.)]
 r=solve_static({'tables':t,'diaphragm':'none'},{'case_id':'q','member_uniform_kN_m':{'B1':[0,0,-10.],'B2':[0,0,-10.]},'nodal_loads_kN_kNm':{}});assert r['ok'],r
 d=physical_demands(r)['B'];assert math.isclose(d['deflection_mm'],5*10*6000**4/(384*206000*395720000),rel_tol=1e-7)
 assert math.isclose(d['Mz_kNm'],10*6**2/8,rel_tol=1e-7)
 two=combine_results({'q':r},{'q':2.},'2q');assert math.isclose(physical_demands(two)['B']['deflection_mm'],2*d['deflection_mm'],rel_tol=1e-7)


def test_master_displacements_are_transformed_to_common_reference():
 from office_responses import master_vector
 r={'analysis':{'master_results':{'@F1':{'xyz_m':[1.,2.,4.],'displacement_mm_rad':[1.,2.,0.,0.,0.,.001]}}}}
 assert list(master_vector(r,{'@F1':{'xyz_m':[0.,0.,4.]}}))==[3.,1.,.001]
