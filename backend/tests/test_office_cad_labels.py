import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parent))


def test_office_compact_marks_preserve_original_member_sources(tmp_path):
 import ezdxf
 from test_explicit_model import ExplicitModel
 from explicit_model import run_explicit_model
 from explicit_cad import generate_explicit_cad
 tables=ExplicitModel().model();r=run_explicit_model(tables)
 files,q=generate_explicit_cad(tables,r['analysis'],tmp_path,include_pdf=False,compact_marks=True)
 assert q['status']=='PASS'
 assert any(e.dxf.text=='M001' for p in files if p.suffix=='.dxf' for e in ezdxf.readfile(p).modelspace().query('TEXT'))
 assert q['covered_members']==['C001']
