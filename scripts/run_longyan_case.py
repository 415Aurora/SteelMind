#!/usr/bin/env python3
"""Reproduce the original XYZ self-weight case without a running gateway/API key."""
import argparse
import hashlib
import json
import math
import platform
from importlib import metadata
import os
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'examples/longyan-selfweight/input.json')
    parser.add_argument('--output', type=Path, default=ROOT/'backend/artifacts/case-runs')
    parser.add_argument('--verify-only', action='store_true', help='Skip DOCX/PDF/CAD generation')
    args = parser.parse_args()
    run = args.output.resolve()/('longyan-'+uuid4().hex[:12]); run.mkdir(parents=True)
    os.environ['STEEL_ARTIFACT_DIR'] = str(run/'downloads')
    os.environ['STEELMIND_OUTPUT_ROOT'] = str(run/'runs')
    from explicit_model import run_explicit_model, input_hash
    tables = json.loads(args.input.read_text(encoding='utf-8'))
    def write(name, value):
        (run/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    write('input.json', tables)
    packages={}
    for name in ('numpy','openseespy','fastapi','python-docx','openpyxl','ezdxf','matplotlib','pydantic'):
        try: packages[name]=metadata.version(name)
        except metadata.PackageNotFoundError: packages[name]=None
    import explicit_model, explicit_audit
    write('runtime-info.json', {'python_version':sys.version,'platform':platform.platform(),'virtual_environment':sys.prefix!=sys.base_prefix,'python_executable':sys.executable,'packages':packages,'module_locations':{'explicit_model':explicit_model.__file__,'explicit_audit':explicit_audit.__file__},'project_root':str(ROOT)})

    coarse = run_explicit_model(tables, segments_per_member=8)
    fine = run_explicit_model(tables, segments_per_member=16)
    write('analysis-8.json', coarse); write('analysis-16.json', fine)
    if not coarse.get('ok') or not fine.get('ok'):
        print(json.dumps({'ok': False, 'output': str(run), 'errors': [coarse.get('errors'), fine.get('errors')]}, ensure_ascii=False)); return 1
    by_id = {n['node_id']: n for n in fine['analysis']['nodes']}
    max_d = max(abs(v-w) for n in coarse['analysis']['nodes'] for v,w in zip(n['displacement_mm_rad'][:3],by_id[n['node_id']]['displacement_mm_rad'][:3]))
    checks = lambda r: {(m['member_id'],c['item']):c for m in r['code_checks']['members'] for c in m['checks']}
    a,b = checks(coarse),checks(fine)
    deltas = {item: max((abs(c['demand']-b[k]['demand']) for k,c in a.items() if k[1]==item and c.get('demand') is not None and b[k].get('demand') is not None),default=0.) for item in ('section_strength','beam_deflection')}
    mesh = {'status': 'PASS' if max_d <= 1e-5 and deltas['section_strength']<=1e-4 and deltas['beam_deflection']<=1e-5 else 'FAIL', 'coarse_segments':8,'fine_segments':16,'max_node_translation_difference_mm':max_d,'max_stress_difference_MPa':deltas['section_strength'],'max_relative_beam_deflection_difference_mm':deltas['beam_deflection'],'limits':{'node_translation_mm':1e-5,'stress_MPa':1e-4,'beam_deflection_mm':1e-5},'scope':'同一求解器的分段细化对照，不是独立工程复核'}
    write('mesh-comparison.json', mesh)
    bill = {}
    for m in coarse['analysis']['members']:
        s=coarse['analysis']['sections'][m['section_id']];mat=coarse['analysis']['materials'][m['material_id']]
        row=bill.setdefault(m['section_id'], {'section_id':m['section_id'],'name':s.get('section_name'),'count':0,'length_m':0.,'steel_mass_t':0.})
        row['count']+=1;row['length_m']+=m['length_m'];row['steel_mass_t']+=s['A']*1e-6*m['length_m']*mat['density_t_m3']
    write('section-quantities.json', list(bill.values()))
    summary={'ok':mesh['status']=='PASS','input_sha256':input_hash(tables),'nodes':len(coarse['analysis']['nodes']),'members':len(coarse['analysis']['members']),'numerical_audit_status':coarse['numerical_audit']['status'],'mesh_comparison_status':mesh['status'],'upstream_check_summary':coarse['upstream_check_summary'],'code_check_counts':coarse['code_checks']['summary'],'file_generation_status':'not_requested','output':str(run)}
    if args.input.resolve() == (ROOT/'examples/longyan-selfweight/input.json').resolve():
        expected=json.loads((ROOT/'examples/longyan-selfweight/expected.json').read_text())
        node_max=max(math.sqrt(sum(v*v for v in n['displacement_mm_rad'][:3])) for n in coarse['analysis']['nodes'])
        beam_max=max((c.get('demand') or 0 for m in coarse['code_checks']['members'] for c in m['checks'] if c['item']=='beam_deflection'),default=0.)
        passed=(summary['input_sha256']==expected['input_sha256'] and summary['nodes']==expected['nodes'] and summary['members']==expected['members'] and abs(coarse['analysis']['weight_kN']-expected['weight_kN'])<=expected['weight_tolerance_kN'] and abs(node_max-expected['max_node_displacement_mm'])<=expected['max_node_tolerance_mm'] and abs(beam_max-expected['max_beam_relative_deflection_mm'])<=expected['max_beam_tolerance_mm'] and summary['upstream_check_summary']==expected['upstream_check_summary'])
        baseline={'status':'PASS' if passed else 'FAIL','weight_kN':coarse['analysis']['weight_kN'],'max_node_displacement_mm':node_max,'max_beam_relative_deflection_mm':beam_max,'expected':expected}
        write('baseline-comparison.json',baseline);summary['baseline_comparison_status']=baseline['status'];summary['ok']=summary['ok'] and passed
    else:summary['baseline_comparison_status']='not_applicable_custom_input'
    if not args.verify_only:
        from app import load_tools
        load_tools()
        from explicit_outputs import publish_explicit_outputs
        from explicit_viewer import build_html
        artifacts=publish_explicit_outputs(tables,coarse)
        scene,html=build_html(tables,coarse);(run/'三维结果.html').write_text(html,encoding='utf-8')
        summary['file_generation_status']='partial' if any(a['name'].endswith('缺项.json') for a in artifacts) else 'success'
        write('artifacts.json',artifacts)
        # Local artifacts are usable offline; URLs are supplementary gateway references.
    write('summary.json',summary)
    manifest=[{'path':str(p.relative_to(run)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(run.rglob('*')) if p.is_file()]
    write('files.json',manifest)
    print(json.dumps(summary,ensure_ascii=False,indent=2));return 0 if summary['ok'] else 1

if __name__=='__main__':
    raise SystemExit(main())
