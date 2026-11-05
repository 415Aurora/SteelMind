import sys,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def sample():
 from office_contracts import reference_case,geometry_model
 from office_responses import DEMAND_KEYS
 m=geometry_model(reference_case());s=m['sections']['SEC_HN600'];mat=next(iter(m['materials'].values()))
 d={k:0. for k in DEMAND_KEYS};d.update(physical_member_id='B',member_type='beam',section_id=s['section_id'],length_m=8.,unbraced_length_m=8.)
 return d,s,mat


def test_failing_bending_demand_is_not_passed_and_ltb_uses_physical_span():
 from office_checks import check_member
 d,s,mat=sample();d.update(Mz_kNm=1e6,ltb_moment_bound_kNm=1e6)
 r=check_member(d,s,mat,second_order_verified=True)
 assert r['status']=='FAIL'
 c=next(c for c in r['checks'] if c['item']=='lateral_torsional_stability')
 assert c['inputs']['unbraced_mm']==8000 and c['status']=='FAIL'


def test_missing_second_order_certificate_cannot_enable_column_mu_one():
 from office_checks import check_member
 d,s,mat=sample();d['member_type']='column'
 r=check_member(d,s,mat,second_order_verified=False)
 assert next(c for c in r['checks'] if c['item']=='biaxial_compression_stability')['status']=='PENDING'
 assert r['status']!='PASS'


def test_external_connection_handoff_stays_separate_from_member_check():
 from office_checks import check_member
 d,s,mat=sample();r=check_member(d,s,mat,second_order_verified=True)
 assert 'whole_building_passed' not in r
 assert any(h['status']=='EXTERNAL_VERIFICATION_PENDING' for h in r['handoff'])


def test_new_sections_preserve_reference_authoritative_properties():
 from office_design import apply_section_scheme
 from office_contracts import reference_case,geometry_model
 b=reference_case();before=copy.deepcopy(b)
 c=apply_section_scheme(b,1)
 assert b==before
 old={s['section_id']:s for s in b['tables']['Sections']}
 new={s['section_id']:s for s in c['tables']['Sections']}
 assert all(new[k]==v for k,v in old.items())
 assert all(m['section_id'] in new for m in c['tables']['Members'])
 assert c['analysis_options']['column_chord'] is True
 assert c['stiffeners']


def test_aggregate_refuses_partial_analysis_and_keeps_external_scope_pending():
 import numpy as np
 from office_checks import check_office_design
 from office_contracts import reference_case
 from office_responses import DEMAND_KEYS
 b=reference_case();pid=b['physical_members'][0]['physical_member_id'];m=b['physical_members'][0]
 a={'physical_ids':[pid],'physical_descriptors':{pid:{**m,'length_m':4.}},'floor_ids':[1,2,3,4],'scope_status':'REDUCED_TEST_SCOPE','modal':{'coverage_x':1.,'coverage_y':1.},'earthquake':{'X':{'details':[]},'Y':{'details':[]}},'mass_source':{'floors':[{'mass_t':1.}]*4},'flexibility':np.eye(12)}
 e={'strength':np.zeros((1,len(DEMAND_KEYS))),'service':np.zeros((1,len(DEMAND_KEYS))),'strength_control':[['ULS-001']*len(DEMAND_KEYS)],'service_control':[['SLS-001']*len(DEMAND_KEYS)],'second_order_verified':False,'drift_mm':[[0.,0.,0.]]*4,'drift_control':[['SLS-001']*3]*4,'maximum_theta_upper_bound':.01,'ok':True}
 r=check_office_design(b,a,e)
 assert r['design_status']=='INCOMPLETE'
 assert r['building_status']=='EXTERNAL_VERIFICATION_PENDING'
 assert any(c['status']=='PENDING' for c in r['global_checks'])


def test_torsion_irregularity_requires_treatment_not_false_automatic_failure():
 from office_checks import torsion_assessment
 r=torsion_assessment(1.375,spatial_bidirectional_accidental=True)
 assert r['classification']=='TORSIONALLY_IRREGULAR'
 assert r['status']=='PASS' and r['limit']==1.5 and r['classification_threshold']==1.2
 assert torsion_assessment(1.375,spatial_bidirectional_accidental=False)['status']=='PENDING'
 assert torsion_assessment(1.6,spatial_bidirectional_accidental=True)['status']=='PENDING'


def test_storey_stiffness_is_shear_over_drift_under_declared_force_pattern():
 import numpy as np
 from office_checks import storey_stiffness
 # Two-story shear building k1=100,k2=200 N/mm.
 F=np.zeros((6,6));F[0,0]=.01;F[0,3]=F[3,0]=.01;F[3,3]=.015
 F[1,1]=.01;F[1,4]=F[4,1]=.01;F[4,4]=.015
 floors=[{'floor':1,'z_m':4.,'mass_t':1.},{'floor':2,'z_m':8.,'mass_t':1.}]
 masters={'@F1':{'xyz_m':[0.,0.,4.]},'@F2':{'xyz_m':[0.,0.,8.]}}
 r=storey_stiffness(F,floors,masters)
 assert np.allclose(r['X']['stiffness_N_mm'],[100.,200.])
 assert r['method']=='story_shear_over_interstory_drift'


def test_replay_of_adopted_section_scheme_keeps_unique_section_authority():
 from office_contracts import reference_case,validate_office_bundle
 from office_design import apply_section_scheme
 once=apply_section_scheme(reference_case(),4);twice=apply_section_scheme(once,4)
 assert validate_office_bundle(twice)['ok']
 assert twice['tables']['Sections']==once['tables']['Sections']
