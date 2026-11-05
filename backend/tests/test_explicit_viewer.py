import sys,json,re,unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests'))
from test_explicit_model import ExplicitModel
class AnalysisViewer(unittest.TestCase):
 def test_actual_force_units_and_unresolved_status(self):
  from explicit_model import run_explicit_model
  from explicit_viewer import build_scene
  tables=ExplicitModel().model();r=run_explicit_model(tables);scene=build_scene(tables,r)
  item=scene['member_checks']['C001'];self.assertAlmostEqual(abs(item['demands']['N_kn']),r['analysis']['weight_kN'],places=7)
  self.assertEqual(item['demands']['T_kNm'],0);self.assertIsNone(scene['member_statuses']['C001']);self.assertTrue(any(c['status']=='PENDING' for c in item['checks']))
  self.assertEqual(scene['analysis_scope'],'self_weight');self.assertEqual(len(scene['node_displacements']),2)
 def test_interior_moment_not_just_end_actions(self):
  from explicit_model import run_explicit_model
  from explicit_viewer import build_scene
  tables=ExplicitModel().model();tables['Nodes'][1].update(x=6,y=0,z=0,**dict.fromkeys(['ux','uy','uz','rx','ry','rz'],1));tables['Members'][0].update(member_type='beam',release_i=1,release_j=1)
  r=run_explicit_model(tables);scene=build_scene(tables,r);v=scene['member_checks']['C001']['demands'];q=.0156*7.85*9.80665
  self.assertAlmostEqual(abs(v['Mz_kNm']),q*6**2/8,places=6);self.assertAlmostEqual(abs(v['Vy_kn']),q*6/2,places=6);self.assertGreater(v['deflection_mm'],0)
 def test_stale_analysis_cannot_be_attached(self):
  from explicit_model import run_explicit_model
  from explicit_viewer import build_scene
  tables=ExplicitModel().model();r=run_explicit_model(tables);tables['Members'][0]['member_id']='other'
  with self.assertRaises(ValueError):build_scene(tables,r)

class ViewerDeformation(unittest.TestCase):
 def test_simply_supported_beam_has_curved_midspan_even_with_fixed_nodes(self):
  from explicit_model import run_explicit_model
  from explicit_viewer import build_scene
  t=ExplicitModel().model();t['Nodes'][1].update(x=6,y=0,z=0,**dict.fromkeys(['ux','uy','uz','rx','ry','rz'],1));t['Members'][0].update(member_type='beam',release_i=1,release_j=1)
  r=run_explicit_model(t);scene=build_scene(t,r);curve=scene['deformation_curves']['C001'];middle=curve[len(curve)//2]
  exact=5*(.0156*7.85*9.80665)*6000**4/(384*206000*395720000)
  self.assertAlmostEqual(middle['u_mm'][1],-exact,places=6);self.assertEqual(curve[0]['u_mm'],[0.,0.,0.]);self.assertEqual(curve[-1]['u_mm'],[0.,0.,0.]);self.assertGreater(scene['deformation_summary']['max_beam_relative_deflection_mm'],0)
