import sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def test_all_defined_stiffener_nodes_count_once_in_gravity_and_mass():
 from office_contracts import reference_case,geometry_model
 from office_design import apply_section_scheme
 from office_loads import build_load_cases,build_mass_source,GRAVITY
 b=apply_section_scheme(reference_case(),1);st=b.pop('stiffeners');base=build_load_cases(b);mass0=build_mass_source(b,base)['total_mass_t'];b['stiffeners']=st;loaded=build_load_cases(b);m=geometry_model(b)
 expected=sum(len(s['node_ids'])*2*s['width_mm']*s['thickness_mm']*s['height_mm']*1e-9*7.85*GRAVITY for s in st)
 delta=loaded['G']['audit']['weight_kN']-base['G']['audit']['weight_kN']
 assert math.isclose(delta,expected,rel_tol=1e-10)
 assert math.isclose(build_mass_source(b,loaded)['total_mass_t']-mass0,expected/GRAVITY,rel_tol=1e-10)
 assert loaded['G']['audit']['status']=='PASS'
