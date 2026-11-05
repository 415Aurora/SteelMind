import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'backend'));sys.path.insert(0,str(ROOT/'backend/engineering_export/src'))
class ExplicitCAD(unittest.TestCase):
 def test_longyan_planar_sheets_preserve_geometry_and_sections(self):
  from explicit_model import run_explicit_model
  from explicit_cad import generate_explicit_cad
  import ezdxf
  t=json.loads((ROOT/'examples/longyan-selfweight/input.json').read_text());r=run_explicit_model(t);self.assertTrue(r['ok'],r)
  with tempfile.TemporaryDirectory() as tmp:
   files,quality=generate_explicit_cad(t,r['analysis'],Path(tmp),include_pdf=False)
   self.assertEqual(quality['status'],'PASS');self.assertEqual(len(quality['covered_members']),248)
   self.assertEqual(len([v for v in quality['sheets'] if v['kind']=='plan']),4);self.assertEqual(len([v for v in quality['sheets'] if v['kind']=='elevation']),10)
   self.assertEqual(set(s['shape'] for s in quality['section_sheets']),{'H','H-WELDED','BOX'})
   dims=[]
   for p in files:
    if p.suffix!='.dxf':continue
    d=ezdxf.readfile(p);self.assertFalse(d.audit().has_errors);self.assertEqual(d.units,4)
    if '构件表' in p.name:
     layout=d.layouts.get('A3')
     boundaries=[e.dxf.start.y for e in layout.query('LINE') if abs(e.dxf.start.y-e.dxf.end.y)<1e-8 and 58<e.dxf.start.y<252]
     for text in layout.query('TEXT'):
      if 58<text.dxf.insert.y<252:
       self.assertTrue(all(not text.dxf.insert.y-.3*text.dxf.height<y<text.dxf.insert.y+1.1*text.dxf.height for y in boundaries),'表格边界不得穿过文字：'+text.dxf.text)
    for e in d.modelspace().query('LINE'):self.assertAlmostEqual(e.dxf.start.z,0);self.assertAlmostEqual(e.dxf.end.z,0)
    dims += [round(x.get_measurement()) for x in d.modelspace().query('DIMENSION')]
   self.assertIn(8000,dims);self.assertIn(4000,dims);self.assertIn(2500,dims)
   self.assertTrue(all(q['min_paper_text_mm']>=2.5 for q in quality['sheets']))
if __name__=='__main__':unittest.main()

class DrawingFailure(unittest.TestCase):
 def test_pdf_failure_keeps_dxf_and_reports_partial(self):
  from explicit_model import run_explicit_model
  from explicit_cad import generate_explicit_cad
  from unittest.mock import patch
  sys.path.insert(0,str(ROOT/'backend/tests'))
  from test_explicit_model import ExplicitModel
  t=ExplicitModel().model();r=run_explicit_model(t)
  with tempfile.TemporaryDirectory() as tmp,patch('explicit_cad._render_pdf',side_effect=RuntimeError('forced render failure')):
   files,q=generate_explicit_cad(t,r['analysis'],Path(tmp),include_pdf=True)
   self.assertEqual(q['status'],'PARTIAL');self.assertTrue(q['errors']);self.assertTrue(any(p.suffix=='.dxf' for p in files));self.assertFalse(any(p.suffix=='.pdf' for p in files))
 def test_column_plan_respects_section_orientation(self):
  from explicit_model import run_explicit_model
  from explicit_cad import generate_explicit_cad
  import ezdxf
  sys.path.insert(0,str(ROOT/'backend/tests'))
  from test_explicit_model import ExplicitModel
  t=ExplicitModel().model();t['Members'][0]['orientation_deg']=45;r=run_explicit_model(t)
  with tempfile.TemporaryDirectory() as tmp:
   files,q=generate_explicit_cad(t,r['analysis'],Path(tmp),include_pdf=False)
   p=next(p for p in files if 'XY平面' in p.name);d=ezdxf.readfile(p);poly=next(iter(d.modelspace().query('LWPOLYLINE[layer=="S-OUTLINE"]')));xs=[x[0] for x in poly.get_points('xy')]
   self.assertAlmostEqual(max(xs),200*2**.5,places=6)
