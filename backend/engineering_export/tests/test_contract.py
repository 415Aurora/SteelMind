"""Boundary tests catch permissive inputs, broken references and false check decisions."""
from copy import deepcopy
import pytest
from steelmind_export.models import DesignBundle
from steelmind_export.validation import validate_bundle
from steelmind_export.examples import minimal_bundle, demo_bundle, analytic_bundle


def fixture():
    return {
        'schema_version':'1.0', 'project':{'name':'contract'},
        'provenance':{'data_kind':'upstream','source':'test'},
        'model':{
            'nodes':[{'id':'N1','x_m':0,'y_m':0},{'id':'N2','x_m':6,'y_m':0}],
            'materials':[{'id':'Q','name':'Q235','E_MPa':206000,'fy_MPa':235,'source':'test'}],
            'sections':[{'id':'H','name':'H300','shape':'H','h_mm':300,'b_mm':200,'tw_mm':8,'tf_mm':12,'A_mm2':7008,'Ix_mm4':113606784,'Iy_mm4':16011776,'Wx_mm3':757378.56,'Wy_mm3':160117.76,'property_basis':'idealized','source':'test'}],
            'members':[{'id':'B1','node_i':'N1','node_j':'N2','section_id':'H','material_id':'Q','kind':'beam'}],
            'supports':[{'node_id':'N1','ux':True,'uy':True,'rz':False},{'node_id':'N2','ux':False,'uy':True,'rz':False}],
        },
        'load_cases':[{'id':'L','name':'q','kind':'variable','source':'test','loads':[{'kind':'uniform_member','target_id':'B1','qy_kN_m':-10}]}],
        'combinations':[{'id':'U','name':'ULS','limit_state':'ULS','factors':{'L':1},'source':'test'},{'id':'S','name':'SLS','limit_state':'SLS','factors':{'L':1},'source':'test'}],
    }


def test_minimal_contract_defaults_and_draft():
    b=DesignBundle.model_validate(fixture())
    assert b.project.phase=='方案设计'
    assert b.model.members[0].release_i is False
    r=validate_bundle(b)
    assert r.valid and r.draft
    assert r.data_validation_status=='valid'
    assert r.upstream_check_summary=='INCOMPLETE'
    assert r.warnings and r.draft_reasons


@pytest.mark.parametrize('value',[True,'206000',float('nan'),float('inf'),-1,0])
def test_reject_bad_material_numbers(value):
    b=fixture(); b['model']['materials'][0]['E_MPa']=value
    assert not validate_bundle(b).valid


@pytest.mark.parametrize('mutate',[
    lambda b:b.update(schema_version='2.0'),
    lambda b:b['model']['members'][0].update(offset_i_m=1),
    lambda b:b['model']['nodes'][0].update(x_mm=3),
    lambda b:b['model']['members'][0].update(release_i=1),
    lambda b:b['model']['nodes'].append(deepcopy(b['model']['nodes'][0])),
    lambda b:b['model']['members'][0].update(node_j='missing'),
    lambda b:b['model']['members'][0].update(node_j='N1'),
    lambda b:b['model']['members'][0].update(section_id='missing'),
    lambda b:b['model']['members'][0].update(material_id='missing'),
    lambda b:b['model']['supports'].append(deepcopy(b['model']['supports'][0])),
    lambda b:b['model']['supports'][0].update(node_id='missing'),
    lambda b:b['model']['sections'][0].update(A_mm2=7100),
    lambda b:b['model']['sections'][0].update(tf_mm=160),
    lambda b:b['model']['sections'][0].update(tw_mm=201),
    lambda b:b['model']['sections'][0].update(property_basis='catalog',source=''),
    lambda b:b['combinations'][0]['factors'].update(missing=1),
    lambda b:b['load_cases'][0]['loads'][0].update(target_id='N1'),
    lambda b:b['load_cases'][0]['loads'][0].update(fx_kN=1),
    lambda b:b['load_cases'][0]['loads'][0].pop('qy_kN_m'),
])
def test_cross_and_schema_errors_return_report(mutate):
    b=fixture(); mutate(b)
    r=validate_bundle(b)
    assert not r.valid and r.errors
    assert all(i.code and i.path for i in r.errors)


def test_catalog_properties_are_not_overwritten():
    b=fixture(); s=b['model']['sections'][0]
    s.update(property_basis='catalog',A_mm2=8000,source='catalog page 1')
    assert validate_bundle(b).valid
    assert s['A_mm2']==8000


def check(**kwargs):
    c=dict(id='C',target_id='B1',combination_id='U',item='strength',status='PASS',demand=100,limit=200,comparator='<=',unit='MPa',utilization=.5,formula_text='sigma <= f',substitution='100 <= 200',source='teaching',clause='example',trace_ids=['T'])
    c.update(kwargs); return c


def with_check(**kwargs):
    b=fixture(); b['checks']=[check(**kwargs)]
    demand=b['checks'][0]['demand']
    b['traces']=[dict(id='T',name='stress',formula_text='M/W',inputs={'M':45},intermediate=[],
        result=demand if demand is not None else 45,unit='MPa',source='test',
        result_path='/checks/0/demand' if demand is not None else '/traces/0/inputs/M')]
    return b


@pytest.mark.parametrize('kwargs',[
    {'status':'FAIL'}, {'utilization':.7}, {'target_id':'no'}, {'combination_id':'no'},
    {'trace_ids':['no']}, {'status':'NA','na_reason':''}, {'unit':'cm'},
    {'comparator':'>=','demand':100,'limit':200,'status':'PASS','utilization':2},
    {'comparator':'abs<=','demand':-300,'limit':200,'status':'PASS','utilization':1.5},
])
def test_invalid_check_decisions_and_references(kwargs):
    assert not validate_bundle(with_check(**kwargs)).valid


@pytest.mark.parametrize('kwargs',[
    {}, {'status':'FAIL','demand':300,'utilization':1.5},
    {'comparator':'abs<=','demand':-100},
    {'comparator':'>=','demand':400,'limit':200,'utilization':.5},
    {'status':'NA','na_reason':'not applicable','demand':None,'limit':None,'utilization':None},
])
def test_valid_check_decisions(kwargs):
    assert validate_bundle(with_check(**kwargs)).valid


def test_fail_survives_incomplete_coverage():
    r=validate_bundle(with_check(status='FAIL',demand=300,utilization=1.5))
    assert r.valid and r.draft and r.upstream_check_summary=='FAIL'


def test_trace_pointer_and_nonfinite():
    b=with_check(); b['traces'][0]['result_path']='/checks/99/demand'
    assert not validate_bundle(b).valid
    b=with_check(); b['traces'][0]['inputs']['bad']=float('nan')
    assert not validate_bundle(b).valid
    b=with_check(); b['traces'][0]['result']=True
    assert not validate_bundle(b).valid


@pytest.mark.parametrize('block,record',[
    ('node_displacements',dict(node_id='N1',combination_id='U',ux_mm=0,uy_mm=0,rz_rad=0)),
    ('reactions',dict(node_id='N1',combination_id='U',fx_kN=0,fy_kN=30,mz_kNm=0)),
    ('member_end_forces',dict(member_id='B1',combination_id='U',Ni_kN=0,Vi_kN=30,Mi_kNm=0,Nj_kN=0,Vj_kN=30,Mj_kNm=0)),
    ('member_samples',dict(member_id='B1',combination_id='U',x_m=3,side='single',N_kN=0,V_kN=0,M_kNm=45)),
])
def test_result_duplicates_and_references(block,record):
    b=fixture(); b['analysis']={block:[record]}
    assert validate_bundle(b).valid
    b['analysis'][block].append(deepcopy(record))
    assert not validate_bundle(b).valid
    b['analysis'][block]=[dict(record,combination_id='missing')]
    assert not validate_bundle(b).valid
    entity='node_id' if block in ('node_displacements','reactions') else 'member_id'
    b['analysis'][block]=[dict(record,**{entity:'missing'})]
    assert not validate_bundle(b).valid


def test_sample_stations_and_two_sides():
    b=fixture(); p=dict(member_id='B1',combination_id='U',x_m=6.1,side='single',N_kN=0,V_kN=0,M_kNm=0)
    b['analysis']={'member_samples':[p]}; assert not validate_bundle(b).valid
    p['x_m']=3; p['side']='left'; b['analysis']['member_samples'].append(dict(p,side='right'))
    assert validate_bundle(b).valid


def test_coverage_complete_with_reasoned_na_and_metadata():
    b=with_check()
    b['provenance'].update(run_id='fixture-run', tool_versions={'fixture':'1.0'})
    b['analysis']={
        'node_displacements':[dict(node_id=node,combination_id=combo,ux_mm=0,uy_mm=0,rz_rad=0) for combo in ('U','S') for node in ('N1','N2')],
        'reactions':[dict(node_id=node,combination_id=combo,fx_kN=0,fy_kN=30,mz_kNm=0) for combo in ('U','S') for node in ('N1','N2')],
        'member_end_forces':[dict(member_id='B1',combination_id=combo,Ni_kN=0,Vi_kN=30,Mi_kNm=0,Nj_kN=0,Vj_kN=30,Mj_kNm=0) for combo in ('U','S')],
    }
    for item,combo,target in [('stability','U','B1'),('deflection','S','B1'),('drift','S','FRAME')]:
        b['checks'].append(check(id=item,item=item,target_id=target,combination_id=combo,status='NA',na_reason='scope exclusion',demand=None,limit=None,utilization=None))
    r=validate_bundle(b)
    assert r.valid and not r.draft and r.upstream_check_summary=='PASS'
    b['checks'][0]['source']=''
    r=validate_bundle(b); assert r.valid and r.draft


def test_unknown_check_does_not_replace_required_coverage():
    r=validate_bundle(with_check(item='custom'))
    assert r.valid and r.upstream_check_summary=='INCOMPLETE'


@pytest.mark.parametrize('builder',[minimal_bundle,demo_bundle,analytic_bundle])
def test_examples_valid_drafts(builder):
    r=validate_bundle(builder())
    assert r.valid, r.errors
    assert r.draft


def test_demo_has_deliberate_failure_and_unequal_spans():
    b=demo_bundle(); r=validate_bundle(b)
    assert r.upstream_check_summary=='FAIL'
    assert len(b['model']['nodes'])==12
    assert sorted({n['x_m'] for n in b['model']['nodes']})==[0,6,14]


def test_large_finite_section_is_reported_without_overflow():
    b=fixture(); b['model']['sections'][0].update(h_mm=1e200)
    report=validate_bundle(b)
    assert not report.valid and report.errors


@pytest.mark.parametrize('mutate',[
    lambda b:b['combinations'][0]['factors'].update(L=True),
    lambda b:b['analysis'].update(node_displacements=[dict(node_id='N1',combination_id='U',ux_mm=float('inf'),uy_mm=0,rz_rad=0)]),
    lambda b:b['checks'][0].update(demand=True),
    lambda b:b['traces'][0]['inputs'].update(v=True),
])
def test_strict_finite_every_numeric_block(mutate):
    b=with_check(); b['analysis']={}; mutate(b)
    assert not validate_bundle(b).valid


def test_rfc6901_escaped_pointer_and_reject_invalid_escapes():
    b=with_check(); b['traces'][0]['inputs']['a/b~c']=100
    b['traces'][0]['result_path']='/traces/0/inputs/a~1b~0c'
    assert validate_bundle(b).valid
    b['traces'][0]['result_path']='/traces/0/inputs/a~2b'
    assert not validate_bundle(b).valid


def test_invalid_mutated_model_is_revalidated():
    b=DesignBundle.model_validate(fixture()); b.model.nodes[0].x_m=float('nan')
    assert not validate_bundle(b).valid


def test_all_reasoned_na_satisfies_coverage_but_cannot_report_pass():
    b=with_check()
    b['analysis']={'node_displacements':[dict(node_id='N1',combination_id='U',ux_mm=0,uy_mm=0,rz_rad=0)]}
    b['checks']=[]
    for item,combo,target in [('strength','U','B1'),('stability','U','B1'),('deflection','S','B1'),('drift','S','FRAME')]:
        b['checks'].append(check(id=item,item=item,target_id=target,combination_id=combo,
            status='NA',na_reason='Outside declared scope',demand=None,limit=None,utilization=None))
    b['traces'][0].update(result_path='/traces/0/inputs/supplied',inputs={'supplied':100})
    report=validate_bundle(b)
    assert report.valid
    assert report.upstream_check_summary=='INCOMPLETE'
    assert report.draft
    assert any(issue.code=='no_pass_checks' for issue in report.warnings)
    assert not any(issue.code=='coverage_missing' for issue in report.warnings)


@pytest.mark.parametrize('result,path',[
    (101,'/checks/0/demand'),
    ('100','/checks/0/demand'),
    (100,'/project/name'),
    ('Contract','/project/name'),
    (100,''),
    (100,'/checks'),
    (100,'/checks/0'),
    (100,'/checks/0/utilization_missing'),
    (100,'/model/supports/0/ux'),
    (100,'/checks/0/na_reason'),
])
def test_trace_rejects_mismatching_or_nonscalar_target(result,path):
    b=with_check(); b['traces'][0].update(result=result,result_path=path)
    report=validate_bundle(b)
    assert not report.valid and report.errors
    assert any(issue.code.startswith('trace_') for issue in report.errors)


def test_trace_rejects_null_target():
    b=with_check(); b['traces'][0].update(result=100,result_path='/checks/0/limit')
    b['checks'][0]['limit']=None
    assert not validate_bundle(b).valid


@pytest.mark.parametrize('target,result,valid',[
    (100,100+5e-8,True), (100,100+2e-7,False),
    (0,5e-10,True), (0,2e-9,False),
    ('steel','steel',True), ('steel','Steel',False),
])
def test_trace_numeric_tolerance_and_exact_strings(target,result,valid):
    b=with_check(); b['traces'][0]['inputs']['expected']=target
    b['traces'][0].update(result=result,result_path='/traces/0/inputs/expected')
    assert validate_bundle(b).valid is valid


def test_escaped_trace_pointer_must_also_match_result():
    b=with_check(); b['traces'][0]['inputs']['a/b~c']=1
    b['traces'][0]['result_path']='/traces/0/inputs/a~1b~0c'
    assert not validate_bundle(b).valid
