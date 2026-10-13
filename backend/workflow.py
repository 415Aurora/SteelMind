"""LangGraph orchestration for a transparent, bounded steel-design workflow.

This graph coordinates existing deterministic engineering tools. It deliberately
does not let an LLM invent loads, member forces, sections, or acceptance criteria.
"""
from __future__ import annotations

import json
import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class WorkflowState(TypedDict, total=False):
    request: dict[str, Any]
    log: list[dict[str, Any]]
    errors: list[str]
    load_result: str
    analysis_result: str
    checks: list[dict[str, Any]]
    member_index: int
    candidate_index: int
    current_member: dict[str, Any]
    current_check: dict[str, Any]
    status: str
    artifacts: dict[str, str]
    report: dict[str, Any]


def _tool_text(name: str, payload: dict[str, Any]) -> str:
    # Late import avoids coupling module loading to when the gateway loads user tools.
    from app import TOOLS

    tool = TOOLS.get(name)
    if tool is None:
        raise RuntimeError(f"工具未加载：{name}")
    raw = json.dumps(payload, ensure_ascii=False)
    value = tool.invoke(raw) if hasattr(tool, "invoke") else tool(raw)
    if value is None or not str(value).strip():
        raise RuntimeError(f"{name} 返回空结果")
    return str(value)


def _log(state: WorkflowState, stage: str, status: str, message: str) -> list[dict[str, Any]]:
    return [*state.get("log", []), {"stage": stage, "status": status, "message": message}]


def _validate(state: WorkflowState) -> dict[str, Any]:
    req = state["request"]
    geometry = req.get("geometry") or {}
    loads = req.get("loads") or {}
    missing = []
    for key in ("bays", "stories", "bay_m", "height_m"):
        if geometry.get(key) in (None, ""):
            missing.append(f"geometry.{key}")
    for key in ("dead", "live"):
        if loads.get(key) in (None, ""):
            missing.append(f"loads.{key}")
    if missing:
        msg = "缺少必要输入：" + ", ".join(missing)
        return {"status": "needs_input", "errors": [msg], "log": _log(state, "参数检查", "failed", msg)}
    try:
        if any(float(geometry[k]) <= 0 for k in ("bays", "stories", "bay_m", "height_m")):
            raise ValueError("跨数、层数、跨度和高度必须大于 0")
        if float(loads["dead"]) < 0 or float(loads["live"]) < 0:
            raise ValueError("恒载、活载不能为负值")
    except (TypeError, ValueError) as exc:
        msg = f"参数检查失败：{exc}"
        return {"status": "needs_input", "errors": [msg], "log": _log(state, "参数检查", "failed", msg)}
    msg = "几何与基本荷载字段齐全；仍需工程师确认单位、荷载取值及模型假设。"
    return {"status": "running", "log": _log(state, "参数检查", "ok", msg)}


def _combine(state: WorkflowState) -> dict[str, Any]:
    loads = state["request"].get("loads", {})
    try:
        result = _tool_text("calculate_load_combination", {
            "dead": loads["dead"], "live": loads["live"],
            "wind": loads.get("wind", 0), "seismic": loads.get("seismic", 0),
            "unit": loads.get("unit", "kN/m"),
        })
        return {"load_result": result, "log": _log(state, "荷载组合", "ok", "已生成荷载组合摘要")}
    except Exception as exc:
        msg = f"荷载组合失败：{exc}"
        return {"status": "failed", "errors": [*state.get("errors", []), msg], "log": _log(state, "荷载组合", "failed", msg)}


def _analyze(state: WorkflowState) -> dict[str, Any]:
    req = state["request"]
    geometry = req.get("geometry", {})
    loads = req.get("loads", {})
    sections = req.get("model_sections", {})
    payload = {
        **geometry,
        "base_support": geometry.get("base_support", "fixed"),
        "q_kNm": loads.get("q_kNm", loads.get("dead", 0)),
        "lateral_kn": loads.get("lateral_kn", loads.get("wind", 0) + loads.get("seismic", 0)),
        "beam_section": sections.get("beam_section", ""),
        "column_section": sections.get("column_section", ""),
    }
    try:
        result = _tool_text("opensees_frame_verify", payload)
        if "分析失败" in result or "失败" in result:
            raise RuntimeError(result)
        return {"analysis_result": result, "log": _log(state, "OpenSeesPy 建模与分析", "ok", "有限元分析已返回结果")}
    except Exception as exc:
        msg = f"OpenSeesPy 分析失败：{exc}"
        return {"status": "failed", "errors": [*state.get("errors", []), msg], "log": _log(state, "OpenSeesPy 建模与分析", "failed", msg)}


def _prepare_member(state: WorkflowState) -> dict[str, Any]:
    members = state["request"].get("members", [])
    index = state.get("member_index", 0)
    if index >= len(members):
        return {"status": "checks_complete"}
    member = dict(members[index])
    candidates = member.get("candidate_sections") or [member.get("section", "")]
    if not candidates or not candidates[0]:
        msg = f"构件 {member.get('member_id', index + 1)} 未提供 section/candidate_sections"
        return {"status": "failed", "errors": [*state.get("errors", []), msg], "log": _log(state, "构件验算", "failed", msg)}
    candidate_index = state.get("candidate_index", 0)
    member["_candidate_sections"] = candidates
    member["section"] = candidates[min(candidate_index, len(candidates) - 1)]
    return {"current_member": member, "log": state.get("log", [])}


def _check_member(state: WorkflowState) -> dict[str, Any]:
    member = state["current_member"]
    candidate = member["section"]
    payload = {k: v for k, v in member.items() if not k.startswith("_") and k not in ("candidate_sections", "member_id")}
    try:
        result = _tool_text("check_steel_member", payload)
        failed = bool(re.search(r"✗|JSON 解析失败|不支持的钢材|未找到截面|验算失败", result))
        check = {"member_id": member.get("member_id", f"member-{state.get('member_index', 0) + 1}"),
                 "section": candidate, "passed": not failed, "result": result}
        msg = f"{check['member_id']} 使用 {candidate}：" + ("当前验算未发现失败标记" if not failed else "存在未通过项")
        return {"current_check": check, "checks": [*state.get("checks", []), check],
                "log": _log(state, "构件验算", "ok" if not failed else "review", msg)}
    except Exception as exc:
        msg = f"构件验算调用失败：{exc}"
        return {"current_check": {"passed": False, "error": msg}, "status": "failed",
                "errors": [*state.get("errors", []), msg], "log": _log(state, "构件验算", "failed", msg)}


def _after_check(state: WorkflowState) -> str:
    if state.get("status") == "failed":
        return "stop"
    if state.get("current_check", {}).get("passed"):
        if state.get("member_index", 0) + 1 < len(state["request"].get("members", [])):
            return "next_member"
        return "outputs"
    member = state.get("current_member", {})
    if state.get("candidate_index", 0) + 1 < len(member.get("_candidate_sections", [])):
        return "revise"
    return "unresolved"


def _revise(state: WorkflowState) -> dict[str, Any]:
    index = state.get("candidate_index", 0) + 1
    member = dict(state.get("current_member", {}))
    section = member["_candidate_sections"][index]
    member["section"] = section
    msg = f"按用户给定的候选顺序将 {member.get('member_id', '构件')} 截面改为 {section} 并重新验算。"
    return {"candidate_index": index, "current_member": member, "log": _log(state, "截面修改", "review", msg)}


def _next_member(state: WorkflowState) -> dict[str, Any]:
    return {"member_index": state.get("member_index", 0) + 1, "candidate_index": 0}


def _unresolved(state: WorkflowState) -> dict[str, Any]:
    msg = "给定候选截面均未通过当前验算；流程停止自动出成果，请调整设计并由工程师复核。"
    return {"status": "needs_revision", "log": _log(state, "截面修改", "failed", msg)}


def _generate(state: WorkflowState) -> dict[str, Any]:
    req = state["request"]
    geometry = req.get("geometry", {})
    latest_by_member: dict[str, dict[str, Any]] = {}
    for item in state.get("checks", []):
        latest_by_member[str(item.get("member_id", len(latest_by_member)))] = item
    final_checks = list(latest_by_member.values())
    passing = [c for c in final_checks if c.get("passed")]
    failed = [c for c in final_checks if not c.get("passed")]
    if failed:
        msg = "存在未通过的构件验算；为避免生成误导性定稿成果，已跳过输出。请补充候选截面或工程师复核。"
        return {"status": "needs_revision", "log": _log(state, "成果输出", "skipped", msg)}
    if req.get("generate_outputs", True) is False:
        return {"status": "completed", "log": _log(state, "成果输出", "skipped", "按请求跳过文件生成")}
    name = req.get("project_name", "钢结构初步设计")
    check_text = "\n\n".join(c["result"] for c in passing) or "未提供 member_checks；本次仅完成荷载组合与框架分析，未执行构件验算。"
    chapters = [
        {"title": "项目参数与建模假设", "body": json.dumps({"geometry": geometry, "loads": req.get("loads", {}), "model_sections": req.get("model_sections", {})}, ensure_ascii=False, indent=2)},
        {"title": "荷载组合", "body": state.get("load_result", "")},
        {"title": "OpenSeesPy 框架分析", "body": state.get("analysis_result", "")},
        {"title": "构件验算与迭代记录", "body": check_text},
    ]
    conclusion = "工作流已完成。结果仅供方案研究与计算准备，须由具备资质的工程师核查模型、荷载、规范版本及全部验算。"
    output_data = {"project_name": name, "bays": geometry.get("bays", 1), "bay_m": geometry.get("bay_m", 6),
                   "height_m": geometry.get("height_m", 6), "sections": [{"title": "流程结果", "items": [
                       {"name": "荷载组合", "symbol": "load_combo", "value": "已生成", "note": "详见计算书"},
                       {"name": "构件验算", "symbol": "member_check", "value": f"通过 {len(passing)} 项", "note": "只按提交的输入和候选截面检查"},
                       {"name": "OpenSeesPy", "symbol": "analysis", "value": "已完成", "note": "线弹性平面框架验证模型"},
                   ]}], "conclusion": conclusion}
    artifacts: dict[str, str] = {}
    try:
        artifacts["calculation_book"] = _tool_text("generate_calculation_book", {"project_name": name, "chapters": chapters, "conclusion": conclusion})
        artifacts["design_outputs"] = _tool_text("generate_design_outputs", output_data)
        return {"status": "completed", "artifacts": artifacts,
                "log": _log(state, "成果输出", "ok", "计算书、参数表、方案说明书和 DXF 简图已请求生成")}
    except Exception as exc:
        msg = f"成果文件生成失败：{exc}"
        return {"status": "partial", "artifacts": artifacts, "errors": [*state.get("errors", []), msg],
                "log": _log(state, "成果输出", "failed", msg)}


def _route_after_validation(state: WorkflowState) -> str:
    return "stop" if state.get("status") == "needs_input" else "combine"


def _route_after_combine(state: WorkflowState) -> str:
    return "stop" if state.get("status") == "failed" else "analyze"


def _route_after_analysis(state: WorkflowState) -> str:
    return "stop" if state.get("status") == "failed" else "prepare"


def _route_after_members(state: WorkflowState) -> str:
    if state.get("status") == "failed":
        return "stop"
    if state.get("status") == "checks_complete":
        return "outputs"
    return "check"


def _finish(state: WorkflowState) -> dict[str, Any]:
    req = state.get("request", {})
    latest_by_member: dict[str, dict[str, Any]] = {}
    for item in state.get("checks", []):
        latest_by_member[str(item.get("member_id", len(latest_by_member)))] = item
    report = {
        "project_name": req.get("project_name", "钢结构初步设计"),
        "status": state.get("status", "completed"),
        "load_combinations": state.get("load_result", ""),
        "analysis": state.get("analysis_result", ""),
        "member_checks": list(latest_by_member.values()),
        "check_history": state.get("checks", []),
        "artifacts": state.get("artifacts", {}),
        "errors": state.get("errors", []),
        "engineering_notice": "该流程是计算辅助原型，不等同完整结构设计。当前 OpenSees 工具为简化线弹性二维框架，不能据此签发施工图或作安全结论。",
    }
    return {"report": report, "log": _log(state, "流程结束", state.get("status", "completed"), "工作流执行结束")}


def build_workflow():
    graph = StateGraph(WorkflowState)
    for name, node in (("validate", _validate), ("combine", _combine), ("analyze", _analyze),
                       ("prepare_member", _prepare_member), ("check_member", _check_member),
                       ("revise", _revise), ("next_member", _next_member), ("unresolved", _unresolved),
                       ("generate", _generate), ("finish", _finish)):
        graph.add_node(name, node)
    graph.add_edge(START, "validate")
    graph.add_conditional_edges("validate", _route_after_validation, {"stop": "finish", "combine": "combine"})
    graph.add_conditional_edges("combine", _route_after_combine, {"stop": "finish", "analyze": "analyze"})
    graph.add_conditional_edges("analyze", _route_after_analysis, {"stop": "finish", "prepare": "prepare_member"})
    graph.add_conditional_edges("prepare_member", _route_after_members, {"stop": "finish", "check": "check_member", "outputs": "generate"})
    graph.add_conditional_edges("check_member", _after_check, {"stop": "finish", "revise": "revise", "next_member": "next_member", "outputs": "generate", "unresolved": "unresolved"})
    graph.add_edge("revise", "check_member")
    graph.add_edge("next_member", "prepare_member")
    graph.add_edge("unresolved", "finish")
    graph.add_edge("generate", "finish")
    graph.add_edge("finish", END)
    return graph.compile()


WORKFLOW = build_workflow()


def run_workflow(request: dict[str, Any]) -> dict[str, Any]:
    final = WORKFLOW.invoke({"request": request, "log": [], "errors": [], "checks": [], "artifacts": {},
                             "member_index": 0, "candidate_index": 0, "status": "running"},
                            config={"recursion_limit": 100})
    return {"ok": final.get("status") in ("completed", "partial"), "log": final.get("log", []),
            "report": final.get("report", {}), "status": final.get("status", "failed")}
