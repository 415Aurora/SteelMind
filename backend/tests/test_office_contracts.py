import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def test_reference_column_positions_and_intersection_connectivity():
 from office_contracts import reference_case,validate_office_bundle
 b=reference_case();assert len(b['columns_per_floor'])==28
 assert (4.,0.) in map(tuple,b['columns_per_floor'])
 assert (4.,9.5) not in map(tuple,b['columns_per_floor'])
 assert sum(m['member_type']=='column' for m in b['tables']['Members'])==112
 report=validate_office_bundle(b);assert report['ok'],report
 assert all(m['physical_member_id'] and m['unbraced_length_m']>0 for m in b['tables']['Members'])


def test_split_segments_never_replace_physical_ltb_length():
 from office_contracts import reference_case
 b=reference_case();members=b['tables']['Members']
 assert any(m['unbraced_length_m']>m['length_m']*2 for m in members if m['member_type']=='beam')
 assert len({m['member_id'] for m in members})==len(members)


def test_case_assumptions_and_old_input_are_explicitly_preserved():
 from office_contracts import reference_case,validate_office_bundle
 b=reference_case();assert b['scope']=='office_superstructure';assert b['diaphragm']=='rigid_in_plane';assert not b['compression_flange_slab_restraint']
 assert all(r['status']=='user_confirmed_design_assumption' for r in b['assumptions'])
 b['assumptions'][0]['status']='unconfirmed'
 assert not validate_office_bundle(b)['design_inputs_confirmed']


def test_full_office_input_cannot_silently_run_as_selfweight():
 from office_contracts import reference_case
 from explicit_model import normalize
 _,errors=normalize(reference_case()['tables'])
 assert any('office' in e.lower() or '办公楼' in e for e in errors)


def test_office_contract_rejects_nonfinite_parameters_and_slanted_columns():
 import copy
 from office_contracts import reference_case,validate_office_bundle
 b=reference_case();b['parameters']['wind_basic_kPa']=float('nan')
 assert not validate_office_bundle(b)['ok']
 b=reference_case();column=next(m for m in b['tables']['Members'] if m['member_type']=='column');node=next(n for n in b['tables']['Nodes'] if n['node_id']==column['j_node']);node['x']+=.1
 assert not validate_office_bundle(b)['ok']


def test_unsupported_seismic_conditions_and_inconsistent_reference_layout_are_rejected():
 from office_contracts import reference_case,validate_office_bundle
 b=reference_case();b['parameters']['ag_g']=.2
 assert not validate_office_bundle(b)['ok']
 b=reference_case();b['diaphragm']='none'
 assert not validate_office_bundle(b)['ok']
 b=reference_case();b['panels'][0]['rect_m'][1]-=.1
 assert not validate_office_bundle(b)['ok']


def test_office_hash_survives_browser_json_integral_number_roundtrip():
 import json
 from office_contracts import reference_case,bundle_hash
 b=reference_case();browser=json.loads(json.dumps(b),parse_float=lambda v:int(float(v)) if float(v).is_integer() else float(v))
 assert bundle_hash(b)==bundle_hash(browser)
