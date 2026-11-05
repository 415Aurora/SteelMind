import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def test_office_run_invalid_input_returns_no_generation_or_design_pass():
 from office_design import run_office_design
 r=run_office_design({'bundle':{'schema_version':'bad'}})
 assert r['ok'] is False and r['status']=='needs_input'
 assert not r.get('design_passed',False)


def test_run_sanitizes_options_and_retains_reference_hash():
 from office_design import run_office_design
 from office_contracts import reference_case
 r=run_office_design({'bundle':reference_case(),'options':{'scheme_indices':[True]}})
 assert not r['ok'] and r['status']=='needs_input'


def test_json_conversion_rejects_nonfinite_and_supports_numpy():
 import numpy as np
 import pytest
 from office_design import json_ready
 assert json_ready({'x':np.array([1.,2.])})=={'x':[1.,2.]}
 with pytest.raises(ValueError):json_ready(float('nan'))


def test_cancel_during_final_verification_never_publishes_success(monkeypatch):
 import office_analysis,office_envelopes,office_checks,office_validation
 from office_design import run_office_design
 stopped=[False]
 monkeypatch.setattr(office_analysis,'analyze_office',lambda *a,**kw:{'ok':True})
 monkeypatch.setattr(office_envelopes,'build_design_envelopes',lambda *a:{})
 check={'design_status':'PASS','summary':{'PASS':1},'members':[{'member_id':'C','section_id':'S','status':'PASS','max_utilization':.1}],'coverage_status':'COMPLETE','scope':'test'}
 monkeypatch.setattr(office_checks,'check_office_design',lambda *a:check)
 def verification(*a,**kw):stopped[0]=True;return {'status':'PASS'}
 monkeypatch.setattr(office_validation,'verify_second_order_controls',verification)
 r=run_office_design({'options':{'scheme_indices':[4]}},cancelled=lambda:stopped[0])
 assert not r['ok'] and r['status']=='cancelled'
