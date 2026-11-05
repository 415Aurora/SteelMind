"""LangChain thin adapters: never accept client-fabricated analysis/checks."""
import json
from langchain.tools import tool

def _files(run_id,extensions):
 from office_api import outputs,OfficeRequest
 package=outputs(OfficeRequest(payload={'run_id':run_id}));return json.dumps({**package,'artifacts':[a for a in package['artifacts'] if a['name'].lower().endswith(extensions)]},ensure_ascii=False)

@tool
def generate_office_calculation_book(run_id:str)->str:
 """为已完成的办公楼运行生成计算书DOCX/PDF与结果表，保留真实验算及交接状态。"""
 return _files(run_id,('.docx','.pdf','.xlsx','.json'))

@tool
def generate_office_design_files(run_id:str)->str:
 """为已完成的办公楼运行生成DXF/PDF和成果包；仅使用服务端run_id对应输入。"""
 return _files(run_id,('.dxf','.pdf','.zip','.json'))
