"""Independent equilibrium audit for the declared uniform self-weight model.

PASS means numerical consistency only; it is never structural code approval.
Units are m, kN and kN*m. Moments are summed about the original XYZ origin.
"""
import math
import numpy as np


def audit_analysis(tables, analysis):
    from explicit_model import normalize
    model, errors = normalize(tables)
    if errors:
        return {'status': 'FAIL', 'errors': errors}
    errors = []
    expected_members = model['members']
    members = analysis.get('members', [])
    nodes = analysis.get('nodes', [])
    if len(members) != len(expected_members) or {m['member_id'] for m in members} != set(expected_members):
        errors.append('分析构件编号或数量与输入不一致')
    if len(nodes) != len(model['nodes']) or {n['node_id'] for n in nodes} != set(model['nodes']):
        errors.append('分析节点编号或数量与输入不一致')
    try:
        for n in nodes:
            if not np.allclose(n['xyz_m'], model['nodes'][n['node_id']]['xyz'], rtol=0, atol=1e-9):
                errors.append('节点坐标改变：' + n['node_id'])
            if len(n['displacement_mm_rad']) != 6 or not np.isfinite(n['displacement_mm_rad']).all():
                errors.append('节点六自由度结果无效：' + n['node_id'])
        for m in members:
            if not np.isfinite(m['segment_end_actions_kN_kNm']).all():
                errors.append('杆端力含非有限值：' + m['member_id'])
    except (ValueError, KeyError, TypeError) as e:
        errors.append('结果字段无效：' + str(e))
    if errors:
        return {'schema_version': 'ExplicitNumericalAudit/1.0', 'status': 'FAIL', 'errors': errors}

    external = np.zeros(6)
    weight = 0.
    q_by_member = {}
    for mid, m in expected_members.items():
        s, mat = model['sections'][m['section_id']], model['materials'][m['material_id']]
        q = s['A'] * 1e-6 * mat['density_t_m3'] * 9.80665 * model['self_weight_factor']
        q_by_member[mid] = q
        force = np.array([0., 0., -q * m['length_m']])
        center = (np.array(model['nodes'][m['i_node']]['xyz']) + model['nodes'][m['j_node']]['xyz']) / 2
        external[:3] += force
        external[3:] += np.cross(center, force)
        weight += q * m['length_m']
    reactions = np.zeros(6)
    seen = set()
    expected_supports = {nid for nid, n in model['nodes'].items() if any(n['fix'])}
    for r in analysis.get('reactions', []):
        nid = r['node_id']
        if nid not in expected_supports or nid in seen:
            errors.append('支反力节点重复或不是输入支座：' + str(nid))
            continue
        seen.add(nid)
        f = np.array([r[k] for k in ('Fx_kN', 'Fy_kN', 'Fz_kN')])
        moment = np.array([r[k] for k in ('Mx_kNm', 'My_kNm', 'Mz_kNm')])
        if not np.isfinite(np.r_[f, moment]).all():
            errors.append('支反力含非有限值：' + nid)
            continue
        reactions[:3] += f
        reactions[3:] += moment + np.cross(model['nodes'][nid]['xyz'], f)
    if seen != expected_supports:
        errors.append('缺少输入支座反力')
    span = max(1., max(np.linalg.norm(n['xyz']) for n in model['nodes'].values()))
    force_tol = max(1e-6, weight * 1e-7)
    moment_tol = max(1e-6, weight * span * 1e-7)
    global_checks = []
    for k, name in enumerate(('Fx', 'Fy', 'Fz', 'Mx', 'My', 'Mz')):
        residual = float(reactions[k] + external[k])
        tolerance = force_tol if k < 3 else moment_tol
        global_checks.append({'component': name, 'external': float(external[k]), 'reaction': float(reactions[k]), 'residual': residual, 'tolerance': tolerance, 'unit': 'kN' if k < 3 else 'kN·m', 'status': 'PASS' if abs(residual) <= tolerance else 'FAIL'})
    details, release_checks, interfaces = [], [], []
    joint_actions = {nid: np.zeros(6) for nid in model["nodes"]}
    for m in members:
        mid = m['member_id']; source = expected_members[mid]
        if (m['i_node'],m['j_node'],m['section_id'],m['material_id']) != (source['i_node'],source['j_node'],source['section_id'],source['material_id']):
            errors.append('构件属性引用改变：' + mid)
        if not np.allclose(m['axes'],source['axes'],atol=1e-10,rtol=0) or not math.isclose(m['length_m'],source['length_m'],rel_tol=1e-10,abs_tol=1e-10):
            errors.append('构件局部轴或长度改变：' + mid)
        if not math.isclose(m['self_weight_kN_m'],q_by_member[mid],rel_tol=1e-10,abs_tol=1e-10):
            errors.append('构件自重强度与输入不一致：' + mid)
        forces = m['segment_end_actions_kN_kNm']
        if not forces or any(len(f) != 12 for f in forces):
            errors.append('分段端力长度无效：' + mid)
            continue
        ell = source['length_m'] / len(forces)
        q = np.array(source['axes']) @ np.array([0., 0., -q_by_member[mid]])
        for k, raw in enumerate(forces):
            f = np.array(raw)
            res_f = f[:3] + f[6:9] + q * ell
            res_m = f[3:6] + f[9:12] + np.cross([ell, 0., 0.], f[6:9]) + np.cross([ell/2, 0., 0.], q*ell)
            ft = max(1e-7, np.max(np.abs(f[np.r_[0:3, 6:9]])) * 1e-7)
            mt = max(1e-7, ft * ell, np.max(np.abs(f[np.r_[3:6, 9:12]])) * 1e-7)
            details.append({'member_id': mid, 'segment': k+1, 'force_residual_kN': res_f.tolist(), 'moment_residual_kNm': res_m.tolist(), 'force_tolerance_kN': float(ft), 'moment_tolerance_kNm': float(mt), 'status': 'PASS' if max(abs(res_f)) <= ft and max(abs(res_m)) <= mt else 'FAIL'})
        for k in range(len(forces)-1):
            residual = np.array(forces[k][6:12]) + forces[k+1][:6]
            interfaces.append({'member_id': mid, 'interface': k+1, 'force_residual_kN': residual[:3].tolist(), 'moment_residual_kNm': residual[3:].tolist(), 'status': 'PASS' if max(abs(residual[:3])) <= force_tol and max(abs(residual[3:])) <= moment_tol else 'FAIL'})
        axes = np.array(source['axes'])
        for nid, local in [(source['i_node'],forces[0][:6]), (source['j_node'],forces[-1][6:12])]:
            joint_actions[nid] += np.r_[np.array(local[:3]) @ axes, np.array(local[3:]) @ axes]
        for end, index in [('i', 0), ('j', -1)]:
            if source['hinge_'+end]:
                values = forces[index][4:6] if end == 'i' else forces[index][10:12]
                demand = max(abs(v) for v in values)
                release_checks.append({'member_id': mid, 'end': end, 'max_released_moment_kNm': demand, 'tolerance_kNm': 1e-6, 'status': 'PASS' if demand <= 1e-6 else 'FAIL'})
    reaction_by_node = {r['node_id']: np.array([r[k] for k in ('Fx_kN','Fy_kN','Fz_kN','Mx_kNm','My_kNm','Mz_kNm')]) for r in analysis.get('reactions', [])}
    joint_checks = []
    for nid, action in joint_actions.items():
        residual = action - reaction_by_node.get(nid, np.zeros(6))
        joint_checks.append({'node_id': nid, 'force_residual_kN': residual[:3].tolist(), 'moment_residual_kNm': residual[3:].tolist(), 'force_tolerance_kN': force_tol, 'moment_tolerance_kNm': moment_tol, 'status':'PASS' if max(abs(residual[:3])) <= force_tol and max(abs(residual[3:])) <= moment_tol else 'FAIL'})
    weight_error = float(analysis.get('weight_kN', math.nan)) - weight
    if not math.isfinite(weight_error) or abs(weight_error) > force_tol:
        errors.append('分析自重与按输入独立重算的自重不一致')
    status = 'FAIL' if errors or any(c['status'] == 'FAIL' for c in global_checks + details + release_checks + interfaces + joint_checks) else 'PASS'
    return {'schema_version': 'ExplicitNumericalAudit/1.0', 'status': status, 'scope': '仅核对自重线弹性分析的数值平衡及释放条件，不替代规范验算或独立求解器复核', 'errors': errors, 'independent_weight_kN': weight, 'weight_error_kN': weight_error, 'global_equilibrium': global_checks, 'segments_checked': len(details), 'segment_equilibrium': details, 'released_ends_checked': len(release_checks), 'release_checks': release_checks, 'interface_equilibrium': interfaces, 'joint_equilibrium': joint_checks}
