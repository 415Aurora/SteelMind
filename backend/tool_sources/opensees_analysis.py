"""参数化三维钢框架 OpenSeesPy 建模、静力分析及脚本生成工具。

单位：输入 m/kN，模型内部 mm/N；E、G 为 MPa，截面特性为 mm 系。
使用弹性空间梁柱单元；Fy 仅作材料元数据，不进行塑性或规范设计验算。
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
    h, b, tw, tf = (float(sec[key]) for key in ("h", "b", "tw", "t1"))
    Iz = float(sec["Ix"])
    Iy = float(sec["Iy"])
    # Saint-Venant torsional constant approximation for a thin-walled H section.
    J = (2 * b * tf ** 3 + max(h - 2 * tf, 0) * tw ** 3) / 3
    if not all(math.isfinite(value) and value > 0 for value in (A, Iz, Iy, J)):
        raise ValueError(f"{role}截面 A、Iy、Iz 和 J 必须为有限正数")
    return {"name": sec["name"], "designation": sec["designation"],
            "A_mm2": A, "Iz_mm4": Iz, "Iy_mm4": Iy, "J_mm4": J,
            "h_mm": h, "b_mm": b, "tw_mm": tw, "tf_mm": tf,
            "catalog_standard": sec["catalog_standard"], "catalog_id": sec["catalog_id"]}


def _normalize(raw):
    d = json.loads(raw) if isinstance(raw, str) else dict(raw)
    geometry = d.get("geometry") or d
    material = d.get("material") or d.get("materials") or {}
    loads = d.get("loads") or d
    bays_x = int(geometry.get("bays_x", geometry.get("bays", 1)))
    bays_z = int(geometry.get("bays_z", 1))
    stories = int(geometry.get("stories", 1))
    if not 1 <= bays_x <= 30 or not 1 <= bays_z <= 30 or not 1 <= stories <= 30:
        raise ValueError("X/Z 向跨数和层数必须在 1 到 30 之间")
    spans_x = _positive_list(geometry.get("bay_widths_x_m") or geometry.get("bay_widths_m") or geometry.get("bay_m"),
                             bays_x, "bay_widths_x_m", 6)
    spans_z = _positive_list(geometry.get("bay_widths_z_m") or geometry.get("bay_depth_m"),
                             bays_z, "bay_widths_z_m", 6)
    physical_count = stories * ((bays_x + 1) * (bays_z + 1) + bays_x * (bays_z + 1) + bays_z * (bays_x + 1))
    if (bays_x + 1) * (bays_z + 1) * (stories + 1) > 5000 or physical_count > 2500:
        raise ValueError("三维模型规模超限：节点不得超过 5000，实体构件不得超过 2500")
    height_input = geometry.get("story_heights_m") or None
    if height_input is None and geometry.get("height_m") is not None:
        # Legacy height_m represented total building/eave height.
        height_input = float(geometry["height_m"]) / stories
    heights = _positive_list(height_input, stories, "story_heights_m", 3)
    support = geometry.get("base_support", d.get("base_support", "fixed"))
    if support not in ("fixed", "pinned"):
        raise ValueError("base_support 仅支持 fixed 或 pinned")
    E = float(material.get("E_MPa", material.get("E_mpa", d.get("E_mpa", 206000))))
    nu = float(material.get("poisson_ratio", material.get("nu", 0.3)))
    G = float(material.get("G_MPa", E / (2 * (1 + nu))))
    fy = material.get("Fy_MPa", material.get("fy_mpa"))
    fy = float(fy) if fy is not None else None
    if (not math.isfinite(E) or E <= 0 or not math.isfinite(G) or G <= 0 or not 0 < nu < 0.5
            or (fy is not None and (not math.isfinite(fy) or fy <= 0))):
        raise ValueError("材料 E 与可选 Fy 必须为有限正数，泊松比须在 0 到 0.5 之间")
    q_raw = loads.get("q_by_story_kN_per_m", loads.get("q_kNm", loads.get("q_kN_per_m", loads.get("dead", 0))))
    q = _nonnegative_list(q_raw, stories, "q_by_story_kN_per_m")
    qz = _nonnegative_list(loads.get("q_z_by_story_kN_per_m", loads.get("q_by_story_z_kN_per_m", 0)),
                           stories, "q_z_by_story_kN_per_m")
    lateral_x_raw = loads.get("lateral_x_by_story_kN", loads.get("lateral_by_story_kN", loads.get("lateral_kn", 0)))
    lateral_z_raw = loads.get("lateral_z_by_story_kN", 0)
    lateral_x = _signed_list(lateral_x_raw, stories, "lateral_x_by_story_kN")
    lateral_z = _signed_list(lateral_z_raw, stories, "lateral_z_by_story_kN")
    lateral_x_is_total = "lateral_x_by_story_kN" in loads or "lateral_by_story_kN" in loads
    lateral_z_is_total = "lateral_z_by_story_kN" in loads
    beam = _resolve_section({**d, **(d.get("sections") or {})}, "beam")
    col = _resolve_section({**d, **(d.get("sections") or {})}, "column")
    member_sections = {}
    for member_id, value in (d.get("member_sections") or {}).items():
        mid = str(member_id).strip()
        role = "column" if mid.startswith("C-") else "beam" if mid.startswith(("B-", "BX-", "BZ-")) else None
        if not mid or role is None:
            raise ValueError(f"逐构件截面编号 {member_id!r} 无效；编号需以 C-、B-、BX- 或 BZ- 开头")
        section_input = value if isinstance(value, dict) else {"name": str(value)}
        member_sections[mid] = _resolve_section({f"{role}_section": section_input.get("name") or section_input.get("section"),
                                                  f"{role}_properties": section_input}, role)
    mesh_segments = int(d.get("mesh_segments_per_member", 8))
    if not 2 <= mesh_segments <= 32:
        raise ValueError("mesh_segments_per_member 必须在 2 到 32 之间")
    if physical_count * mesh_segments > 30000:
        raise ValueError("细分后单元数超过 30000；请减少跨数、层数或 mesh_segments_per_member")
    return {
        "geometry": {"bays": bays_x, "bays_x": bays_x, "bays_z": bays_z,
                     "stories": stories, "bay_widths_m": spans_x,
                     "bay_widths_x_m": spans_x, "bay_widths_z_m": spans_z,
                     "story_heights_m": heights, "base_support": support},
        "material": {"name": material.get("name", material.get("steel_grade", "未指定")),
                     "E_MPa": E, "G_MPa": G, "poisson_ratio": nu, "Fy_MPa": fy},
        "loads": {"q_by_story_kN_per_m": q, "q_z_by_story_kN_per_m": qz,
                  "lateral_x_by_story_kN": lateral_x, "lateral_z_by_story_kN": lateral_z,
                  "lateral_x_is_story_total": lateral_x_is_total,
                  "lateral_z_is_story_total": lateral_z_is_total},
        "sections": {"beam": beam, "column": col},
        "member_sections": member_sections,
        "mesh_segments_per_member": mesh_segments,
        "expected": d.get("expected") or {},
    }


def _make_script(config):
    encoded = json.dumps(config, ensure_ascii=False)
    template = textwrap.dedent('''\
        """Standalone generated 3D elastic steel-frame analysis (m/kN input, mm/N model).
        Section torsional J uses a thin-wall H-section approximation; Fy is metadata only.
        Install openseespy with: python -m pip install openseespy
        """
        import json
        import openseespy.opensees as ops
        C = json.loads(__CONFIG_JSON__)
        g, mat, load, sec = C["geometry"], C["material"], C["loads"], C["sections"]
        nx, nz, ns = g["bays_x"], g["bays_z"], g["stories"]
        coord = lambda vals: [0.0] + list(__import__("itertools").accumulate(vals))
        xs, ys, zs = coord(g["bay_widths_x_m"]), coord(g["story_heights_m"]), coord(g["bay_widths_z_m"])
        ops.wipe(); ops.model("basic", "-ndm", 3, "-ndf", 6)
        ops.geomTransf("Linear", 1, 0, 0, 1); ops.geomTransf("Linear", 2, 1, 0, 0); ops.geomTransf("Linear", 3, 1, 0, 0)
        nodes, xyz, tag = {}, {}, 0
        for j in range(ns+1):
            for k in range(nz+1):
                for i in range(nx+1):
                    tag += 1; nodes[j,i,k] = tag; xyz[tag] = (xs[i],ys[j],zs[k])
                    ops.node(tag,xs[i]*1000,ys[j]*1000,zs[k]*1000)
        for k in range(nz+1):
            for i in range(nx+1):
                ops.fix(nodes[0,i,k],1,1,1,1,1,1) if g["base_support"]=="fixed" else ops.fix(nodes[0,i,k],1,1,1,0,0,0)
        members=[]; eid=0
        def add(mid,kind,story,i,k,ni,nj,base,transf,length,local_y_sign):
            global eid
            s=C.get("member_sections",{}).get(mid,base)
            for a,b in ((ni,nj),):
                eid+=1; ops.element("elasticBeamColumn",eid,a,b,s["A_mm2"],mat["E_MPa"],mat["G_MPa"],s["J_mm4"],s["Iy_mm4"],s["Iz_mm4"],transf)
            members.append({"id":mid,"kind":kind,"story":story,"i":i,"k":k,"ni":ni,"nj":nj,"eid":eid,"section":s,"length":length,"sign":local_y_sign})
        for j in range(ns):
            for k in range(nz+1):
                for i in range(nx+1): add("C-S%d-X%d-Z%d"%(j+1,i+1,k+1),"column",j+1,i,k,nodes[j,i,k],nodes[j+1,i,k],sec["column"],3,g["story_heights_m"][j],1)
        for j in range(1,ns+1):
            for k in range(nz+1):
                for i in range(nx): add("BX-S%d-Z%d-G%d"%(j,k+1,i+1),"beam_x",j,i,k,nodes[j,i,k],nodes[j,i+1,k],sec["beam"],1,g["bay_widths_x_m"][i],1)
            for i in range(nx+1):
                for k in range(nz): add("BZ-S%d-X%d-G%d"%(j,i+1,k+1),"beam_z",j,i,k,nodes[j,i,k],nodes[j,i,k+1],sec["beam"],2,g["bay_widths_z_m"][k],-1)
        ops.timeSeries("Linear",1); ops.pattern("Plain",1,1)
        for m in members:
            if m["kind"] in ("beam_x","beam_z"):
                q=load["q_by_story_kN_per_m"][m["story"]-1] if m["kind"]=="beam_x" else load["q_z_by_story_kN_per_m"][m["story"]-1]
                if q: ops.eleLoad("-ele",m["eid"],"-type","-beamUniform",(-q if m["sign"]>0 else q),0,0)
        for j in range(1,ns+1):
            floor=[nodes[j,i,k] for k in range(nz+1) for i in range(nx+1)]
            fx=load["lateral_x_by_story_kN"][j-1]/len(floor) if load["lateral_x_is_story_total"] else load["lateral_x_by_story_kN"][j-1]
            fz=load["lateral_z_by_story_kN"][j-1]/len(floor) if load["lateral_z_is_story_total"] else load["lateral_z_by_story_kN"][j-1]
            for n in floor: ops.load(n,fx*1000,0,fz*1000,0,0,0)
        ops.constraints("Transformation"); ops.numberer("RCM"); ops.system("BandGeneral")
        ops.test("NormDispIncr",1e-8,40); ops.algorithm("Newton"); ops.integrator("LoadControl",1); ops.analysis("Static")
        code=ops.analyze(1)
        if code: raise RuntimeError("3D OpenSees static analysis failed: %s"%code)
        results=[]
        for m in members:
            f=[float(v) for v in ops.eleResponse(m["eid"],"localForce")]
            results.append({"member_id":m["id"],"member_type":"column" if m["kind"]=="column" else "beam","section":m["section"]["name"],
                "N_kn":max(abs(f[0]),abs(f[6]))/1000,"Vy_kn":max(abs(f[1]),abs(f[7]))/1000,"Vz_kn":max(abs(f[2]),abs(f[8]))/1000,
                "Mx_kNm":max(abs(f[5]),abs(f[11]))/1e6,"My_kNm":max(abs(f[4]),abs(f[10]))/1e6,"T_kNm":max(abs(f[3]),abs(f[9]))/1e6,
                "local_force":f,"node_i":m["ni"],"node_j":m["nj"]})
        print(json.dumps({"model":"3D elasticBeamColumn","members":results,"joint_count":len(nodes),"element_count":len(members),"units":"kN,m,MPa"},ensure_ascii=False,indent=2))
        ops.wipe()
        ''')
    return template.replace("__CONFIG_JSON__", repr(encoded))


def _run_model(c):
    g, mat, loads, secs = c["geometry"], c["material"], c["loads"], c["sections"]
    nx, nz, stories = g["bays_x"], g["bays_z"], g["stories"]
    segments = int(c.get("mesh_segments_per_member", 8))
    def cumulative(values):
        result = [0.0]
        for value in values: result.append(result[-1] + value)
        return result
    xs, ys, zs = cumulative(g["bay_widths_x_m"]), cumulative(g["story_heights_m"]), cumulative(g["bay_widths_z_m"])
    _ops("wipe")
    _ops("model", "basic", "-ndm", 3, "-ndf", 6)
    _ops("geomTransf", "Linear", 1, 0.0, 0.0, 1.0)  # X beams: local y is global +Y
    _ops("geomTransf", "Linear", 2, 1.0, 0.0, 0.0)  # Z beams: local y is global -Y
    _ops("geomTransf", "Linear", 3, 1.0, 0.0, 0.0)  # Columns: strong axis along global X
    joints, tag, eid = {}, 0, 0
    node_xyz, node_names = {}, {}
    for level in range(stories + 1):
        for iz in range(nz + 1):
            for ix in range(nx + 1):
                tag += 1
                joints[level, ix, iz] = tag
                node_id = f"N-L{level:02d}-X{ix + 1:02d}-Z{iz + 1:02d}"
                node_names[tag] = node_id
                node_xyz[tag] = (xs[ix], ys[level], zs[iz])
                _ops("node", tag, xs[ix] * 1000.0, ys[level] * 1000.0, zs[iz] * 1000.0)
    for iz in range(nz + 1):
        for ix in range(nx + 1):
            flags = (1, 1, 1, 1, 1, 1) if g["base_support"] == "fixed" else (1, 1, 1, 0, 0, 0)
            _ops("fix", joints[0, ix, iz], *flags)
    physical = []
    def add_member(member_id, member_type, story, ix, iz, ni, nj, section, transf, length_m, local_y_global_sign):
        nonlocal tag, eid
        section = c.get("member_sections", {}).get(member_id, section)
        p0, p1 = node_xyz[ni], node_xyz[nj]
        chain = [ni]
        for part in range(1, segments):
            ratio = part / segments
            tag += 1
            node = tag
            xyz = tuple(p0[axis] + (p1[axis] - p0[axis]) * ratio for axis in range(3))
            node_xyz[node] = xyz
            _ops("node", node, *(value * 1000.0 for value in xyz))
            chain.append(node)
        chain.append(nj)
        element_tags = []
        for left, right in zip(chain, chain[1:]):
            eid += 1
            _ops("element", "elasticBeamColumn", eid, left, right, section["A_mm2"], mat["E_MPa"],
                 mat["G_MPa"], section["J_mm4"], section["Iy_mm4"], section["Iz_mm4"], transf)
            element_tags.append(eid)
        physical.append({"member_id": member_id, "member_type": member_type,
            "member_axis": "Y" if member_type == "column" else "X" if member_type == "beam_x" else "Z",
            "section": section["name"], "steel": mat["name"], "span_m": length_m,
            "l0x_m": length_m, "l0y_m": length_m,
            "node_i": node_names[ni], "node_j": node_names[nj], "node_tags": chain,
            "element_tags": element_tags, "story": story, "grid_x": ix, "grid_z": iz,
            "local_y_global_sign": local_y_global_sign})
    for level in range(stories):
        for iz in range(nz + 1):
            for ix in range(nx + 1):
                member_id = f"C-S{level + 1}-X{ix + 1}-Z{iz + 1}"
                add_member(member_id, "column", level + 1, ix, iz,
                    joints[level, ix, iz], joints[level + 1, ix, iz], secs["column"], 3,
                    g["story_heights_m"][level], 1.0)
    for floor in range(1, stories + 1):
        for iz in range(nz + 1):
            for ix in range(nx):
                member_id = f"BX-S{floor}-Z{iz + 1}-G{ix + 1}"
                add_member(member_id, "beam_x", floor, ix, iz,
                    joints[floor, ix, iz], joints[floor, ix + 1, iz], secs["beam"], 1,
                    g["bay_widths_x_m"][ix], 1.0)
        for ix in range(nx + 1):
            for iz in range(nz):
                member_id = f"BZ-S{floor}-X{ix + 1}-G{iz + 1}"
                add_member(member_id, "beam_z", floor, ix, iz,
                    joints[floor, ix, iz], joints[floor, ix, iz + 1], secs["beam"], 2,
                    g["bay_widths_z_m"][iz], -1.0)
    _ops("timeSeries", "Linear", 1)
    _ops("pattern", "Plain", 1, 1)
    for member in physical:
        if member["member_type"] not in ("beam_x", "beam_z"):
            continue
        story_index = member["story"] - 1
        q = loads["q_by_story_kN_per_m"][story_index] if member["member_type"] == "beam_x" else loads["q_z_by_story_kN_per_m"][story_index]
        wy = -q if member["local_y_global_sign"] > 0 else q
        if q:
            for element in member["element_tags"]:
                _ops("eleLoad", "-ele", element, "-type", "-beamUniform", wy, 0.0, 0.0)
    for level in range(1, stories + 1):
        lateral_x = loads["lateral_x_by_story_kN"][level - 1]
        lateral_z = loads["lateral_z_by_story_kN"][level - 1]
        floor_nodes = [joints[level, ix, iz] for iz in range(nz + 1) for ix in range(nx + 1)]
        fx = lateral_x / len(floor_nodes) if loads["lateral_x_is_story_total"] else lateral_x
        fz = lateral_z / len(floor_nodes) if loads["lateral_z_is_story_total"] else lateral_z
        for node in floor_nodes:
            if fx or fz:
                _ops("load", node, fx * 1000.0, 0.0, fz * 1000.0, 0.0, 0.0, 0.0)
    _ops("constraints", "Transformation")
    _ops("numberer", "RCM")
    _ops("system", "BandGeneral")
    _ops("test", "NormDispIncr", 1.0e-8, 40)
    _ops("algorithm", "Newton")
    _ops("integrator", "LoadControl", 1.0)
    _ops("analysis", "Static")
    if _ops("analyze", 1) != 0:
        raise RuntimeError("3D OpenSees 静力分析未收敛；请检查框架稳定性、柱脚约束和参数")
    _ops("reactions")
    def displacement(node):
        return tuple(float(_ops("nodeDisp", node, dof)) for dof in (1, 2, 3))
    drifts_x, drifts_z = [], []
    for level in range(1, stories + 1):
        drift_x = max(abs(displacement(joints[level, ix, iz])[0] - displacement(joints[level - 1, ix, iz])[0])
                      for iz in range(nz + 1) for ix in range(nx + 1))
        drift_z = max(abs(displacement(joints[level, ix, iz])[2] - displacement(joints[level - 1, ix, iz])[2])
                      for iz in range(nz + 1) for ix in range(nx + 1))
        drifts_x.append(drift_x / (g["story_heights_m"][level - 1] * 1000.0))
        drifts_z.append(drift_z / (g["story_heights_m"][level - 1] * 1000.0))
    member_results = []
    for member in physical:
        forces = [[float(value) for value in _ops("eleResponse", element, "localForce")]
                  for element in member["element_tags"]]
        if any(len(force) < 12 for force in forces):
            raise RuntimeError("三维梁柱单元未返回预期的 12 分量 localForce")
        max_force = lambda indexes: max((abs(force[index]) for force in forces for index in indexes), default=0.0)
        d0, d1 = displacement(member["node_tags"][0]), displacement(member["node_tags"][-1])
        p0, p1 = node_xyz[member["node_tags"][0]], node_xyz[member["node_tags"][-1]]
        length = math.sqrt(sum((p1[i] - p0[i]) ** 2 for i in range(3)))
        axis = tuple((p1[i] - p0[i]) / length for i in range(3))
        deflections = []
        for index, node in enumerate(member["node_tags"]):
            ratio = index / (len(member["node_tags"]) - 1)
            current = displacement(node)
            offset = tuple(current[i] - (d0[i] + (d1[i] - d0[i]) * ratio) for i in range(3))
            axial = sum(offset[i] * axis[i] for i in range(3))
            # nodeDisp and offset already use the N-mm model units.
            transverse = tuple(offset[i] - axial * axis[i] for i in range(3))
            deflections.append(math.sqrt(sum(value ** 2 for value in transverse)))
        fi, fj = forces[0], forces[-1]
        item = {key: value for key, value in member.items()
                if key not in ("node_tags", "element_tags", "local_y_global_sign")}
        item.update({"member_type": "column" if member["member_type"] == "column" else "beam",
            "N_kn": max_force((0, 6)) / 1000.0,
            "Vy_kn": max_force((1, 7)) / 1000.0, "Vz_kn": max_force((2, 8)) / 1000.0,
            "V_kn": max(max_force((1, 7)), max_force((2, 8))) / 1000.0,
            "T_kNm": max_force((3, 9)) / 1.0e6,
            "Mx_kNm": max_force((5, 11)) / 1.0e6, "My_kNm": max_force((4, 10)) / 1.0e6,
            "deflection_mm": max(deflections, default=0.0),
            "deflection_x_mm": max((abs(float(_ops("nodeDisp", node, 1))) for node in member["node_tags"]), default=0.0),
            "deflection_y_mm": max((abs(float(_ops("nodeDisp", node, 2))) for node in member["node_tags"]), default=0.0),
            "deflection_z_mm": max((abs(float(_ops("nodeDisp", node, 3))) for node in member["node_tags"]), default=0.0),
            "end_actions_local": {"Ni_kN": fi[0]/1000.0, "Vyi_kN": fi[1]/1000.0, "Vzi_kN": fi[2]/1000.0, "Ti_kNm": fi[3]/1.0e6, "Myi_kNm": fi[4]/1.0e6, "Mzi_kNm": fi[5]/1.0e6,
                "Nj_kN": fj[6]/1000.0, "Vyj_kN": fj[7]/1000.0, "Vzj_kN": fj[8]/1000.0, "Tj_kNm": fj[9]/1.0e6, "Myj_kNm": fj[10]/1.0e6, "Mzj_kNm": fj[11]/1.0e6},
            "end_forces_local": [{"element_tag": element, "local_force": force} for element, force in zip(member["element_tags"], forces)],
            "deflection_source": "构件分段节点三维横向位移相对端点弦线的最大合位移",
            "calculation_length_basis": "l0x/l0y 暂按构件几何长度；须按侧移、支撑与节点约束复核"})
        member_results.append(item)
    model_nodes, supports, support_reactions = [], [], []
    for (level, ix, iz), node in joints.items():
        ux, uy, uz = displacement(node)
        node_id = f"N-L{level:02d}-X{ix + 1:02d}-Z{iz + 1:02d}"
        model_nodes.append({"node_id": node_id, "x_m": xs[ix], "y_m": ys[level], "z_m": zs[iz],
            "ux_mm": ux, "uy_mm": uy, "uz_mm": uz,
            "rx_rad": float(_ops("nodeDisp", node, 4)), "ry_rad": float(_ops("nodeDisp", node, 5)), "rz_rad": float(_ops("nodeDisp", node, 6))})
        if level == 0:
            fixed = g["base_support"] == "fixed"
            supports.append({"node_id": node_id, "ux": True, "uy": True, "uz": True, "rx": fixed, "ry": fixed, "rz": fixed})
            support_reactions.append({"node_id": node_id, "fx_kN": float(_ops("nodeReaction", node, 1))/1000.0,
                "fy_kN": float(_ops("nodeReaction", node, 2))/1000.0, "fz_kN": float(_ops("nodeReaction", node, 3))/1000.0,
                "mx_kNm": float(_ops("nodeReaction", node, 4))/1.0e6, "my_kNm": float(_ops("nodeReaction", node, 5))/1.0e6,
                "mz_kNm": float(_ops("nodeReaction", node, 6))/1.0e6})
    top = [displacement(joints[stories, ix, iz]) for iz in range(nz + 1) for ix in range(nx + 1)]
    max_dx, max_dz = max((abs(value[0]) for value in top), default=0.0), max((abs(value[2]) for value in top), default=0.0)
    return {"node_count": len(model_nodes) + sum(len(item["element_tags"]) - 1 for item in physical),
        "joint_count": len(model_nodes), "column_count": sum(item["member_type"] == "column" for item in physical),
        "beam_x_count": sum(item["member_type"] == "beam_x" for item in physical),
        "beam_z_count": sum(item["member_type"] == "beam_z" for item in physical),
        "beam_count": sum(item["member_type"] in ("beam_x", "beam_z") for item in physical),
        "finite_element_count": sum(len(item["element_tags"]) for item in physical),
        "mesh_segments_per_member": segments,
        "max_column_axial_kN": max((item["N_kn"] for item in member_results if item["member_type"] == "column"), default=0.0),
        "max_beam_moment_kNm": max((item["Mx_kNm"] for item in member_results if item["member_type"] == "beam"), default=0.0),
        "max_top_displacement_x_mm": max_dx, "max_top_displacement_z_mm": max_dz,
        "max_top_displacement_mm": max((math.sqrt(value[0]**2 + value[2]**2) for value in top), default=0.0),
        "story_drift_ratios_x": drifts_x, "story_drift_ratios_z": drifts_z,
        "story_drift_ratios": [max(x, z) for x, z in zip(drifts_x, drifts_z)],
        "max_drift_ratio_x": max(drifts_x, default=0.0), "max_drift_ratio_z": max(drifts_z, default=0.0),
        "max_drift_ratio": max(drifts_x + drifts_z, default=0.0),
        "model_nodes": model_nodes, "supports": supports, "support_reactions": support_reactions,
        "members": member_results,
        "engineering_notice": "三维线弹性单静力工况；截面主轴按局部坐标约定，H截面 J 为薄壁近似。轴力和内力按分段端部包络，计算长度暂按几何长度，需工程师复核。",
        "model": "3D elasticBeamColumn, linear static"}
@tool
def opensees_frame_verify(payload: str) -> str:
    """根据 JSON 参数建立/计算 X-Z 双向三维钢框架，并返回可独立运行的 OpenSeesPy 脚本。

    geometry 支持 bays_x/bays_z、bay_widths_x_m/bay_widths_z_m、stories、story_heights_m、base_support；
    兼容旧 bays/bay_widths_m/bay_m 字段（作为 X 向输入，Z 向默认一跨）。loads 支持两向逐层线荷载
    q_by_story_kN_per_m/q_z_by_story_kN_per_m 和层总水平力 lateral_x_by_story_kN/lateral_z_by_story_kN；
    旧 lateral_by_story_kN 解释为 X 向层总力，lateral_kn 仍为逐节点力。输出每根杆件的 N、双向剪力、
    双向弯矩、扭矩、三维挠度、分段端部力及节点反力。Fy 不进入线弹性分析。
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
                           "notice": "三维线弹性静力结果不等同于 GB 50017 完整构件验算或抗震设计；H截面J为薄壁近似，计算长度与边界条件仍须工程师核验；Fy 仅记录，不进入本模型计算。"}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
