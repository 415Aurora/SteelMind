"""Adapter from the converged SteelMind frame workflow to the drawing bundle exporter."""
from __future__ import annotations

import json
import math
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain.tools import tool


BACKEND_ROOT = Path(__file__).resolve().parents[1]
EXPORT_PACKAGE_ROOT = BACKEND_ROOT / "engineering_export" / "src"
if str(EXPORT_PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(EXPORT_PACKAGE_ROOT))

from steelmind_export import generate_package, validate_bundle  # noqa: E402
from steelmind_export.results import GenerationOptions  # noqa: E402


CHECK_SOURCE = "SteelMind backend/tool_sources/structural_calc.py::check_steel_member"
ANALYSIS_SOURCE = "SteelMind backend/tool_sources/opensees_analysis.py::opensees_frame_verify"


def _finite(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 缺失或不是数值") from exc
    if not math.isfinite(number):
        raise ValueError(f"{label} 必须是有限数值")
    return number


def build_drawing_bundle(report: dict[str, Any]) -> dict[str, Any]:
    """Build the export tool's strict DesignBundle using only workflow outputs."""
    if report.get("status") != "converged" or report.get("converged") is not True:
        raise ValueError("仅可从工作流2已收敛的最终分析报告准备图纸数据")
    member_checks = report.get("member_checks") or []
    if not member_checks or any(item.get("passed") is not True for item in member_checks):
        raise ValueError("最终逐构件验算记录为空或存在未通过构件")

    analysis = report.get("analysis") or {}
    parameters = analysis.get("parameters") or {}
    result = analysis.get("results") or {}
    geometry = parameters.get("geometry") or {}
    material = parameters.get("material") or {}
    loads = parameters.get("loads") or {}
    raw_members = result.get("members") or []
    nodes = result.get("model_nodes") or []
    supports = result.get("supports") or []
    reactions = result.get("support_reactions") or []
    if int(geometry.get("bays_z", 0) or 0) > 0 or any(abs(float(node.get("z_m", 0) or 0)) > 1e-9 for node in nodes):
        raise ValueError("当前 DesignBundle/DXF 导出器仍只支持二维框架坐标；三维分析结果已保留，但不会压扁成二维图纸。")
    if not nodes or not raw_members or not supports:
        raise ValueError("OpenSees 报告缺少节点位移、实体杆件或支座信息；请用新版分析工具重新运行工作流2")
    if len(raw_members) != len(member_checks):
        raise ValueError("OpenSees 实体杆件数与最终验算记录数不一致")

    from steelmind_structural_calc import MATERIALS, _get_section

    steel_name = str(material.get("name") or (report.get("request", {}).get("material") or {}).get("steel_grade") or "").strip()
    material_data = (report.get("request", {}).get("material") or {})
    if not steel_name:
        raise ValueError("最终模型缺少钢材牌号")
    if steel_name not in MATERIALS and material_data.get("Fy_MPa") in (None, ""):
        raise ValueError(f"钢材 {steel_name} 不在本系统材料表中，且未提供 Fy_MPa；不能生成有依据的截面数据")
    fy = _finite(material_data.get("Fy_MPa", MATERIALS.get(steel_name, (None,))[0]), "材料 Fy_MPa")
    elastic_modulus = _finite(material.get("E_MPa", material_data.get("E_MPa", 206000)), "材料 E_MPa")
    material_id = "MAT_" + re.sub(r"[^A-Za-z0-9_-]+", "_", steel_name).strip("_")

    member_ids = {str(member.get("member_id")) for member in raw_members}
    check_by_member = {str(item.get("member_id")): item for item in member_checks}
    if member_ids != set(check_by_member):
        raise ValueError("OpenSees 杆件编号与最终验算报告中的杆件编号不一致")

    section_ids: dict[str, str] = {}
    section_records: dict[str, dict[str, Any]] = {}
    model_members = []
    node_lookup = {str(node.get("node_id")): node for node in nodes}
    for index, member in enumerate(raw_members):
        member_id = str(member.get("member_id") or "").strip()
        section_name = str(member.get("section") or "").strip()
        props = _get_section(section_name)
        if not member_id or not section_name or props is None:
            raise ValueError(f"构件 {member_id or index} 的截面 {section_name!r} 缺少可追溯的 H/I 几何；当前导出器不猜测自定义截面尺寸")
        section_name = props["name"]
        section_id = section_ids.setdefault(section_name, "SEC_" + re.sub(r"[^A-Za-z0-9_-]+", "_", section_name).strip("_"))
        if section_name not in section_records:
            h, b, tw, tf = (_finite(props[key], f"{section_name}.{key}") for key in ("h", "b", "tw", "t1"))
            area = _finite(props["A"], f"{section_name}.A")
            ix, iy = _finite(props["Ix"], f"{section_name}.Ix"), _finite(props["Iy"], f"{section_name}.Iy")
            section_records[section_name] = {
                "id": section_id, "name": section_name, "shape": "I" if section_name.upper().startswith("I") else "H",
                "h_mm": h, "b_mm": b, "tw_mm": tw, "tf_mm": tf, "A_mm2": area,
                "Ix_mm4": ix, "Iy_mm4": iy, "Wx_mm3": _finite(props["Wx"], f"{section_name}.Wx"),
                "Wy_mm3": _finite(props["Wy"], f"{section_name}.Wy"), "property_basis": "catalog",
                "source": f"{props['catalog_standard']} {props['catalog_table']}；截面特性采用表列值，r={props['root_radius_mm']} mm。",
            }
        node_i, node_j = str(member.get("node_i") or ""), str(member.get("node_j") or "")
        if node_i not in node_lookup or node_j not in node_lookup:
            raise ValueError(f"构件 {member_id} 的节点引用无效")
        model_members.append({
            "id": member_id, "node_i": node_i, "node_j": node_j, "section_id": section_id,
            "material_id": material_id, "kind": "column" if member.get("member_type") == "column" else "beam",
            "release_i": False, "release_j": False,
        })

    model_nodes = [{"id": str(node["node_id"]), "x_m": _finite(node["x_m"], "节点x坐标"),
                    "y_m": _finite(node["y_m"], "节点y坐标")} for node in nodes]
    model_supports = [{"node_id": str(item["node_id"]), "ux": bool(item["ux"]),
                       "uy": bool(item["uy"]), "rz": bool(item["rz"])} for item in supports]
    combination_id = "MODEL_ANALYSIS"
    case_id = "MODEL_LOAD"
    span_list = geometry.get("bay_widths_m") or []
    story_heights = geometry.get("story_heights_m") or []
    case_loads = []
    for member in raw_members:
        if member.get("member_type") != "beam":
            continue
        story = int(member.get("story", 0))
        q = _finite((loads.get("q_by_story_kN_per_m") or [])[story - 1], f"第{story}层线荷载")
        if q:
            case_loads.append({"kind": "uniform_member", "target_id": str(member["member_id"]), "qx_kN_m": 0.0, "qy_kN_m": -q})
    bays, stories = int(geometry.get("bays", 0)), int(geometry.get("stories", 0))
    lateral = loads.get("lateral_by_story_kN") or []
    for level, total_force in enumerate(lateral, start=1):
        force = _finite(total_force, f"第{level}层水平荷载")
        per_node = force / (bays + 1) if loads.get("lateral_is_story_total") else force
        for grid in range(bays + 1):
            node_id = f"N-L{level:02d}-G{grid + 1:02d}"
            if node_id not in node_lookup:
                raise ValueError(f"水平荷载目标节点 {node_id} 缺失")
            if per_node:
                case_loads.append({"kind": "nodal", "target_id": node_id, "fx_kN": per_node, "fy_kN": 0.0, "mz_kNm": 0.0})

    checks = []
    traces = []
    for member_index, member in enumerate(raw_members):
        member_id = str(member["member_id"])
        result_item = check_by_member[member_id]
        components = result_item.get("utilization_components") or {}
        if not components:
            raise ValueError(f"构件 {member_id} 未返回逐项数值利用率")
        detail_lines = [str(row.get("text", "")) for row in (result_item.get("checks") or [])]
        detail_text = "\n".join(line for line in detail_lines if line)
        for component_index, (label, raw_utilization) in enumerate(components.items()):
            utilization = _finite(raw_utilization, f"构件{member_id}验算项{label}利用率")
            label_text = str(label)
            item = "deflection" if "挠度" in label_text or "变形" in label_text else (
                "strength" if "强度" in label_text or "抗剪" in label_text else "stability")
            check_id = f"CHK-{member_index + 1:04d}-{component_index + 1:02d}"
            trace_id = f"TR-{member_index + 1:04d}-{component_index + 1:02d}"
            checks.append({
                "id": check_id, "target_id": member_id, "combination_id": combination_id,
                "item": item, "status": "PASS" if utilization <= 1.0 else "FAIL",
                "demand": utilization, "limit": 1.0, "comparator": "<=", "unit": "ratio",
                "utilization": utilization,
                "formula_text": "采用构件验算工具输出的利用率U；判定条件 U ≤ 1.0。未补写工具未返回的规范公式。",
                "substitution": f"{label_text}: U={utilization:.9g}; 门槛=1.0。\n{detail_text}".strip(),
                "source": CHECK_SOURCE, "clause": "", "trace_ids": [trace_id],
            })
            traces.append({
                "id": trace_id, "name": f"{member_id} {label_text}利用率", "formula_text": "工具输出利用率 U",
                "inputs": {"member_id": member_id, "check_item": label_text}, "intermediate": [],
                "result": utilization, "unit": "ratio", "source": CHECK_SOURCE,
                "result_path": f"/checks/{len(checks) - 1}/utilization",
            })

    for reaction in reactions:
        if str(reaction.get("node_id")) not in node_lookup:
            raise ValueError("OpenSees 支座反力引用了未知节点")

    request = report.get("request") or {}
    user_material = request.get("material") or {}
    load_note = "OpenSees 单次静力分析输入；各层竖向线荷载与水平节点荷载按实际分析参数记录。"
    analysis_notice = str(result.get("engineering_notice") or "")
    limitations = [
        "本成果源自二维、线弹性、单一静力荷载模式；没有对恒载/活载/风/地震分别建立工况并执行规范组合。DesignBundle 的 ANALYSIS 状态仅表示模型分析状态，不等同 ULS/SLS 设计组合。",
        "工作流2的构件验算器仍有筛查性简化；条文号和规范公式未由该工具以结构化数值回传，导出结果应保留草稿/不完整标识并由专业人员复核。",
        "输出图纸为分析模型方案级图，不含节点连接、螺栓/焊缝、加劲肋、基础、面外构造及施工详图，不能作为正式施工图。",
        analysis_notice,
    ]
    bundle = {
        "schema_version": "1.0",
        "project": {
            "name": str(report.get("project_name") or request.get("project_name") or "钢框架方案"),
            "phase": "截面迭代收敛后的方案级图纸导出", "designer": str(user_material.get("designer") or request.get("designer") or ""),
            "institution": str(request.get("institution") or ""), "student_id": str(request.get("student_id") or ""),
            "date": date.today().isoformat(), "assumptions": [analysis_notice, load_note], "limitations": limitations,
        },
        "model": {
            "nodes": model_nodes, "members": model_members,
            "materials": [{"id": material_id, "name": steel_name, "E_MPa": elastic_modulus, "fy_MPa": fy,
                           "source": f"工作流2输入材料 {steel_name}；Fy={fy:g} MPa。按用户输入/工具内置材料表记录。"}],
            "sections": list(section_records.values()), "supports": model_supports,
        },
        "load_cases": [{"id": case_id, "name": "工作流2 OpenSees 单次分析荷载", "kind": "other", "source": load_note, "loads": case_loads}],
        "combinations": [{"id": combination_id, "name": "MODEL_ANALYSIS（非规范设计组合）", "factors": {case_id: 1.0},
                          "limit_state": "ANALYSIS", "source": load_note}],
        "analysis": {
            "node_displacements": [{"node_id": str(node["node_id"]), "combination_id": combination_id,
                                    "ux_mm": _finite(node["ux_mm"], "节点ux"), "uy_mm": _finite(node["uy_mm"], "节点uy"),
                                    "rz_rad": _finite(node["rz_rad"], "节点转角")} for node in nodes],
            "reactions": [{"node_id": str(item["node_id"]), "combination_id": combination_id,
                           "fx_kN": _finite(item["fx_kN"], "支座Fx"), "fy_kN": _finite(item["fy_kN"], "支座Fy"),
                           "mz_kNm": _finite(item["mz_kNm"], "支座Mz")} for item in reactions],
            "member_end_forces": [], "member_samples": [],
        },
        "checks": checks, "traces": traces,
        "provenance": {
            "data_kind": "upstream", "tool_versions": {
                "opensees_frame_verify": "SteelMind local tool; source recorded in this project",
                "check_steel_member": "SteelMind GB 50017 screening tool; source recorded in this project",
                "steelmind-export": "1.0.0 (integrated adapter)",
            },
            "source": ANALYSIS_SOURCE + " + " + CHECK_SOURCE, "run_id": str(report.get("run_id") or uuid4().hex),
        },
    }
    member_force_map = {str(member["member_id"]): member for member in raw_members}
    bundle["analysis"]["member_end_forces"] = [
        {"member_id": member_id, "combination_id": combination_id,
         **{key: _finite(member_force_map[member_id].get("end_actions_local", {}).get(key), f"{member_id}.{key}")
            for key in ("Ni_kN", "Vi_kN", "Mi_kNm", "Nj_kN", "Vj_kN", "Mj_kNm")}}
        for member_id in sorted(member_ids)
    ]
    return bundle


def inspect_drawing_bundle(report: dict[str, Any]) -> dict[str, Any]:
    try:
        bundle = report.get("construction_drawing_bundle") or build_drawing_bundle(report)
        validation = validate_bundle(bundle)
        return {"valid": validation.valid, "data_validation_status": validation.data_validation_status,
                "upstream_check_summary": validation.upstream_check_summary, "draft": validation.draft,
                "draft_reasons": validation.draft_reasons,
                "errors": [item.model_dump(mode="json") for item in validation.errors],
                "warnings": [item.model_dump(mode="json") for item in validation.warnings],
                "bundle": bundle}
    except Exception as exc:
        return {"valid": False, "data_validation_status": "invalid", "upstream_check_summary": "INCOMPLETE",
                "draft": True, "draft_reasons": [f"导出输入适配失败：{type(exc).__name__}: {exc}"],
                "errors": [{"code": "adapter_error", "message": str(exc), "path": "/"}], "warnings": [], "bundle": None}


@tool
def generate_construction_drawing_package(payload: str) -> str:
    """从工作流2收敛报告生成可追溯计算书、结果表和二维钢框架DXF方案图。"""
    try:
        request = json.loads(payload) if isinstance(payload, str) else dict(payload)
        report = request.get("final_report") or request.get("report") or {}
        preflight = inspect_drawing_bundle(report)
        if not preflight["valid"]:
            return json.dumps({"ok": False, "status": "input_invalid", "preflight": {k: v for k, v in preflight.items() if k != "bundle"}}, ensure_ascii=False)
        options = GenerationOptions.model_validate(request.get("options") or {})
        output_root = Path(os.getenv("STEELMIND_OUTPUT_ROOT", str(BACKEND_ROOT / "artifacts" / "engineering-export-runs")))
        generation = generate_package(preflight["bundle"], options=options, output_dir=output_root)
        from app import LocalArtifactStorage

        storage = LocalArtifactStorage()
        artifacts = []
        run_root = Path(generation.output_dir).resolve()
        for item in generation.artifacts:
            source = (run_root / item.relative_path).resolve()
            if not source.is_relative_to(run_root) or not source.is_file():
                raise ValueError(f"导出器返回非法成果路径：{item.name}")
            content = source.read_bytes()
            if len(content) != item.bytes:
                raise ValueError(f"成果文件长度校验失败：{item.name}")
            key = storage.upload_file(file_content=content, file_name=item.name, content_type=item.media_type)
            artifacts.append({"id": item.id, "name": item.name, "media_type": item.media_type,
                              "bytes": item.bytes, "sha256": item.sha256,
                              "url": storage.generate_presigned_url(key=key)})
        return json.dumps({"ok": generation.generation_status != "failed", "status": generation.generation_status,
                           "generation_status": generation.generation_status,
                           "data_validation_status": generation.data_validation_status,
                           "upstream_check_summary": generation.upstream_check_summary,
                           "draft": generation.draft, "draft_reasons": generation.draft_reasons,
                           "warnings": generation.warnings, "errors": generation.errors,
                           "preflight": {k: v for k, v in preflight.items() if k not in {"bundle", "warnings", "errors"}},
                           "artifacts": artifacts}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
