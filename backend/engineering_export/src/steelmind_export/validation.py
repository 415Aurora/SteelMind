"""Schema, relational and check-decision validation without solving the model."""
import math
import re
from typing import Any, Literal
from pydantic import Field, ValidationError
from .models import ContractModel, DesignBundle
from .coverage import COVERAGE_PROFILE, SUPPORTED_ITEMS, missing_checks


class Issue(ContractModel):
    code: str
    message: str
    path: str


class ValidationReport(ContractModel):
    valid: bool
    errors: list[Issue] = Field(default_factory=list)
    warnings: list[Issue] = Field(default_factory=list)
    data_validation_status: Literal['valid', 'invalid']
    upstream_check_summary: Literal['PASS', 'FAIL', 'INCOMPLETE']
    draft: bool
    draft_reasons: list[str] = Field(default_factory=list)
    coverage_profile: str = COVERAGE_PROFILE


def _pointer_part(value: Any) -> str:
    return str(value).replace('~', '~0').replace('/', '~1')


def _path(*parts: Any) -> str:
    return '/' + '/'.join(_pointer_part(p) for p in parts)


def resolve_pointer(document: Any, pointer: str) -> Any:
    """Resolve RFC 6901; malformed escapes and noncanonical array indices fail."""
    if pointer == '':
        return document
    if not pointer.startswith('/'):
        raise ValueError('JSON pointer must start with /')
    current = document
    for raw in pointer[1:].split('/'):
        if re.search(r'~(?![01])', raw):
            raise ValueError('Invalid JSON pointer escape')
        token = raw.replace('~1', '/').replace('~0', '~')
        if isinstance(current, list):
            if not re.fullmatch(r'0|[1-9][0-9]*', token):
                raise ValueError('Invalid array index')
            current = current[int(token)]
        elif isinstance(current, dict):
            current = current[token]
        else:
            raise ValueError('Pointer traverses a scalar')
    return current


def validate_bundle(data: dict | DesignBundle) -> ValidationReport:
    errors: list[Issue] = []
    warnings: list[Issue] = []
    reasons: list[str] = []

    def error(code, message, path):
        errors.append(Issue(code=code, message=message, path=path))

    def draft(code, message, path='/'):
        warnings.append(Issue(code=code, message=message, path=path))
        if message not in reasons:
            reasons.append(message)

    try:
        # Revalidation also protects callers that used model_construct or mutated instances.
        bundle = DesignBundle.model_validate(data.model_dump() if isinstance(data, DesignBundle) else data)
    except (ValidationError, ValueError, TypeError) as exc:
        if isinstance(exc, ValidationError):
            for issue in exc.errors(include_url=False):
                error('schema.' + issue['type'], issue['msg'], _path(*issue['loc']))
        else:
            error('schema.invalid', str(exc), '/')
        return ValidationReport(valid=False, errors=errors, data_validation_status='invalid',
                                upstream_check_summary='INCOMPLETE', draft=True,
                                draft_reasons=['输入数据未通过结构验证'])

    model = bundle.model

    def unique(records, key, path):
        seen = set()
        for index, record in enumerate(records):
            value = getattr(record, key)
            if value in seen:
                error('duplicate_id', f'Duplicate {key}: {value}', f'{path}/{index}/{key}')
            seen.add(value)

    for records, key, path in [
        (model.nodes,'id','/model/nodes'),(model.members,'id','/model/members'),
        (model.materials,'id','/model/materials'),(model.sections,'id','/model/sections'),
        (model.supports,'node_id','/model/supports'),(bundle.load_cases,'id','/load_cases'),
        (bundle.combinations,'id','/combinations'),(bundle.checks,'id','/checks'),
        (bundle.traces,'id','/traces'),
    ]:
        unique(records,key,path)
    nodes = {n.id:n for n in model.nodes}
    members = {m.id:m for m in model.members}
    sections = {s.id:s for s in model.sections}
    materials = {m.id:m for m in model.materials}
    combos = {c.id:c for c in bundle.combinations}
    cases = {c.id:c for c in bundle.load_cases}
    traces = {t.id:t for t in bundle.traces}

    for records, block in ((model.materials, 'materials'), (model.sections, 'sections'),
                           (bundle.load_cases, 'load_cases'), (bundle.combinations, 'combinations')):
        for i, record in enumerate(records):
            if not record.source.strip():
                prefix = '/model' if block in ('materials', 'sections') else ''
                draft('source_missing', f'Missing source: {block}/{record.id}', f'{prefix}/{block}/{i}/source')
    provenance = bundle.provenance
    if (not provenance.source.strip() or not provenance.run_id.strip() or not provenance.tool_versions
            or any(not value.strip() for value in provenance.tool_versions.values())):
        draft('provenance_missing', 'Upstream source, run_id and tool_versions must be supplied for a traceable report', '/provenance')

    for i, node in enumerate(model.nodes):
        for field in ('x_m', 'y_m'):
            if not math.isfinite(getattr(node, field) * 1000):
                error('coordinate_numeric_range', 'Coordinate cannot be represented in CAD millimetres',
                      _path('model', 'nodes', i, field))

    def reference(value, allowed, path):
        if value not in allowed:
            error('reference_missing', f'Unknown reference: {value}', path)

    for i, material in enumerate(model.materials):
        for field in ('E_MPa','fy_MPa'):
            if getattr(material,field) <= 0:
                error('positive_required',f'{field} must be positive',_path('model','materials',i,field))
    for i, s in enumerate(model.sections):
        base = _path('model','sections',i)
        positive = True
        for field in ('h_mm','b_mm','tw_mm','tf_mm','A_mm2','Ix_mm4','Iy_mm4','Wx_mm3','Wy_mm3'):
            if getattr(s,field) <= 0:
                positive = False
                error('positive_required',f'{field} must be positive',f'{base}/{field}')
        if 2*s.tf_mm >= s.h_mm or s.tw_mm >= s.b_mm:
            error('section_geometry','Require 2 tf < h and tw < b',base)
            positive = False
        if s.property_basis == 'catalog':
            if not s.source.strip():
                error('catalog_source','Catalog properties require source',f'{base}/source')
        elif positive:
            h,b,tw,tf=s.h_mm,s.b_mm,s.tw_mm,s.tf_mm
            hw=h-2*tf
            try:
                A=2*b*tf+hw*tw
                Ix=(b*h**3-(b-tw)*hw**3)/12
                Iy=(2*tf*b**3+hw*tw**3)/12
                if not all(math.isfinite(v) and v > 0 for v in (A,Ix,Iy)):
                    raise ArithmeticError('Derived section properties exceed numeric range')
            except (ArithmeticError, OverflowError):
                error('section_numeric_range','Idealized section properties exceed supported numeric range',base)
                continue
            values={'A_mm2':(A,'2*b*tf+(h-2*tf)*tw'),
                    'Ix_mm4':(Ix,'[b*h^3-(b-tw)*(h-2*tf)^3]/12'),
                    'Iy_mm4':(Iy,'[2*tf*b^3+(h-2*tf)*tw^3]/12'),
                    'Wx_mm3':(2*Ix/h,'2*Ix/h'),'Wy_mm3':(2*Iy/b,'2*Iy/b')}
            for field,(expected,formula) in values.items():
                if abs(getattr(s,field)-expected)/expected > .01+1e-12:
                    error('section_property_mismatch',f'{field} differs >1% from {formula} = {expected:g}; input retained',f'{base}/{field}')
    lengths = {}
    for i, m in enumerate(model.members):
        base=_path('model','members',i)
        for field,allowed in [('node_i',nodes),('node_j',nodes),('section_id',sections),('material_id',materials)]:
            reference(getattr(m,field),allowed,f'{base}/{field}')
        if m.node_i in nodes and m.node_j in nodes:
            a,z=nodes[m.node_i],nodes[m.node_j]
            length=math.hypot(z.x_m-a.x_m,z.y_m-a.y_m)
            lengths[m.id]=length
            if not math.isfinite(length):
                error('length_numeric_range','Derived member length exceeds numeric range',base)
            elif length <= 1e-12:
                error('zero_length_member','Member length must be greater than zero',base)
    for i,support in enumerate(model.supports):
        reference(support.node_id,nodes,_path('model','supports',i,'node_id'))
    for i,case in enumerate(bundle.load_cases):
        for j,load in enumerate(case.loads):
            base=_path('load_cases',i,'loads',j)
            reference(load.target_id,nodes if load.kind=='nodal' else members,f'{base}/target_id')
            fields=('fx_kN','fy_kN','mz_kNm') if load.kind=='nodal' else ('qx_kN_m','qy_kN_m')
            if all(getattr(load,key) is None for key in fields):
                error('empty_load','At least one load component is required',base)
    for i,combo in enumerate(bundle.combinations):
        for case_id in combo.factors:
            reference(case_id,cases,_path('combinations',i,'factors',case_id))
    for block,entity,allowed in [('node_displacements','node_id',nodes),('reactions','node_id',nodes),
                                 ('member_end_forces','member_id',members),('member_samples','member_id',members)]:
        seen=set()
        for i,record in enumerate(getattr(bundle.analysis,block)):
            base=_path('analysis',block,i)
            target=getattr(record,entity)
            reference(target,allowed,f'{base}/{entity}')
            reference(record.combination_id,combos,f'{base}/combination_id')
            key=(target,record.combination_id)
            if block=='member_samples':
                key += (record.x_m,record.side)
                if record.x_m < 0 or (target in lengths and record.x_m > lengths[target]+1e-9):
                    error('sample_out_of_range','Sample x_m must be in [0, member length]',f'{base}/x_m')
            if key in seen:
                error('duplicate_result','Duplicate entity/combination/station result',base)
            seen.add(key)
    sample_sides = {}
    for i, record in enumerate(bundle.analysis.member_samples):
        key = (record.member_id, record.combination_id, record.x_m)
        sides = sample_sides.setdefault(key, set())
        sides.add(record.side)
        if 'single' in sides and len(sides) > 1:
            error('sample_side_conflict', 'A station cannot mix single with left/right samples',
                  _path('analysis', 'member_samples', i, 'side'))
    constrained = {s.node_id for s in model.supports if s.ux or s.uy or s.rz}
    for block, entity, expected in (('node_displacements', 'node_id', set(nodes)),
                                    ('member_end_forces', 'member_id', set(members)),
                                    ('reactions', 'node_id', constrained)):
        records = getattr(bundle.analysis, block)
        for combo in bundle.combinations:
            supplied = {getattr(record, entity) for record in records if record.combination_id == combo.id}
            missing = sorted(expected - supplied)
            if missing:
                draft('analysis_coverage_missing',
                      f'Missing {block} for combination={combo.id}: {", ".join(missing)}',
                      _path('analysis', block))
    canonical=bundle.model_dump(mode='json')
    for i,trace in enumerate(bundle.traces):
        base=_path('traces',i)
        for field in ('formula_text', 'unit', 'source'):
            if not getattr(trace, field).strip():
                draft('trace_metadata_missing', f'Trace {trace.id}: missing {field}', f'{base}/{field}')
        try:
            target=resolve_pointer(canonical,trace.result_path)
        except (ValueError,KeyError,IndexError,TypeError):
            error('trace_pointer','Unresolvable RFC 6901 result_path',f'{base}/result_path')
            continue
        if isinstance(target,str):
            matches=isinstance(trace.result,str) and trace.result==target
        elif isinstance(target,(int,float)) and not isinstance(target,bool):
            matches=(isinstance(trace.result,(int,float)) and not isinstance(trace.result,bool)
                     and math.isclose(trace.result,target,rel_tol=1e-9,abs_tol=1e-9))
        else:
            error('trace_target_scalar','Trace result_path must reference a string or finite number',f'{base}/result_path')
            continue
        if not matches:
            error('trace_result_mismatch','Trace result disagrees with the scalar at result_path',f'{base}/result')
    unsupported=False
    for i,c in enumerate(bundle.checks):
        base=_path('checks',i)
        reference(c.target_id,set(members)|{'FRAME'},f'{base}/target_id')
        reference(c.combination_id,combos,f'{base}/combination_id')
        for j,trace_id in enumerate(c.trace_ids):
            reference(trace_id,traces,f'{base}/trace_ids/{j}')
        if c.item not in SUPPORTED_ITEMS:
            unsupported=True
            draft('unsupported_check',f'Check {c.id}: custom item {c.item} is outside teaching coverage',base)
        for field in ('source','clause','formula_text','substitution','trace_ids'):
            value=getattr(c,field)
            if not value or isinstance(value,str) and not value.strip():
                draft('check_metadata_missing',f'Check {c.id}: missing {field}',f'{base}/{field}')
        if c.status=='NA':
            if not c.na_reason.strip():
                error('na_reason_required','NA requires an explanation',f'{base}/na_reason')
            continue
        if c.demand is None or c.limit is None:
            unsupported=True
            draft('check_numeric_missing',f'Check {c.id}: missing numeric demand or limit',base)
            continue
        demand=abs(c.demand) if c.comparator=='abs<=' else c.demand
        passed=demand>=c.limit if c.comparator=='>=' else demand<=c.limit
        if (c.status=='PASS') != passed:
            error('check_status_mismatch','Check status disagrees with numeric comparison',f'{base}/status')
        denominator=c.demand if c.comparator=='>=' else c.limit
        numerator=c.limit if c.comparator=='>=' else demand
        if denominator > 0 and c.limit > 0:
            expected=numerator/denominator
            if c.utilization is not None and not math.isclose(c.utilization,expected,rel_tol=1e-6,abs_tol=1e-9):
                error('utilization_mismatch',f'Expected utilization {expected:g}',f'{base}/utilization')
        else:
            unsupported=True
            draft('utilization_unsupported',f'Check {c.id}: utilization needs positive threshold and denominator',base)
    for target,combo,item in missing_checks(bundle):
        draft('coverage_missing',f'Missing {item}: target={target}, combination={combo}', '/checks')
    if not bundle.combinations:
        draft('no_combinations','No combinations supplied','/combinations')
    if not any(bundle.analysis.model_dump().values()):
        draft('no_analysis','No analysis results supplied','/analysis')
    if not bundle.checks:
        draft('no_checks','No upstream checks supplied','/checks')
    has_pass = any(c.status == 'PASS' for c in bundle.checks)
    if bundle.checks and not has_pass:
        draft('no_pass_checks','No upstream check has PASS status; NA is an exclusion, not a passing check','/checks')
    if bundle.provenance.data_kind=='demonstration':
        draft('demonstration','Demonstration data; not an engineering verification','/provenance/data_kind')
    elif bundle.provenance.data_kind=='analytic_benchmark':
        draft('analytic_benchmark','Analytic benchmark data; not a final engineering design','/provenance/data_kind')
    if any(combo.limit_state == 'ANALYSIS' for combo in bundle.combinations):
        draft('analysis_only_combination',
              'ANALYSIS is a recorded model load state, not a normative ULS/SLS design combination',
              '/combinations')
    summary='FAIL' if any(c.status=='FAIL' for c in bundle.checks) else (
        'INCOMPLETE' if not has_pass or not bundle.combinations or missing_checks(bundle) or unsupported
        or any(combo.limit_state == 'ANALYSIS' for combo in bundle.combinations) else 'PASS')
    if errors:
        draft('invalid_data','Input contains validation errors')
    return ValidationReport(valid=not errors,errors=errors,warnings=warnings,
                            data_validation_status='invalid' if errors else 'valid',
                            upstream_check_summary=summary,draft=bool(reasons),draft_reasons=reasons)
