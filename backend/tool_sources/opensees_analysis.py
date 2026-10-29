"""参数化二维钢框架 OpenSeesPy 建模、静力分析及脚本生成工具。

单位：几何 mm（输入 m），力 N（输入 kN），E N/mm2，A mm2，Iz mm4。
该工具建立线弹性平面框架；Fy 仅作为材料元数据写入脚本/结果，不进行塑性或规范设计验算。
"""
from __future__ import annotations

import json
import math
import threading
import textwrap

from langchain.tools import tool
from tools.structural_calc import _get_section


# OpenSeesPy 使用进程级全局模型状态；避免并发请求 wipe/建模互相覆盖。
_OPENSEES_LOCK = threading.RLock()


def _ops(name, *args):
    import openseespy.opensees as ops
    return getattr(ops, name)(*args)


def _positive_list(value, count, label, default):
    if value is None:
        values = [float(default)] * count
    elif isinstance(value, (int, float)):
        values = [float(value)] * count
    elif isinstance(value, list) and len(value) == count:
        values = [float(x) for x in value]
    else:
        raise ValueError(f"{label} 必须是单个数值或长度为 {count} 的数组")
    if any(not math.isfinite(x) or x <= 0 for x in values):
        raise ValueError(f"{label} 中的数值必须为有限正数")
    return values


def _nonnegative_list(value, count, label, default=0):
    if value is None:
        values = [float(default)] * count
    elif isinstance(value, (int, float)):
        values = [float(value)] * count
    elif isinstance(value, list) and len(value) == count:
        values = [float(x) for x in value]
    else:
        raise ValueError(f"{label} 必须是单个数值或长度为 {count} 的数组")
    if any(not math.isfinite(x) or x < 0 for x in values):
        raise ValueError(f"{label} 中的数值必须为有限非负数")
    return values


def _signed_list(value, count, label, default=0):
    if value is None:
        values = [float(default)] * count
    elif isinstance(value, (int, float)):
        values = [float(value)] * count
    elif isinstance(value, list) and len(value) == count:
        values = [float(x) for x in value]
    else:
        raise ValueError(f"{label} 必须是单个数值或长度为 {count} 的数组")
    if any(not math.isfinite(x) for x in values):
        raise ValueError(f"{label} 中的数值必须为有限数")
    return values


def _resolve_section(data, role):
    section_data = (data.get("sections") or {}).get(role, {})
    section_data = section_data if isinstance(section_data, dict) else {}
    name = data.get(f"{role}_section") or section_data.get("name") or section_data.get("section")
    sec = _get_section(name) if name else None
    if not name:
        raise ValueError(f"{role}必须填写本地截面库中的型号；请通过 /sections 查询 H 型钢库")
    if sec is None:
        raise ValueError(f"无法识别{role}截面 {name!r}；请从本地合并截面库中选择型号（热轧H型钢或WH-前缀焊接Q235型钢）")
    # Never let ad-hoc properties override the catalog values used by OpenSees.
    A = float(sec["A"])
    Iz = float(sec["Ix"])
    if not math.isfinite(A) or not math.isfinite(Iz) or A <= 0 or Iz <= 0:
        raise ValueError(f"{role}截面面积 A 和惯性矩 Iz 必须为有限正数")
    return {"name": sec["name"], "designation": sec["designation"],
            "A_mm2": A, "Iz_mm4": Iz, "Iy_mm4": float(sec["Iy"]),
            "catalog_standard": sec["catalog_standard"], "catalog_id": sec["catalog_id"]}


def _normalize(raw):
    d = json.loads(raw) if isinstance(raw, str) else dict(raw)
    geometry = d.get("geometry") or d
    material = d.get("material") or d.get("materials") or {}
    loads = d.get("loads") or d
    bays = int(geometry.get("bays", 1))
    stories = int(geometry.get("stories", 1))
    if not 1 <= bays <= 30 or not 1 <= stories <= 30:
        raise ValueError("跨数和层数必须在 1 到 30 之间")
    spans = _positive_list(geometry.get("bay_widths_m") or geometry.get("bay_m"), bays, "bay_widths_m", 6)
    height_input = geometry.get("story_heights_m") or None
    if height_input is None and geometry.get("height_m") is not None:
        # Legacy height_m represented total building/eave height.
        height_input = float(geometry["height_m"]) / stories
    heights = _positive_list(height_input, stories, "story_heights_m", 3)
    support = geometry.get("base_support", d.get("base_support", "fixed"))
    if support not in ("fixed", "pinned"):
        raise ValueError("base_support 仅支持 fixed 或 pinned")
    E = float(material.get("E_MPa", material.get("E_mpa", d.get("E_mpa", 206000))))
    fy = material.get("Fy_MPa", material.get("fy_mpa"))
    fy = float(fy) if fy is not None else None
    if not math.isfinite(E) or E <= 0 or (fy is not None and (not math.isfinite(fy) or fy <= 0)):
        raise ValueError("材料 E 与可选 Fy 必须为有限正数")
    q_raw = loads.get("q_by_story_kN_per_m", loads.get("q_kNm", loads.get("q_kN_per_m", loads.get("dead", 0))))
    q = _nonnegative_list(q_raw, stories, "q_by_story_kN_per_m")
    lateral_raw = loads.get("lateral_by_story_kN", loads.get("lateral_kn", 0))
    lateral = _signed_list(lateral_raw, stories, "lateral_by_story_kN")
    # 新接口支持按层指定“总层剪力”；旧 lateral_kn 保持为每个节点施加的荷载。
    lateral_is_story_total = "lateral_by_story_kN" in loads
    beam = _resolve_section({**d, **(d.get("sections") or {})}, "beam")
    col = _resolve_section({**d, **(d.get("sections") or {})}, "column")
    member_sections = {}
    for member_id, value in (d.get("member_sections") or {}).items():
        mid = str(member_id).strip()
        role = "column" if mid.startswith("C-") else "beam" if mid.startswith("B-") else None
        if not mid or role is None:
            raise ValueError(f"逐构件截面编号 {member_id!r} 无效；编号需以 C- 或 B- 开头")
        section_input = value if isinstance(value, dict) else {"name": str(value)}
        member_sections[mid] = _resolve_section({f"{role}_section": section_input.get("name") or section_input.get("section"),
                                                  f"{role}_properties": section_input}, role)
    mesh_segments = int(d.get("mesh_segments_per_member", 8))
    if not 2 <= mesh_segments <= 32:
        raise ValueError("mesh_segments_per_member 必须在 2 到 32 之间")
    return {
        "geometry": {"bays": bays, "stories": stories, "bay_widths_m": spans,
                     "story_heights_m": heights, "base_support": support},
        "material": {"name": material.get("name", material.get("steel_grade", "未指定")), "E_MPa": E, "Fy_MPa": fy},
        "loads": {"q_by_story_kN_per_m": q, "lateral_by_story_kN": lateral,
                  "lateral_is_story_total": lateral_is_story_total},
        "sections": {"beam": beam, "column": col},
        "member_sections": member_sections,
        "mesh_segments_per_member": mesh_segments,
        "expected": d.get("expected") or {},
    }


def _make_script(config):
    encoded = json.dumps(config, ensure_ascii=False, indent=2)
    template = textwrap.dedent('''\
        """SteelMind 生成的参数化二维钢框架线弹性分析脚本。
        单位：m/kN 输入；模型内部 mm/N。Fy 是记录字段，不参与本线弹性分析。
        安装：python -m pip install openseespy
        """
        import json
        import openseespy.opensees as ops

        CONFIG = json.loads(__CONFIG_JSON__)
        g, mat, loads, secs = CONFIG["geometry"], CONFIG["material"], CONFIG["loads"], CONFIG["sections"]
        bays, stories = g["bays"], g["stories"]
        x = [0.0]
        for width in g["bay_widths_m"]: x.append(x[-1] + width)
        y = [0.0]
        for height in g["story_heights_m"]: y.append(y[-1] + height)
        ops.wipe()
        ops.model("basic", "-ndm", 2, "-ndf", 3)
        ops.geomTransf("Linear", 1)
        ops.geomTransf("Linear", 2)
        segments = CONFIG.get("mesh_segments_per_member", 8)
        joints = {}
        tag = 0
        for level in range(stories + 1):
            for col in range(bays + 1):
                tag += 1; joints[level, col] = tag
                ops.node(tag, x[col] * 1000.0, y[level] * 1000.0)
        for col in range(bays + 1):
            ops.fix(joints[0, col], 1, 1, 1 if g["base_support"] == "fixed" else 0)
        physical, eid = [], 0
        def add_member(mid, kind, level, grid, start, end, section, transf, length):
            global tag, eid
            section = CONFIG.get("member_sections", {}).get(mid, section)
            ends = ([joints[level, grid], joints[level+1, grid]] if kind == "column"
                    else [joints[level, grid], joints[level, grid+1]])
            nlist = [ends[0]]
            for part in range(1, segments):
                t = part / segments; tag += 1
                nid = tag
                ops.node(nid, (start[0]+(end[0]-start[0])*t)*1000,
                         (start[1]+(end[1]-start[1])*t)*1000)
                nlist.append(nid)
            nlist.append(ends[1]); elements = []
            for ni, nj in zip(nlist, nlist[1:]):
                eid += 1
                ops.element("elasticBeamColumn", eid, ni, nj, section["A_mm2"],
                            mat["E_MPa"], section["Iz_mm4"], transf)
                elements.append(eid)
            physical.append({"member_id":mid,"member_type":kind,"section":section["name"],
                "steel":mat["name"],"span_m":length,"l0x_m":length,"l0y_m":length,
                "nodes":nlist,"elements":elements,"story":level if kind=="column" else level-1})
        for level in range(stories):
            for col in range(bays + 1):
                add_member("C-S%d-G%d"%(level+1,col+1),"column",level,col,
                    (x[col],y[level]),(x[col],y[level+1]),secs["column"],2,g["story_heights_m"][level])
        for level in range(1, stories + 1):
            for bay in range(bays):
                add_member("B-S%d-G%d"%(level,bay+1),"beam",level,bay,
                    (x[bay],y[level]),(x[bay+1],y[level]),secs["beam"],1,g["bay_widths_m"][bay])
        ops.timeSeries("Linear", 1); ops.pattern("Plain", 1, 1)
        for member in physical:
            if member["member_type"]=="beam":
                q=loads["q_by_story_kN_per_m"][member["story"]]
                for e in member["elements"]:
                    if q: ops.eleLoad("-ele",e,"-type","-beamUniform",-q,0.0)
        for story, force in enumerate(loads["lateral_by_story_kN"], start=1):
            if force:
                per_node = force / (bays + 1) if loads["lateral_is_story_total"] else force
                for col in range(bays + 1): ops.load(joints[story, col], per_node * 1000.0, 0.0, 0.0)
        ops.constraints("Transformation"); ops.numberer("RCM"); ops.system("BandGeneral")
        ops.test("NormDispIncr", 1.0e-8, 30); ops.algorithm("Newton")
        ops.integrator("LoadControl", 1.0); ops.analysis("Static")
        code = ops.analyze(1)
        if code: raise RuntimeError("OpenSees 静力分析未收敛，返回码 %s" % code)
        disp = max(abs(ops.nodeDisp(joints[stories, col], 1)) for col in range(bays+1))
        drift_ratios = []
        for story in range(1, stories+1):
            relative = max(abs(ops.nodeDisp(joints[story, col], 1) - ops.nodeDisp(joints[story-1, col], 1)) for col in range(bays+1))
            drift_ratios.append(relative / (g["story_heights_m"][story-1] * 1000.0))
        member_results=[]
        for m in physical:
            forces=[ops.eleResponse(e,"localForce") for e in m["elements"]]
            dof=2 if m["member_type"]=="beam" else 1
            d0=ops.nodeDisp(m["nodes"][0],dof); d1=ops.nodeDisp(m["nodes"][-1],dof)
            curve=[abs(ops.nodeDisp(n,dof)-(d0+(d1-d0)*i/(len(m["nodes"])-1))) for i,n in enumerate(m["nodes"])]
            member_results.append({k:v for k,v in m.items() if k not in ("nodes","elements","story")} | {
                "N_kn":max((abs(f[i]) for f in forces for i in (0,3)),default=0)/1000,
                "Mx_kNm":max((abs(f[i]) for f in forces for i in (2,5)),default=0)/1e6,
                "My_kNm":0,"V_kn":max((abs(f[i]) for f in forces for i in (1,4)),default=0)/1000,
                "deflection_mm":max(curve,default=0),"end_forces_local":[{"element_tag":e,"local_force":ops.eleResponse(e,"localForce")} for e in m["elements"]]})
        print(json.dumps({"status":"ok", "max_top_displacement_mm":disp,
            "max_story_drift_ratio":max(drift_ratios, default=0), "node_count":tag,
            "column_count":sum(m["member_type"]=="column" for m in physical),
            "beam_count":sum(m["member_type"]=="beam" for m in physical),
            "members":member_results,"material":mat,"units":"N, mm"}, ensure_ascii=False, indent=2))
        ops.wipe()
        ''')
    return template.replace("__CONFIG_JSON__", repr(encoded))


def _run_model(c):
    g, mat, loads, secs = c["geometry"], c["material"], c["loads"], c["sections"]
    bays, stories = g["bays"], g["stories"]
    # Subdivide each physical member so interior transverse displacements and
    # local force peaks are available to the checker (not just joint peaks).
    segments = int(c.get("mesh_segments_per_member", 8))
    x = [0.0]
    for width in g["bay_widths_m"]: x.append(x[-1] + width)
    y = [0.0]
    for height in g["story_heights_m"]: y.append(y[-1] + height)
    _ops("wipe")
    _ops("model", "basic", "-ndm", 2, "-ndf", 3)
    _ops("geomTransf", "Linear", 1)
    _ops("geomTransf", "Linear", 2)
    joints = {}
    tag = 0
    for level in range(stories + 1):
        for col in range(bays + 1):
            tag += 1
            joints[level, col] = tag
            _ops("node", tag, x[col] * 1000, y[level] * 1000)
    for col in range(bays + 1):
        _ops("fix", joints[0, col], 1, 1, 1 if g["base_support"] == "fixed" else 0)
    beam_members, column_members, eid = [], [], 0

    def add_member(member_id, member_type, start, end, section, transf, length_m, story, grid):
        nonlocal tag, eid
        section = c.get("member_sections", {}).get(member_id, section)
        x0, y0 = start
        x1, y1 = end
        member_nodes = [joints[story, grid] if member_type == "column" else joints[story, grid]]
        # End joint lookup is explicit because beam and column indexing differ.
        if member_type == "column":
            member_nodes = [joints[story, grid], joints[story + 1, grid]]
        else:
            member_nodes = [joints[story, grid], joints[story, grid + 1]]
        all_nodes = [member_nodes[0]]
        for part in range(1, segments):
            t = part / segments
            tag += 1
            nid = tag
            _ops("node", nid, (x0 + (x1 - x0) * t) * 1000, (y0 + (y1 - y0) * t) * 1000)
            all_nodes.append(nid)
        all_nodes.append(member_nodes[1])
        elements = []
        for left, right in zip(all_nodes, all_nodes[1:]):
            eid += 1
            _ops("element", "elasticBeamColumn", eid, left, right,
                 section["A_mm2"], mat["E_MPa"], section["Iz_mm4"], transf)
            elements.append(eid)
        record = {"member_id": member_id, "member_type": member_type,
                  "section": section["name"], "steel": mat["name"],
                  "span_m": length_m, "l0x_m": length_m, "l0y_m": length_m,
                  "node_i": f"N-L{story:02d}-G{grid + 1:02d}",
                  "node_j": f"N-L{story + 1:02d}-G{grid + 1:02d}" if member_type == "column" else f"N-L{story:02d}-G{grid + 2:02d}",
                  "node_tags": all_nodes, "element_tags": elements,
                  "grid": grid, "story": story + (1 if member_type == "column" else 0)}
        return record

    for level in range(stories):
        for col in range(bays + 1):
            column_members.append(add_member(f"C-S{level + 1}-G{col + 1}", "column",
                (x[col], y[level]), (x[col], y[level + 1]), secs["column"], 2,
                g["story_heights_m"][level], level, col))
    for level in range(1, stories + 1):
        for bay in range(bays):
            beam_members.append(add_member(f"B-S{level}-G{bay + 1}", "beam",
                (x[bay], y[level]), (x[bay + 1], y[level]), secs["beam"], 1,
                g["bay_widths_m"][bay], level, bay))
    _ops("timeSeries", "Linear", 1)
    _ops("pattern", "Plain", 1, 1)
    for member in beam_members:
        q = loads["q_by_story_kN_per_m"][member["story"] - 1]
        if q:
            for element in member["element_tags"]:
                _ops("eleLoad", "-ele", element, "-type", "-beamUniform", -q, 0.0)
    for story, force in enumerate(loads["lateral_by_story_kN"], start=1):
        if force:
            nodal = force / (bays + 1) if loads["lateral_is_story_total"] else force
            for col in range(bays + 1):
                _ops("load", joints[story, col], nodal * 1000, 0.0, 0.0)
    _ops("constraints", "Transformation")
    _ops("numberer", "RCM")
    _ops("system", "BandGeneral")
    _ops("test", "NormDispIncr", 1.0e-8, 30)
    _ops("algorithm", "Newton")
    _ops("integrator", "LoadControl", 1.0)
    _ops("analysis", "Static")
    if _ops("analyze", 1) != 0:
        raise RuntimeError("OpenSees 静力分析未收敛；请检查模型稳定性、支座约束和参数")
    _ops("reactions")
    top_disp = max(abs(_ops("nodeDisp", joints[stories, col], 1)) for col in range(bays + 1))
    drifts = []
    for story in range(1, stories + 1):
        story_disp = max(abs(_ops("nodeDisp", joints[story, col], 1) - _ops("nodeDisp", joints[story - 1, col], 1)) for col in range(bays + 1))
        drifts.append(story_disp / (g["story_heights_m"][story - 1] * 1000))
    def member_result(member):
        forces = [_ops("eleResponse", element, "localForce") for element in member["element_tags"]]
        first_force, last_force = forces[0], forces[-1]
        axial = max((abs(float(v[i])) for v in forces for i in (0, 3)), default=0.0) / 1000
        shear = max((abs(float(v[i])) for v in forces for i in (1, 4)), default=0.0) / 1000
        moment = max((abs(float(v[i])) for v in forces for i in (2, 5)), default=0.0) / 1e6
        is_beam = member["member_type"] == "beam"
        transverse_dof = 2 if is_beam else 1
        start_disp = float(_ops("nodeDisp", member["node_tags"][0], transverse_dof))
        end_disp = float(_ops("nodeDisp", member["node_tags"][-1], transverse_dof))
        deflections = []
        for idx, node in enumerate(member["node_tags"]):
            t = idx / (len(member["node_tags"]) - 1)
            actual = float(_ops("nodeDisp", node, transverse_dof))
            deflections.append(abs(actual - (start_disp + (end_disp - start_disp) * t)))
        length = member["span_m"]
        return {k: v for k, v in member.items() if k not in ("node_tags", "element_tags", "grid", "story")} | {
            "N_kn": axial, "Mx_kNm": moment, "My_kNm": 0.0, "V_kn": shear,
            "deflection_mm": max(deflections, default=0.0),
            "end_actions_local": {
                "Ni_kN": float(first_force[0]) / 1000.0, "Vi_kN": float(first_force[1]) / 1000.0,
                "Mi_kNm": float(first_force[2]) / 1.0e6, "Nj_kN": float(last_force[3]) / 1000.0,
                "Vj_kN": float(last_force[4]) / 1000.0, "Mj_kNm": float(last_force[5]) / 1.0e6,
            },
            "end_forces_local": [{"element_tag": int(e), "local_force": [float(x) for x in _ops("eleResponse", e, "localForce")]} for e in member["element_tags"]],
            "deflection_source": f"OpenSees 节点横向位移相对构件端点弦线的最大值（{segments} 段网格）",
            "axial_source": "各分段单元端部轴力绝对值包络（保守值）",
            "calculation_length_basis": "l0x/l0y 暂按构件几何长度取值；需工程师按框架侧移、支撑与节点约束复核"}
    member_results = [member_result(m) for m in column_members + beam_members]
    model_nodes = []
    supports = []
    support_reactions = []
    for (level, grid), node_tag in joints.items():
        node_id = f"N-L{level:02d}-G{grid + 1:02d}"
        model_nodes.append({"node_id": node_id, "x_m": x[grid], "y_m": y[level],
                            "ux_mm": float(_ops("nodeDisp", node_tag, 1)),
                            "uy_mm": float(_ops("nodeDisp", node_tag, 2)),
                            "rz_rad": float(_ops("nodeDisp", node_tag, 3))})
        if level == 0:
            fixed_rotation = g["base_support"] == "fixed"
            supports.append({"node_id": node_id, "ux": True, "uy": True, "rz": fixed_rotation})
            support_reactions.append({"node_id": node_id,
                                      "fx_kN": float(_ops("nodeReaction", node_tag, 1)) / 1000.0,
                                      "fy_kN": float(_ops("nodeReaction", node_tag, 2)) / 1000.0,
                                      "mz_kNm": float(_ops("nodeReaction", node_tag, 3)) / 1.0e6})
    axial = [m["N_kn"] for m in member_results if m["member_type"] == "column"]
    moments = [m["Mx_kNm"] for m in member_results if m["member_type"] == "beam"]
    return {"node_count": len(joints) + segments * (len(column_members) + len(beam_members) - 0) - len(column_members) - len(beam_members),
            "column_count": len(column_members), "beam_count": len(beam_members),
            "finite_element_count": sum(len(m["element_tags"]) for m in column_members + beam_members),
            "mesh_segments_per_member": segments,
            "max_column_axial_kN": max(axial, default=0), "max_beam_end_moment_kNm": max(moments, default=0),
            "max_top_displacement_mm": top_disp, "story_drift_ratios": drifts,
            "model_nodes": model_nodes, "supports": supports,
            "support_reactions": support_reactions,
            "max_drift_ratio": max(drifts, default=0), "members": member_results,
            "engineering_notice": "线弹性二维静力分析；轴力按端部绝对值包络保守传递，弯矩取平面内弯矩，My=0。计算长度暂按几何长度，位移限值需结合用途与适用规范复核。",
            "model": "2D elasticBeamColumn, linear static"}


@tool
def opensees_frame_verify(payload: str) -> str:
    """根据 JSON 参数建立/计算二维钢框架，并返回完整可独立运行的 OpenSeesPy 脚本。

    支持 geometry:{bays, bay_widths_m 或 bay_m, stories, story_heights_m 或 height_m,
    base_support}；material:{name/steel_grade,E_MPa,Fy_MPa}；sections:{beam:{A_mm2,Iz_mm4},
    column:{A_mm2,Iz_mm4}} 或 beam_section/column_section 名称；loads:{q_by_story_kN_per_m,
    lateral_by_story_kN}。数组长度分别等于层数。兼容旧字段 q_kNm、lateral_kn、E_mpa、beam_A/I、column_A/I。
    lateral_by_story_kN 表示每层总水平力；旧 lateral_kn 表示每个楼层节点施加的力。
    返回 JSON 包含分析结果、归一化参数、可运行 Python 脚本源码。钢材 Fy 不代表塑性分析。
    """
    try:
        config = _normalize(payload)
        with _OPENSEES_LOCK:
            try:
                result = _run_model(config)
            finally:
                try:
                    _ops("wipe")
                except Exception:
                    pass
        return json.dumps({"ok": True, "parameters": config, "results": result,
                           "model_script": _make_script(config),
                           "notice": "线弹性二维分析结果不等同于 GB 50017 构件验算或完整抗震设计；Fy 仅记录，不进入本模型计算。"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
