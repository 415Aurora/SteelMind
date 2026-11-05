"""Artifact acceptance; run with the project virtual environment, no model API."""
import sys,json,hashlib,math
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
import ezdxf
from openpyxl import load_workbook
from pypdf import PdfReader
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from office_contracts import bundle_hash

root=Path(sys.argv[1]).resolve();manifest=json.loads((root/'manifest.json').read_text());run=json.loads((root/'办公楼完整运行.json').read_text());assert manifest['input_sha256']==run['input_sha256']==bundle_hash(run['bundle'])
for row in manifest['files']:
 p=(root/row['path']).resolve();assert p.is_relative_to(root);raw=p.read_bytes();assert len(raw)==row['bytes'];assert hashlib.sha256(raw).hexdigest()==row['sha256'],row['path']
wb=load_workbook(root/'办公楼分析与验算结果表.xlsx',read_only=False,data_only=False)
assert wb['节点'].max_row==309 and wb['构件'].max_row==541
assert wb['组合及二阶'].max_row==319
assert wb['构件验算'].max_row==1+sum(len(m['checks']) for m in run['code_checks']['members'])
assert all(ws.freeze_panes=='A2' and ws.auto_filter.ref for ws in wb)
assert all(c.data_type!='f' for ws in wb for row in ws for c in row)
raw=ezdxf.readfile(root/'90_原始XYZ空间杆系.dxf');assert len(raw.modelspace().query('LINE'))==540 and raw.units==4
q=json.loads((root/'cad/出图质量记录.json').read_text());assert q['status']=='PASS' and len(q['covered_members'])==540 and not q['uncovered_members'];assert min(s['min_paper_text_mm'] for s in q['sheets'])>=2.5-1e-9
for row in q['sheets']:assert not ezdxf.readfile(root/'cad'/row['file']).audit().has_errors
book=PdfReader(root/'办公楼上部钢框架计算书.pdf');text=''.join(p.extract_text() for p in book.pages);assert '上部钢框架计算书' in text and run['input_sha256'] in text;assert 'EXTERNAL_VERIFICATION_PENDING' in text
with ZipFile(root/'办公楼上部钢框架计算书.docx') as z:
 tree=ET.fromstring(z.read('word/document.xml'));assert len(tree.findall('.//{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath'))>20
assert len(PdfReader(root/'cad/钢框架方案图册.pdf').pages)==q['pdf_pages']
with ZipFile(root/'办公楼完整荷载课程设计成果.zip') as z:assert z.testzip() is None and 'manifest.json' in z.namelist()
print(json.dumps({'status':'PASS','files_sha256_verified':len(manifest['files']),'calculation_book_pages':len(book.pages),'cad_pages':q['pdf_pages'],'dxf_model_units':'mm','members_covered':len(q['covered_members']),'xlsx_checks':wb['构件验算'].max_row-1,'input_sha256':run['input_sha256']},ensure_ascii=False,indent=2))
