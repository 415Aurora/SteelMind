import sys,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'backend'))
class ExplicitModel(unittest.TestCase):
 def model(self):
  return {'Project':[{'field_id':'project_name','value':'柱自重基准'}],'Materials':[{'material_id':'Q','grade':'Q355B','E_MPa':206000,'G_MPa':79000,'density_t_m3':7.85}], 'Nodes':[{'node_id':'base','x':0,'y':0,'z':0,**dict.fromkeys(['ux','uy','uz','rx','ry','rz'],1)},{'node_id':'top','x':0,'y':0,'z':3}], 'Sections':[{'section_id':'BOX','section_name':'箱柱','shape':'BOX','depth_mm':400,'width_mm':400,'tw_mm':10,'tf_mm':10,'area_mm2':15600,'Ix_mm4':395720000,'Iy_mm4':395720000}], 'Members':[{'member_id':'C001','member_type':'column','i_node':'base','j_node':'top','section_id':'BOX','material_id':'Q','release_i':0,'release_j':0}], 'Floor_Loads':[{'荷载类别':'构件自重','数值':1}], 'Nodal_Loads':[],'Member_Loads':[]}
 def test_box_selfweight_and_original_ids(self):
  from explicit_model import run_explicit_model
  r=run_explicit_model(self.model());self.assertTrue(r['ok'],r);self.assertEqual(r['status'],'analysis_completed');self.assertEqual(r['analysis']['members'][0]['member_id'],'C001');self.assertAlmostEqual(r['analysis']['weight_kN'],.0156*3*7.85*9.80665,places=7);self.assertAlmostEqual(r['analysis']['reactions'][0]['Fz_kN'],r['analysis']['weight_kN'],places=6);self.assertEqual(r['upstream_check_summary'],'INCOMPLETE')
 def test_cantilever_gravity_matches_analytic_deflection(self):
  from explicit_model import run_explicit_model
  m=self.model();m['Nodes'][1].update(x=6,y=0,z=0);m['Members'][0]['member_type']='beam';r=run_explicit_model(m);self.assertTrue(r['ok'],r)
  q=.0156*7.85*9.80665;expected=-q*6000**4/(8*206000*395720000)
  self.assertAlmostEqual(r['analysis']['nodes'][1]['displacement_mm_rad'][2],expected,places=6)
 def test_hinged_beam_has_zero_released_end_moments(self):
  from explicit_model import run_explicit_model
  m=self.model();m['Nodes'][1].update(x=6,y=0,z=0,**dict.fromkeys(['ux','uy','uz','rx','ry','rz'],1));m['Members'][0].update(member_type='beam',release_i=1,release_j=1);r=run_explicit_model(m);self.assertTrue(r['ok'],r)
  forces=r['analysis']['members'][0]['segment_end_actions_kN_kNm'];self.assertAlmostEqual(forces[0][4],0,places=7);self.assertAlmostEqual(forces[-1][10],0,places=7)
 def test_complete_hn_designation_uses_catalog_properties(self):
  from explicit_model import run_explicit_model
  m=self.model();m['Sections'][0]={'section_id':'BOX','section_name':'HN600x200x11x17','shape':'H'};r=run_explicit_model(m);self.assertTrue(r['ok'],r);self.assertEqual(r['analysis']['sections']['BOX']['A'],13170)
 def test_h_beam_gravity_bends_about_strong_axis(self):
  from explicit_model import run_explicit_model
  m=self.model();m['Nodes'][1].update(x=6,y=0,z=0);m['Members'][0]['member_type']='beam';m['Sections'][0]={'section_id':'BOX','section_name':'H600x200x11x17','shape':'H'};r=run_explicit_model(m);self.assertTrue(r['ok'],r)
  q=.01317*7.85*9.80665;expected=-q*6000**4/(8*206000*756000000)
  self.assertAlmostEqual(r['analysis']['nodes'][1]['displacement_mm_rad'][2],expected,places=6)
 def test_missing_section_stops_instead_of_substitution(self):
  from explicit_model import run_explicit_model
  m=self.model();m['Sections'][0]={'section_id':'BOX','section_name':'HN600x200','shape':'H','depth_mm':600,'width_mm':200};r=run_explicit_model(m);self.assertEqual(r['status'],'needs_input');self.assertIn('BOX',str(r['errors']))
if __name__=='__main__':unittest.main()
