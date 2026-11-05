import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient


def test_office_api_reference_and_invalid_input_are_explicit():
 from app import app
 with TestClient(app) as c:
  r=c.get('/workflow/office-design/reference');assert r.status_code==200
  b=r.json()['bundle'];assert b['scope']=='office_superstructure'
  r=c.post('/workflow/office-design/run-stream',json={'payload':{'bundle':{'schema_version':'bad'}}});assert r.status_code==422
  assert c.get('/workflow/office-design/runs/not-a-run').status_code==404


def test_office_output_endpoint_never_accepts_client_fabricated_analysis():
 from app import app
 with TestClient(app) as c:
  r=c.post('/workflow/office-design/outputs',json={'payload':{'run_id':'0'*32,'design_status':'PASS','analysis':{}}})
  assert r.status_code==404
