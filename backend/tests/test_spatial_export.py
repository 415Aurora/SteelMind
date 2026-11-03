import copy,json,sys,tempfile,unittest,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
sys.path.insert(0,str(ROOT/'backend/tool_sources'))
from engineering_drawings import inspect_drawing_bundle
REPORT=json.loads((ROOT/'backend/tests/data/spatial_report.json').read_text())
class SpatialContract(unittest.TestCase):
 def test_current_3d_report_is_exportable_without_flattening(self):
  r=inspect_drawing_bundle(REPORT)
  self.assertTrue(r['valid'],r.get('draft_reasons'));self.assertEqual(r['bundle']['schema_version'],'SpatialResultBundle/1.0')
  self.assertEqual(len(r['bundle']['members']),8);self.assertEqual(max(n['z_m'] for n in r['bundle']['nodes']),6)
  self.assertTrue(r['draft']);self.assertEqual(r['upstream_check_summary'],'INCOMPLETE')
 def test_bad_inputs_are_rejected(self):
  def reject(edit):
   r=copy.deepcopy(REPORT);edit(r);result=inspect_drawing_bundle(r);self.assertFalse(result['valid'],result)
  reject(lambda r:r['analysis']['results']['model_nodes'].append(r['analysis']['results']['model_nodes'][0]))
  reject(lambda r:r['analysis']['results']['members'][0].update(node_i='missing'))
  reject(lambda r:r['analysis']['results']['model_nodes'][0].update(z_m=float('nan')))
  reject(lambda r:r['member_checks'][0].update(section='H100x100x6x8'))
  reject(lambda r:r['member_checks'][0].update(passed=False))
  reject(lambda r:next(iter(r['analysis']['parameters']['member_sections'].values())).update(h_mm=350))
  reject(lambda r:r['member_checks'][0]['checks'][0].update(passed=False))
class SpatialArtifacts(unittest.TestCase):
 def test_package_preserves_xyz_and_numeric_results(self):
  import spatial_export,ezdxf,openpyxl
  from zipfile import ZipFile
  from docx import Document
  with tempfile.TemporaryDirectory() as temp:
   generated=spatial_export.generate_spatial_package(REPORT,{'include_pdf':False},Path(temp))
   self.assertEqual(generated['generation_status'],'success',generated)
   root=Path(generated['output_dir']);files=generated['artifacts']
   assembly=ezdxf.readfile(root/'cad/90_三维线框.dxf');self.assertFalse(assembly.audit().has_errors)
   lines=list(assembly.modelspace().query('LINE[layer=="S-MEMBER"]'));self.assertEqual(len(lines),8)
   self.assertEqual(max(e.dxf.end.z for e in lines),6000)
   self.assertEqual(assembly.units,4)
   qa=json.loads((root/'cad/cad_quality.json').read_text())
   self.assertEqual(set(qa['covered_members']),{m['member_id'] for m in REPORT['analysis']['results']['members']})
   self.assertIn(6000,[v for sheet in qa['sheets'] for v in sheet['dimension_mm']])
   for sheet in qa['sheets']:self.assertEqual(sheet['audit_errors'],[])
   wb=openpyxl.load_workbook(root/'三维结果表.xlsx',data_only=False)
   self.assertEqual(wb['节点位移']['D2'].value,0);self.assertEqual(wb['节点位移']['G2'].value,0)
   self.assertIsInstance(wb['构件验算']['D2'].value,float);self.assertEqual(wb['构件验算']['D2'].value,REPORT['member_checks'][0]['utilization'])
   text='\n'.join(p.text for p in Document(root/'三维结构计算书.docx').paragraphs)
   self.assertIn('方案草稿',text);self.assertIn('INCOMPLETE',text);self.assertIn('扭转',text)
   with ZipFile(root/'三维工程成果包.zip') as archive:self.assertIsNone(archive.testzip());self.assertIn('input_snapshot.json',archive.namelist())
   self.assertTrue(files)

if __name__=='__main__':unittest.main()
