import sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def test_gravity_floor_stair_wall_and_mass_are_conserved():
 from office_contracts import reference_case
 from office_loads import build_load_cases,build_mass_source
 b=reference_case();cases=build_load_cases(b);mass=build_mass_source(b,cases)
 assert set(cases)>={'G','Q_OFFICE','Q_STAIR','Q_ROOF'}
 assert abs(cases['G']['audit']['floor_area_m2']-(515*3+627))<1e-6
 assert math.isclose(cases['G']['audit']['floor_weight_kN'],515*3*4.5+627*5.5,abs_tol=1e-7)
 assert math.isclose(cases['G']['audit']['stair_weight_kN'],28*32*3,abs_tol=1e-7)
 assert math.isclose(cases['Q_STAIR']['audit']['total_force_kN'][2],-12.5*32*3,abs_tol=1e-7)
 assert abs(mass['total_mass_t']*9.80665-(cases['G']['audit']['weight_kN']+.5*(cases['Q_OFFICE']['audit']['weight_kN']+cases['Q_STAIR']['audit']['weight_kN'])))<1e-6
 assert all(v['audit']['status']=='PASS' for v in cases.values())


def test_unassigned_panel_is_rejected_not_silently_zero():
 import pytest
 from office_contracts import reference_case
 from office_loads import build_load_cases
 b=reference_case();b['panels'][0]['rect_m']=[100,102,100,107]
 with pytest.raises(ValueError,match='支承'):build_load_cases(b)


def test_stair_openings_and_roof_are_distinct():
 from office_contracts import reference_case
 from office_loads import build_load_cases
 b=reference_case();c=build_load_cases(b)
 assert math.isclose(c['Q_OFFICE']['audit']['weight_kN'],515*3*3.5,abs_tol=1e-7)
 assert math.isclose(c['Q_ROOF']['audit']['weight_kN'],627*.5,abs_tol=1e-7)


def test_independent_live_load_regions_sum_to_full_case():
 from office_contracts import reference_case
 from office_loads import build_load_cases,build_live_influence_cases
 import numpy as np
 b=reference_case();base=build_load_cases(b);regions=build_live_influence_cases(b,base)
 assert len(regions)>100
 for key in ('Q_OFFICE','Q_STAIR','Q_ROOF'):
  rows=[v for v in regions if v['parent_case_id']==key]
  for mid,q in base[key]['member_uniform_kN_m'].items():
   assert np.allclose(sum((np.asarray(v['member_uniform_kN_m'].get(mid,[0,0,0])) for v in rows)),q)


def test_added_stiffener_nodal_weight_enters_mass_once():
 from office_contracts import reference_case
 from office_loads import build_load_cases,build_mass_source
 b=reference_case();c=build_load_cases(b);m=build_mass_source(b,c);nid=next(n['node_id'] for n in b['tables']['Nodes'] if n['z']==4)
 c['G']['nodal_loads_kN_kNm'][nid]=[0,0,-10.,0,0,0];c['G']['audit']['weight_kN']+=10.
 updated=build_mass_source(b,c);assert math.isclose(updated['total_mass_t']-m['total_mass_t'],10/9.80665,abs_tol=1e-7)
