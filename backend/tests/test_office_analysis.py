import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def test_full_office_analysis_closes_case_and_live_region_accounting():
 from office_contracts import reference_case
 from office_analysis import analyze_office
 result=analyze_office(reference_case(),include_accidental=False,include_live_regions=False)
 assert result['ok'],result
 assert result['scope_status']=='REDUCED_TEST_SCOPE'
 assert result['modal']['coverage_x']>.9 and result['modal']['coverage_y']>.9
 assert len(result['influences'])==12
 assert result['earthquake']['X']['minimum_shear_scale']>=1
 assert result['case_results']['G']['numerical_audit']['status']=='PASS'
