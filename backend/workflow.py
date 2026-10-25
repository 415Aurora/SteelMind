"""LangChain LCEL orchestration for a transparent, bounded steel-design workflow.

This graph coordinates existing deterministic engineering tools. It deliberately
does not let an LLM invent loads, member forces, sections, or acceptance criteria.
"""
from __future__ import annotations

import json
import re
from contextvars import ContextVar, Token
from typing import Any, Callable, TypedDict
from uuid import uuid4

from langchain_core.runnables import RunnableLambda


_tool_trace_callback: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar("steel_tool_trace_callback", default=None)


def set_tool_trace_callback(callback: Callable[[dict[str, Any]], None]) -> Token:
    """Attach a per-run callback used by the streaming workflow endpoint."""
    return _tool_trace_callback.set(callback)


def reset_tool_trace_callback(token: Token) -> None:
    _tool_trace_callback.reset(token)


def _emit_tool_trace(event: dict[str, Any]) -> None:
    callback = _tool_trace_callback.get()
    if callback is not None:
        callback(event)


class WorkflowState(TypedDict, total=False):
    request: dict[str, Any]
    log: list[dict[str, Any]]
    errors: list[str]
    load_result: str
    region_result: str
    analysis_result: str
    members: list[dict[str, Any]]
    visualization_result: str
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

    trace_id = uuid4().hex
    _emit_tool_trace({"type": "tool_start", "trace_id": trace_id, "tool": name, "input": payload})
    try:
        tool = TOOLS.get(name)
        if tool is None:
            raise RuntimeError(f"工具未加载：{name}")
        raw = json.dumps(payload, ensure_ascii=False)
        if name in {"search_steel_standards", "query_region_params"}:
            value = tool.invoke(payload) if hasattr(tool, "invoke") else tool(**payload)
        else:
            value = tool.invoke(raw) if hasattr(tool, "invoke") else tool(raw)
        if value is None or not str(value).strip():
            raise RuntimeError(f"{name} 返回空结果")
        output = str(value)
        _emit_tool_trace({"type": "tool_result", "trace_id": trace_id, "tool": name, "ok": True, "output": output})
        return output
    except Exception as exc:
        _emit_tool_trace({"type": "tool_result", "trace_id": trace_id, "tool": name, "ok": False, "output": f"{type(exc).__name__}: {exc}"})
        raise


def _log(state: WorkflowState, stage: str, status: str, message: str) -> list[dict[str, Any]]:
    return [*state.get("log", []), {"stage": stage, "status": status, "message": message}]


def _validate(state: WorkflowState) -> dict[str, Any]:
    req = state["request"]
    geometry = req.get("geometry") or {}
    loads = req.get("loads") or {}
    missing = []
    for key in ("bays", "stories"):
        if geometry.get(key) in (None, ""):
            missing.append(f"geometry.{key}")
    if geometry.get("bay_widths_m") is None and geometry.get("bay_m") in (None, ""):
        missing.append("geometry.bay_m 或 geometry.bay_widths_m")
    if geometry.get("story_heights_m") is None and geometry.get("height_m") in (None, ""):
        missing.append("geometry.height_m 或 geometry.story_heights_m")
    has_line_load = loads.get("q_by_story_kN_per_m") is not None or loads.get("q_kNm") is not None
    if not has_line_load and (loads.get("dead") in (None, "") or loads.get("live") in (None, "")):
        missing.append("loads.dead/live 或 loads.q_by_story_kN_per_m")
    if missing:
        msg = "缺少必要输入：" + ", ".join(missing)
        return {"status": "needs_input", "errors": [msg], "log": _log(state, "参数检查", "failed", msg)}
    try:
        if any(float(geometry[k]) <= 0 for k in ("bays", "stories")):
            raise ValueError("跨数、层数、跨度和高度必须大于 0")
        if geometry.get("bay_m") is not None and float(geometry["bay_m"]) <= 0:
            raise ValueError("跨度必须大于 0")
        if geometry.get("height_m") is not None and float(geometry["height_m"]) <= 0:
            raise ValueError("高度必须大于 0")
        if loads.get("dead") not in (None, "") and float(loads["dead"]) < 0 or loads.get("live") not in (None, "") and float(loads["live"]) < 0:
            raise ValueError("恒载、活载不能为负值")
    except (TypeError, ValueError) as exc:
        msg = f"参数检查失败：{exc}"
        return {"status": "needs_input", "errors": [msg], "log": _log(state, "参数检查", "failed", msg)}
    msg = "几何与基本荷载字段齐全；仍需工程师确认单位、荷载取值及模型假设。"
    return {"status": "running", "log": _log(state, "参数检查", "ok", msg)}


def _combine(state: WorkflowState) -> dict[str, Any]:
    loads = state["request"].get("loads", {})
    if loads.get("dead") in (None, "") or loads.get("live") in (None, ""):
        msg = "未提供恒载/活载分项，已跳过规范荷载组合摘要；OpenSees 将按显式逐层线荷载进行结构分析。"
        return {"load_result": msg, "log": _log(state, "荷载组合", "skipped", msg)}
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


def _query_region(state: WorkflowState) -> dict[str, Any]:
    req = state.get("request", {})
    region = str(req.get("region") or req.get("location") or "").strip()
    if not region:
        return {}
    knowledge = req.get("knowledge") or {}
    enabled = knowledge.get("enabled", req.get("knowledge_enabled", True))
    standard_ids = knowledge.get("standard_ids", req.get("standard_ids", []))
    source_dirs = knowledge.get("source_dirs", req.get("source_dirs", []))
    payload = {"region": region, "items": req.get("region_items"),
               "standard_ids": standard_ids, "source_dirs": source_dirs,
               "knowledge_enabled": enabled}
    try:
        result = _tool_text("query_region_params", payload)
        return {"region_result": result,
                "log": _log(state, "地区规范知识检索", "ok", "已检索本地规范知识库；命中片段仅作为候选依据")}
    except Exception as exc:
        msg = f"地区规范知识检索失败：{exc}"
        return {"region_result": json.dumps({"ok": False, "status": "failed", "error": msg}, ensure_ascii=False),
                "log": _log(state, "地区规范知识检索", "warning", msg)}


def _analyze(state: WorkflowState) -> dict[str, Any]:
    req = state["request"]
    geometry = req.get("geometry", {})
    loads = req.get("loads", {})
    sections = req.get("model_sections", {})
    payload = {
        "geometry": {**geometry, "base_support": geometry.get("base_support", "fixed")},
        "material": req.get("material", req.get("materials", {})),
        "loads": {
            **loads,
            # Keep legacy workflow inputs operational while allowing the new
            # explicit per-story arrays to pass through unchanged.
            "q_kNm": loads.get("q_kNm", loads.get("dead", 0)),
            "lateral_kn": loads.get("lateral_kn", loads.get("wind", 0) + loads.get("seismic", 0)),
        },
        "sections": {
            "beam": sections.get("beam", {"name": sections.get("beam_section", "")}),
            "column": sections.get("column", {"name": sections.get("column_section", "")}),
        },
        "beam_section": sections.get("beam_section", ""),
        "column_section": sections.get("column_section", ""),
    }
    try:
        result = _tool_text("opensees_frame_verify", payload)
        parsed = json.loads(result)
        if not parsed.get("ok"):
            raise RuntimeError(parsed.get("error", result))
        members_by_id = {str(m["member_id"]): dict(m) for m in parsed.get("results", {}).get("members", [])}
        for supplied in req.get("members", []):
            member_id = str(supplied.get("member_id", ""))
            if member_id in members_by_id:
                members_by_id[member_id].update(supplied)
            elif member_id:
                members_by_id[member_id] = dict(supplied)
        members = list(members_by_id.values())
        return {"analysis_result": result, "members": members,
                "log": _log(state, "OpenSeesPy 建模与分析", "ok", f"已分析并提取 {len(members)} 根构件的内力与位移")}
    except Exception as exc:
        msg = f"OpenSeesPy 分析失败：{exc}"
        return {"status": "failed", "errors": [*state.get("errors", []), msg], "log": _log(state, "OpenSeesPy 建模与分析", "failed", msg)}


def _visualize(state: WorkflowState) -> dict[str, Any]:
    """Generate an interactive HTML view from the solver's normalized parameters."""
    analysis_text = state.get("analysis_result", "")
    if not analysis_text:
        return {}
    try:
        analysis = json.loads(analysis_text)
        if not analysis.get("ok") or not analysis.get("parameters"):
            return {}
        statuses = [{"member_id": c.get("member_id"), "member_type": c.get("member_type"),
                     "passed": c.get("passed"), "section": c.get("section"),
                     "steel": c.get("steel"), "span_m": c.get("span_m"),
                     "demands": c.get("demands"), "checks": c.get("checks", []),
                     "result": c.get("result"), "error": c.get("error")}
                    for c in state.get("checks", [])]
        result = _tool_text("opensees_frame_visualize", {
            "parameters": analysis["parameters"], "member_checks": statuses})
        parsed = json.loads(result)
        if not parsed.get("ok"):
            raise RuntimeError(parsed.get("error", "可视化工具未生成 HTML"))
        return {"visualization_result": result,
                "log": _log(state, "框架三维可视化", "ok", "已生成可旋转交互视图")}
    except Exception as exc:
        msg = f"框架三维视图生成失败：{type(exc).__name__}: {exc}"
        # Visualization is auxiliary; keep a valid OpenSees analysis if rendering fails.
        return {"visualization_result": json.dumps({"ok": False, "error": msg}, ensure_ascii=False),
                "log": _log(state, "框架三维可视化", "warning", msg)}


def _prepare_member(state: WorkflowState) -> dict[str, Any]:
    members = state.get("members", state["request"].get("members", []))
    index = state.get("member_index", 0)
    if index >= len(members):
        return {"status": "checks_complete"}
    member = dict(members[index])
    candidates = member.get("candidate_sections") or [member.get("section", "")]
    if not candidates or not candidates[0]:
        msg = f"构件 {member.get('member_id', index + 1)} 未提供 section/candidate_sections"
        candidates = [""]
        state = {**state, "errors": [*state.get("errors", []), msg]}
    candidate_index = state.get("candidate_index", 0)
    member["_candidate_sections"] = candidates
    member["section"] = candidates[min(candidate_index, len(candidates) - 1)]
    return {"current_member": member, "log": state.get("log", [])}


def _check_member(state: WorkflowState) -> dict[str, Any]:
    member = state["current_member"]
    candidate = member["section"]
    payload = {k: v for k, v in member.items() if not k.startswith("_") and k not in ("candidate_sections", "member_id")}
    payload["member_id"] = member.get("member_id")
    payload["structured_output"] = True
    try:
        raw = _tool_text("check_steel_member", payload)
        result = json.loads(raw)
        if not result.get("ok"):
            raise RuntimeError(result.get("error", raw))
        check = {**result, "member_id": member.get("member_id", f"member-{state.get('member_index', 0) + 1}"),
                 "section": candidate, "result": result.get("result_text", "")}
        failed = not result.get("passed", False)
        msg = f"{check['member_id']} 使用 {candidate}：" + ("当前验算未发现失败标记" if not failed else "存在未通过项")
        return {"current_check": check, "checks": [*state.get("checks", []), check],
                "log": _log(state, "构件验算", "ok" if not failed else "review", msg)}
    except Exception as exc:
        msg = f"构件验算调用失败：{exc}"
        check = {"member_id": member.get("member_id", f"member-{state.get('member_index', 0) + 1}"),
                 "section": candidate, "passed": False, "error": msg,
                 "result": msg, "checks": [{"item": "验算执行", "passed": False, "text": msg}]}
        return {"current_check": check, "checks": [*state.get("checks", []), check],
                "errors": [*state.get("errors", []), msg], "log": _log(state, "构件验算", "failed", msg)}


def _after_check(state: WorkflowState) -> str:
    if state.get("status") == "failed":
        return "stop"
    member = state.get("current_member", {})
    if not state.get("current_check", {}).get("passed") and state.get("candidate_index", 0) + 1 < len(member.get("_candidate_sections", [])):
        return "revise"
    if state.get("member_index", 0) + 1 < len(state.get("members", state["request"].get("members", []))):
        return "next_member"
    return "outputs"


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
    if req.get("generate_outputs", True) is False:
        final_status = "needs_revision" if failed else "completed"
        return {"status": final_status, "log": _log(state, "成果输出", "skipped", "按请求跳过文件生成；逐构件结果仍在工作流报告中")}
    name = req.get("project_name", "钢结构初步设计")
    check_text = "\n\n".join(
        f"构件 {c.get('member_id')} | {'通过' if c.get('passed') else '未通过'} | 截面 {c.get('section')}\n{c.get('result', '')}"
        for c in final_checks) or "没有可验算的物理构件结果。"
    chapters = [
        {"title": "项目参数与建模假设", "body": json.dumps({"geometry": geometry, "loads": req.get("loads", {}), "model_sections": req.get("model_sections", {})}, ensure_ascii=False, indent=2)},
        *([{"title": "地区参数规范检索候选依据", "body": state.get("region_result", "")}] if state.get("region_result") else []),
        {"title": "荷载组合", "body": state.get("load_result", "")},
        {"title": "OpenSeesPy 框架分析", "body": state.get("analysis_result", "")},
        {"title": "构件验算与迭代记录", "body": check_text},
        {"title": "验算汇总", "body": f"总构件数：{len(final_checks)}；通过：{len(passing)}；未通过：{len(failed)}。\n未通过构件：{', '.join(str(c.get('member_id')) for c in failed) or '无'}"},
    ]
    conclusion = (f"构件验算完成：{len(passing)} 根通过，{len(failed)} 根未通过。" if failed else "全部构件已完成当前验算项。") + "结果仅供方案研究与计算准备，须由具备资质的工程师核查模型、荷载组合、规范条文适用性及全部计算。"
    output_data = {"project_name": name, "bays": geometry.get("bays", 1), "bay_m": geometry.get("bay_m", 6),
                   "height_m": geometry.get("height_m", 6), "sections": [{"title": "流程结果", "items": [
                       {"name": "荷载组合", "symbol": "load_combo", "value": "已生成", "note": "详见计算书"},
                       {"name": "构件验算", "symbol": "member_check", "value": f"通过 {len(passing)} 项", "note": "只按提交的输入和候选截面检查"},
                       {"name": "OpenSeesPy", "symbol": "analysis", "value": "已完成", "note": "线弹性平面框架验证模型"},
                   ]}], "conclusion": conclusion}
    artifacts: dict[str, str] = {}
    try:
        artifacts["calculation_book"] = _tool_text("generate_calculation_book", {"project_name": name, "chapters": chapters, "conclusion": conclusion})
        if not failed:
            artifacts["design_outputs"] = _tool_text("generate_design_outputs", output_data)
        final_status = "needs_revision" if failed else "completed"
        message = (f"已生成包含逐构件结果的验算报告；{len(failed)} 根未通过，已在可视化中标红，跳过定稿设计文件。"
                   if failed else "已生成逐构件验算报告及设计文件。")
        return {"status": final_status, "artifacts": artifacts,
                "log": _log(state, "成果输出", "review" if failed else "ok", message)}
    except Exception as exc:
        msg = f"成果文件生成失败：{exc}"
        return {"status": "partial", "artifacts": artifacts, "errors": [*state.get("errors", []), msg],
                "log": _log(state, "成果输出", "failed", msg)}


_TERMINAL_STATUSES = {"needs_input", "failed", "needs_revision"}


def _runnable_step(step):
    """Wrap a deterministic state transition as a composable LangChain runnable."""
    def invoke(state: WorkflowState) -> WorkflowState:
        if state.get("status") in _TERMINAL_STATUSES:
            return state
        return {**state, **step(state)}

    return RunnableLambda(invoke)


def _run_member_loop(state: WorkflowState) -> WorkflowState:
    """Run bounded member checks and user-supplied section retries inside LCEL."""
    if state.get("status") in _TERMINAL_STATUSES:
        return state

    while True:
        state.update(_prepare_member(state))
        if state.get("status") in _TERMINAL_STATUSES or state.get("status") == "checks_complete":
            return state

        state.update(_check_member(state))
        route = _after_check(state)
        if route == "stop":
            return state
        if route == "revise":
            state.update(_revise(state))
            continue
        if route == "next_member":
            state.update(_next_member(state))
            continue
        if route == "unresolved":
            if state.get("member_index", 0) + 1 < len(state.get("members", [])):
                state.update(_next_member(state))
                continue
            return state
        if route == "outputs":
            return state


def _finalize(state: WorkflowState) -> WorkflowState:
    return {**state, **_finish(state)}


def _finish(state: WorkflowState) -> dict[str, Any]:
    req = state.get("request", {})
    latest_by_member: dict[str, dict[str, Any]] = {}
    for item in state.get("checks", []):
        latest_by_member[str(item.get("member_id", len(latest_by_member)))] = item
    report = {
        "project_name": req.get("project_name", "钢结构初步设计"),
        "status": state.get("status", "completed"),
        "load_combinations": state.get("load_result", ""),
        "region_knowledge": state.get("region_result", ""),
        "analysis": state.get("analysis_result", ""),
        "visualization": state.get("visualization_result", ""),
        "member_checks": list(latest_by_member.values()),
        "check_history": state.get("checks", []),
        "artifacts": state.get("artifacts", {}),
        "errors": state.get("errors", []),
        "engineering_notice": "该流程是计算辅助原型，不等同完整结构设计。当前 OpenSees 工具为简化线弹性二维框架，不能据此签发施工图或作安全结论。",
    }
    return {"report": report, "log": _log(state, "流程结束", state.get("status", "completed"), "工作流执行结束")}


def build_workflow():
    """Compose validation, analysis, checks, and reporting with LangChain LCEL."""
    return (
        _runnable_step(_validate)
        | _runnable_step(_query_region)
        | _runnable_step(_combine)
        | _runnable_step(_analyze)
        | RunnableLambda(_run_member_loop)
        | _runnable_step(_visualize)
        | _runnable_step(_generate)
        | RunnableLambda(_finalize)
    )


WORKFLOW = build_workflow()


def run_workflow(request: dict[str, Any]) -> dict[str, Any]:
    final = WORKFLOW.invoke({"request": request, "log": [], "errors": [], "checks": [], "artifacts": {},
                             "member_index": 0, "candidate_index": 0, "status": "running"})
    return {"ok": final.get("status") in ("completed", "partial", "needs_revision"), "log": final.get("log", []),
            "report": final.get("report", {}), "status": final.get("status", "failed")}
