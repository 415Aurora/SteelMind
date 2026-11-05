import sys,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests'))
from test_explicit_model import ExplicitModel
class NormChecks(unittest.TestCase):
 def result(self):
  from explicit_model import run_explicit_model
  return run_explicit_model(ExplicitModel().model())
 def test_q355_design_strength_respects_plate_thickness(self):
  from explicit_checks import design_strength
  self.assertEqual(design_strength('Q355B',10)['f_MPa'],305);self.assertEqual(design_strength('Q355B',17)['f_MPa'],295)
 def test_numerical_checks_and_coverage_are_attached(self):
  r=self.result();self.assertIn('code_checks',r);v=r['code_checks'];self.assertEqual(v['status'],'INCOMPLETE');m=v['members'][0];stress=next(c for c in m['checks'] if c['item']=='section_strength');self.assertEqual(stress['status'],'PASS');self.assertGreater(stress['demand'],0);self.assertIn('substitution',stress);self.assertTrue(any(c['status']=='PENDING' and c['item']=='compression_stability' for c in m['checks']))
 def test_elastic_strength_fail_is_not_upgraded(self):
  from explicit_model import run_explicit_model
  m=ExplicitModel().model();m['Floor_Loads'][0]['数值']=10000;r=run_explicit_model(m);self.assertEqual(r['code_checks']['status'],'FAIL');self.assertEqual(r['upstream_check_summary'],'FAIL')
 def test_released_beam_interior_moment_and_deflection_are_checked(self):
  from explicit_model import run_explicit_model
  from explicit_checks import evaluate_checks
  m=ExplicitModel().model();m['Nodes'][1].update(x=6,y=0,z=0,**dict.fromkeys(['ux','uy','uz','rx','ry','rz'],1));m['Members'][0].update(member_type='beam',release_i=1,release_j=1);r=run_explicit_model(m);self.assertTrue(r['ok'],r)
  a=r['analysis'];member=a['members'][0];forces=member['segment_end_actions_kN_kNm'];D=member['segment_displacements_mm_rad'];member['segment_end_actions_kN_kNm']=[forces[0][:6]+forces[-1][6:]];member['segment_displacements_mm_rad']=[D[0],D[-1]]
  v=evaluate_checks(m,a)['members'][0]['checks'];q=.0156*7.85*9.80665;expected=5*q*6000**4/(384*206000*395720000)
  self.assertAlmostEqual(next(c for c in v if c['item']=='beam_deflection')['demand'],expected,places=6)
  self.assertAlmostEqual(next(c for c in v if c['item']=='section_strength')['demand'],1.3*q*6000**2/8/(395720000/200),places=6)
if __name__=='__main__':unittest.main()

class CantileverChecks(unittest.TestCase):
 def test_free_tip_is_not_removed_by_end_chord(self):
  from explicit_model import run_explicit_model
  m=ExplicitModel().model();m['Nodes'][1].update(x=6,y=0,z=0);m['Members'][0]['member_type']='beam';m['Floor_Loads'][0]['数值']=20
  r=run_explicit_model(m);c=next(c for c in r['code_checks']['members'][0]['checks'] if c['item']=='beam_deflection')
  expected=.0156*7.85*9.80665*20*6000**4/(8*206000*395720000)
  self.assertAlmostEqual(c['demand'],expected,places=6);self.assertEqual(c['limit'],30);self.assertEqual(c['status'],'FAIL')
