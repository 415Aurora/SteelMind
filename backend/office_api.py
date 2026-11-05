"""Local office jobs. Export consumes only server-side completed run snapshots."""
from __future__ import annotations
import json,os,queue,re,threading
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter,HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel,Field
from office_contracts import reference_case,validate_office_bundle

router=APIRouter(prefix='/workflow/office-design',tags=['office-design'])
_jobs={};_lock=threading.RLock();_export_locks={}
class OfficeRequest(BaseModel):payload:dict=Field(default_factory=dict)


def root():
 p=Path(os.getenv('STEELMIND_OUTPUT_ROOT',str(Path(__file__).parent/'artifacts')))/'office-run-snapshots';p.mkdir(parents=True,exist_ok=True);return p


def load_run(run_id):
 if not re.fullmatch('[0-9a-f]{32}',run_id):raise HTTPException(404,'办公楼运行不存在')
 path=root()/(run_id+'.json')
 if not path.is_file():raise HTTPException(404,'办公楼运行尚未完成或不存在')
 result=json.loads(path.read_text())
 if result.get('run_id')!=run_id or result.get('ok') is not True:raise HTTPException(409,'该运行未完成有效分析')
 return result


def summary(r):
 return {k:r.get(k) for k in ('ok','run_id','status','analysis_status','design_status','coverage_status','building_status','input_sha256','original_input_sha256','engine_sha256','elapsed_seconds','scope','warnings','errors','iterations')}|{'code_check_summary':r.get('code_checks',{}).get('summary',{}),'verification_status':r.get('verification',{}).get('status'),'static_cases':list(r.get('analysis',{}).get('case_results',{}))}


def check_request(payload):
 b=payload.get('bundle') or reference_case();v=validate_office_bundle(b)
 if not v['ok']:raise HTTPException(422,v['errors'])
 return {**payload,'bundle':b}


@router.get('/reference')
def reference():return {'bundle':reference_case(),'scope':'reference_based_new_course_design','notice':'选择载入将使用已确认课程假定的新办公楼布置，保留旧自重模型作为独立案例'}


@router.post('/run-stream')
def run_stream(request:OfficeRequest):
 payload=check_request(request.payload);job_id=uuid4().hex;events=queue.Queue();done=object();cancel=threading.Event()
 with _lock:_jobs[job_id]={'run_id':job_id,'status':'running','cancel':cancel,'latest_progress':{}}
 def emit(value):
  with _lock:_jobs[job_id]['latest_progress']=value
  events.put({'type':'office_progress',**value})
 def worker():
  from office_design import run_office_design
  try:
   result=run_office_design(payload,progress=emit,cancelled=cancel.is_set,run_id=job_id);path=root()/(job_id+'.json');temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False));temporary.replace(path)
   with _lock:_jobs[job_id].update(status=result['status'],result=summary(result))
   events.put({'type':'workflow_completed','result':summary(result)})
  except Exception as exc:
   result={'ok':False,'run_id':job_id,'status':'cancelled' if cancel.is_set() else 'analysis_failed','design_status':'INCOMPLETE','errors':[str(exc)]}
   with _lock:_jobs[job_id].update(status=result['status'],result=result)
   events.put({'type':'workflow_completed','result':result})
  finally:events.put(done)
 threading.Thread(target=worker,name='office-'+job_id[:8],daemon=True).start()
 def stream():
  completed=False
  try:
   yield 'data: '+json.dumps({'type':'workflow_started','run_id':job_id})+'\n\n'
   while True:
    try:event=events.get(timeout=10)
    except queue.Empty:yield ': keepalive\n\n';continue
    if event is done:completed=True;break
    yield 'data: '+json.dumps(event,ensure_ascii=False)+'\n\n'
  finally:
   if not completed:cancel.set()
 return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})


@router.get('/runs/{run_id}')
def status(run_id:str):
 if not re.fullmatch('[0-9a-f]{32}',run_id):raise HTTPException(404,'办公楼运行不存在')
 with _lock:
  job=_jobs.get(run_id)
  if job:return {k:v for k,v in job.items() if k!='cancel'}
 return summary(load_run(run_id))


@router.post('/runs/{run_id}/cancel')
def cancel(run_id:str):
 with _lock:
  job=_jobs.get(run_id)
  if not job:raise HTTPException(404,'办公楼运行不存在')
  job['cancel'].set()
 return {'ok':True,'run_id':run_id,'status':'cancellation_requested'}


@router.get('/runs/{run_id}/viewer/{case_id}')
def viewer(run_id:str,case_id:str):
 from office_viewer import publish_office_viewer
 try:return publish_office_viewer(load_run(run_id),case_id)
 except ValueError as exc:raise HTTPException(422,str(exc)) from exc


@router.post('/outputs')
def outputs(request:OfficeRequest):
 from office_outputs import publish_office_outputs
 run_id=str(request.payload.get('run_id',''));run=load_run(run_id)
 with _lock:lock=_export_locks.setdefault(run_id,threading.Lock())
 with lock:
  saved=root()/(run_id+'-outputs.json')
  if saved.is_file():return json.loads(saved.read_text())
  result=publish_office_outputs(run);saved.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False));return result


@router.get('/runs/{run_id}/members/{member_id}')
def member(run_id:str,member_id:str):
 run=load_run(run_id);row=next((m for m in run['code_checks']['members'] if m['member_id']==member_id),None)
 if row is None:raise HTTPException(404,'本次办公楼运行没有该物理构件')
 return {'ok':True,'run_id':run_id,'input_sha256':run['input_sha256'],'design_status':run['design_status'],'building_status':run['building_status'],'member':row}
