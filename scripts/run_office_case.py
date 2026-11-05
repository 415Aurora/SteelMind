#!/usr/bin/env python3
"""Office reference G/Q/W/E case; imports only the selected project environment."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'backend'))
from office_contracts import reference_case,validate_office_bundle
from office_design import run_office_design

def main():
 p=argparse.ArgumentParser(description='办公楼完整荷载课程案例');p.add_argument('--input',type=Path);p.add_argument('--output',type=Path,default=ROOT/'artifacts'/'office-case');p.add_argument('--schemes',default='0,4');p.add_argument('--validate-only',action='store_true');p.add_argument('--no-drawings',action='store_true');a=p.parse_args();bundle=json.loads(a.input.read_text()) if a.input else reference_case()
 if a.validate_only:
  v=validate_office_bundle(bundle);print(json.dumps(v,ensure_ascii=False,indent=2));return 0 if v['ok'] else 2
 try:indices=[int(v.strip()) for v in a.schemes.split(',')]
 except ValueError:p.error('--schemes需要逗号分隔的整数')
 result=run_office_design({'bundle':bundle,'options':{'scheme_indices':indices}},progress=lambda value:print(json.dumps(value,ensure_ascii=False),flush=True))
 if not result['ok']:print(json.dumps(result,ensure_ascii=False));return 2
 from office_outputs import write_office_outputs
 generated=write_office_outputs(result,a.output,include_drawings=not a.no_drawings);print(json.dumps(generated['manifest'],ensure_ascii=False,indent=2));return 0 if generated['manifest']['file_generation_status']=='success' else 3
if __name__=='__main__':raise SystemExit(main())
