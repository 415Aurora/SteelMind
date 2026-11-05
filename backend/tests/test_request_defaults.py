import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
class Defaults(unittest.TestCase):
 def test_blank_request_runs_with_audited_defaults(self):
  from request_defaults import apply_request_defaults
  r=apply_request_defaults({});self.assertEqual(r['geometry']['stories'],1);self.assertEqual(r['loads']['q_by_story_kN_per_m'],[10]);self.assertTrue(r['default_assumptions']);self.assertIn(r['model_sections']['beam_section'],r['candidate_sections']['beam'])
 def test_dimensions_and_zero_user_values(self):
  from request_defaults import apply_request_defaults
  p={'geometry':{'stories':3,'bays_x':2},'loads':{'lateral_z_by_story_kN':[0]}};original=copy.deepcopy(p);r=apply_request_defaults(p)
  self.assertEqual(p,original);self.assertEqual(r['geometry']['bay_widths_x_m'],[6,6]);self.assertEqual(r['loads']['lateral_z_by_story_kN'],[0,0,0]);self.assertEqual(r['geometry']['story_heights_m'],[3,3,3])
  self.assertEqual(apply_request_defaults(r)['default_assumptions'],r['default_assumptions'])
 def test_invalid_explicit_values_are_not_replaced(self):
  from request_defaults import apply_request_defaults
  r=apply_request_defaults({'geometry':{'stories':1.5,'bays_x':-2}});self.assertEqual(r['geometry']['stories'],1.5);self.assertEqual(r['geometry']['bays_x'],-2)
if __name__=='__main__':unittest.main()
