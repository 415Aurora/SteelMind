"""Agent adapter for the standalone Q235 welded-section selector."""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from langchain.tools import tool


TOOL_DIR = Path(__file__).resolve().parent / "Q235_钢结构强度选截面工具"
OPTIMIZER_PATH = TOOL_DIR / "steel_section_optimizer.py"
MODULE_NAME = "steelmind_q235_section_optimizer_impl"


def _load_optimizer():
    if MODULE_NAME in sys.modules:
        return sys.modules[MODULE_NAME]
    if not OPTIMIZER_PATH.is_file():
        raise FileNotFoundError(f"Q235截面优化器文件不存在：{OPTIMIZER_PATH}")
    spec = importlib.util.spec_from_file_location(MODULE_NAME, OPTIMIZER_PATH)
    if not spec or not spec.loader:
        raise ImportError(f"无法加载Q235截面优化器：{OPTIMIZER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _unwrap_analysis(value: Any) -> dict[str, Any]:
    """Accept either a direct OpenSees result or the gateway's wrapped result."""
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise ValueError("opensees_result 必须是对象或 JSON 字符串")
    current = value
    for _ in range(4):
        if isinstance(current.get("members"), list):
            return current
        nested = current.get("result")
        if isinstance(nested, str):
            nested = json.loads(nested)
        if not isinstance(nested, dict):
            break
        current = nested
    raise ValueError("OpenSees结果中未找到 members 构件数组")


def _from_opensees(source: dict[str, Any]) -> list[dict[str, Any]]:
    members = []
    for raw in source["members"]:
        member_id = str(raw.get("member_id") or raw.get("id") or "").strip()
        if not member_id:
            raise ValueError("OpenSees结果的每个构件都必须包含 member_id")
        section = str(raw.get("section") or raw.get("current_section") or "").strip()
        if not section:
            raise ValueError(f"构件 {member_id} 缺少 section 型号")
        force_rows = raw.get("forces")
        if not force_rows:
            force_rows = []
            # The current OpenSees 2D tool exports localForce as
            # [N_i, V_i, M_i, N_j, V_j, M_j] for each elastic element.
            for element in raw.get("end_forces_local", []):
                vector = element.get("local_force") if isinstance(element, dict) else element
                if not isinstance(vector, (list, tuple)) or len(vector) < 6:
                    raise ValueError(f"构件 {member_id} 的 end_forces_local 项不是6分量OpenSees局部端力")
                element_id = element.get("element_tag", "element") if isinstance(element, dict) else "element"
                for end, offset in (("i", 0), ("j", 3)):
                    force_rows.append({
                        "case": str(source.get("load_case") or "OpenSees_static"),
                        "station": f"{element_id}_{end}",
                        "N": float(vector[offset]),
                        # The model uses the strong-axis inertia in its 2D
                        # plane; map its in-plane moment/shear to My/Vz here.
                        "My": float(vector[offset + 2]), "Mz": 0.0,
                        "Vy": 0.0, "Vz": float(vector[offset + 1]), "T": 0.0,
                    })
        if not force_rows:
            raise ValueError(f"构件 {member_id} 未提供 forces 或 OpenSees end_forces_local")
        members.append({
            "id": member_id,
            "design_group": raw.get("design_group"),
            "length_mm": float(raw.get("length_mm") or float(raw.get("span_m", 0)) * 1000),
            "current_section": section,
            "forces": force_rows,
        })
    return members


@tool
def optimize_q235_steel_sections(payload: str) -> str:
    """对OpenSees杆件内力逐构件搜索本地Q235焊接H型截面库，按强度筛选并输出建议截面。

    输入采用 N、mm、N·mm、MPa；可传 members 的 forces 样本，也可传
    opensees_result（支持网关返回对象及 end_forces_local）。仅作强度初选，
    不验算整体稳定、局部稳定、长细比、变形、连接或多工况完整组合。
    """
    try:
        data = json.loads(payload) if isinstance(payload, str) else dict(payload)
        analysis = data.get("opensees_result")
        mapped_opensees = False
        if analysis is not None:
            unwrapped = _unwrap_analysis(analysis)
            data["members"] = _from_opensees(unwrapped)
            data.setdefault("units", "N-mm-MPa")
            data.setdefault("axes", "y=flange_width,z=section_height")
            mapped_opensees = True
        elif isinstance(data.get("result"), (dict, str)):
            unwrapped = _unwrap_analysis(data)
            data["members"] = _from_opensees(unwrapped)
            data.setdefault("units", "N-mm-MPa")
            data.setdefault("axes", "y=flange_width,z=section_height")
            mapped_opensees = True
        elif any(member.get("end_forces_local") for member in data.get("members", []) if isinstance(member, dict)):
            data["members"] = _from_opensees(data)
            data.setdefault("units", "N-mm-MPa")
            data.setdefault("axes", "y=flange_width,z=section_height")
            mapped_opensees = True

        if data.get("units") != "N-mm-MPa":
            raise ValueError("单位必须为 N-mm-MPa；OpenSees适配输入自动按 N、mm、N·mm 转换")
        if data.get("axes") != "y=flange_width,z=section_height":
            raise ValueError("axes 必须明确为 y=flange_width,z=section_height")
        optimizer = _load_optimizer()
        base_library = optimizer.load_library()
        library = {}
        for original_name, section in base_library.items():
            canonical_name = "WH-" + original_name
            library[canonical_name] = replace(section, name=canonical_name)
        for member in data.get("members", []):
            current = str(member.get("current_section", ""))
            already_welded_id = current.startswith("WH-")
            unprefixed = current.removeprefix("WH-")
            from section_catalog import section_record
            catalog_row = section_record(unprefixed)
            if (unprefixed in base_library and (already_welded_id or not mapped_opensees)
                    and (already_welded_id or catalog_row is None or catalog_row.get("catalog_type") == "welded_q235")):
                member["current_section"] = "WH-" + unprefixed

        result = optimizer.optimize(data, library)
        result["catalog"] = {
            "catalog_type": "welded_q235",
            "catalog_id_prefix": "WH-",
            "record_count": len(base_library),
            "source": "backend/tool_sources/Q235_钢结构强度选截面工具/焊接对称工字型截面_Q235_筛选保留.csv",
        }
        result["notice"] += "；当前截面若不属于Q235焊接候选库，仅报告型号，不对该当前截面做本库复算。"
        if mapped_opensees:
            result["notice"] += "OpenSees自动转换仅对应本项目二维梁柱单元局部端力映射；弱轴弯矩、弱轴剪力和扭矩按零处理。"
        return json.dumps(result, ensure_ascii=False, allow_nan=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
