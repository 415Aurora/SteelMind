import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_explicit_model import ExplicitModel
class NumericalAudit(unittest.TestCase):
 def result(self):
  from explicit_model import run_explicit_model
  t=ExplicitModel().model();t['Nodes'][1].update(x=6,y=0,z=0);t['Members'][0]['member_type']='beam'
  return t,run_explicit_model(t)
 def test_correct_analysis_balances_all_six_components(self):
  from explicit_audit import audit_analysis
  t,r=self.result();a=audit_analysis(t,r['analysis']);self.assertEqual(a['status'],'PASS');self.assertEqual(len(a['global_equilibrium']),6);self.assertEqual(a['segments_checked'],8)
 def test_corrupt_horizontal_reaction_fails_despite_vertical_balance(self):
  from explicit_audit import audit_analysis
  t,r=self.result();r['analysis']['reactions'][0]['Fx_kN']+=1;a=audit_analysis(t,r['analysis']);self.assertEqual(a['status'],'FAIL');self.assertEqual(a['global_equilibrium'][0]['status'],'FAIL')
 def test_corrupt_local_end_force_fails(self):
  from explicit_audit import audit_analysis
  t,r=self.result();r['analysis']['members'][0]['segment_end_actions_kN_kNm'][2][4]+=1;self.assertEqual(audit_analysis(t,r['analysis'])['status'],'FAIL')
 def test_missing_member_cannot_pass(self):
  from explicit_audit import audit_analysis
  t,r=self.result();r['analysis']['members']=[];self.assertEqual(audit_analysis(t,r['analysis'])['status'],'FAIL')
 def test_mesh_option_and_norm_status_are_distinct(self):
  from explicit_model import run_explicit_model
  t,r=self.result();fine=run_explicit_model(t,segments_per_member=16);self.assertTrue(fine['ok'],fine);self.assertEqual(fine['numerical_audit']['status'],'PASS');self.assertEqual(fine['upstream_check_summary'],'INCOMPLETE');self.assertEqual(len(fine['analysis']['members'][0]['segment_end_actions_kN_kNm']),16)
  self.assertAlmostEqual(fine['analysis']['nodes'][1]['displacement_mm_rad'][2],r['analysis']['nodes'][1]['displacement_mm_rad'][2],places=6)
 def test_invalid_mesh_and_nonfinite_results_are_rejected(self):
  from explicit_model import run_explicit_model
  from explicit_audit import audit_analysis
  t,r=self.result();self.assertEqual(run_explicit_model(t,segments_per_member=True)['status'],'needs_input')
  r['analysis']['members'][0]['segment_end_actions_kN_kNm'][0][0]=float('nan');self.assertEqual(audit_analysis(t,r['analysis'])['status'],'FAIL')
 def test_released_end_has_its_own_audit(self):
  from explicit_model import run_explicit_model
  from explicit_audit import audit_analysis
  t=ExplicitModel().model();t['Nodes'][1].update(x=6,y=0,z=0,**dict.fromkeys(['ux','uy','uz','rx','ry','rz'],1));t['Members'][0].update(member_type='beam',release_i=1,release_j=1)
  r=run_explicit_model(t);a=r['numerical_audit'];self.assertEqual(a['released_ends_checked'],2);self.assertEqual(a['status'],'PASS')
  r['analysis']['members'][0]['segment_end_actions_kN_kNm'][0][5]=.1;self.assertTrue(any(c['status']=='FAIL' for c in audit_analysis(t,r['analysis'])['release_checks']))
 def test_reported_load_and_axes_cannot_differ_from_input(self):
  from explicit_audit import audit_analysis
  t,r=self.result();r['analysis']['members'][0]['self_weight_kN_m']*=2;self.assertEqual(audit_analysis(t,r['analysis'])['status'],'FAIL')
 def test_self_equilibrated_corruption_still_fails_joint_equilibrium(self):
  from explicit_audit import audit_analysis
  t,r=self.result()
  for f in r['analysis']['members'][0]['segment_end_actions_kN_kNm']:f[0]+=100;f[6]-=100
  a=audit_analysis(t,r['analysis']);self.assertEqual(a['status'],'FAIL');self.assertTrue(any(c['status']=='FAIL' for c in a['joint_equilibrium']))
 def test_internal_segment_interface_must_balance(self):
  from explicit_audit import audit_analysis
  t,r=self.result();f=r['analysis']['members'][0]['segment_end_actions_kN_kNm'][2];f[0]+=100;f[6]-=100
  a=audit_analysis(t,r['analysis']);self.assertEqual(a['status'],'FAIL');self.assertTrue(any(c['status']=='FAIL' for c in a['interface_equilibrium']))
