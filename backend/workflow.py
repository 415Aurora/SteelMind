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


def _iteration_input(state: dict[str, Any]) -> dict[str, Any]:
    req = state["request"]
    from section_catalog import section_record
    geometry, loads = req.get("geometry") or {}, req.get("loads") or {}
    sections, candidates = req.get("model_sections") or {}, req.get("candidate_sections") or {}
    missing = [key for key in ("bays", "stories") if geometry.get(key) in (None, "")]
    if geometry.get("bay_widths_m") is None and geometry.get("bay_m") in (None, ""):
        missing.append("geometry.bay_m / bay_widths_m")
    if geometry.get("story_heights_m") is None and geometry.get("height_m") in (None, ""):
        missing.append("geometry.height_m / story_heights_m")
    if loads.get("q_by_story_kN_per_m") is None and loads.get("q_kNm") is None:
        missing.append("loads.q_by_story_kN_per_m")
    if missing:
        return {"status": "needs_input", "errors": ["缺少必要输入：" + ", ".join(missing)]}
    for role in ("beam", "column"):
        initial = sections.get(f"{role}_section") or (sections.get(role) or {}).get("name")
        values = candidates.get(role)
        if not initial or not isinstance(values, list) or not values:
            return {"status": "needs_input", "errors": [f"请提供 model_sections.{role}_section 和 candidate_sections.{role}（按截面由小到大）"]}
        candidate_pairs = [(str(value).strip(), section_record(str(value).strip()))
                           for value in values if str(value).strip()]
        resolved = [item for _, item in candidate_pairs]
        if any(item is None for item in resolved):
            unknown = [value for value, item in candidate_pairs if item is None]
            return {"status": "needs_input", "errors": [f"{role}候选包含不在本地合并截面库中的型号：{', '.join(unknown[:8])}"]}
        initial_record = section_record(str(initial))
        if not initial_record:
            return {"status": "needs_input", "errors": [f"{role}初始截面 {initial} 不在本地合并截面库中"]}
        unique = {item["id"]: item for item in resolved if item}
        names = [row["id"] for row in sorted(unique.values(), key=lambda item: (item["area_mm2"], item["id"]))]
        initial_id = initial_record["id"]
        if initial_id not in names:
            return {"status": "needs_input", "errors": [f"{role}初始截面 {initial} 必须包含在 candidate_sections.{role} 中"]}
        candidates[role] = names
        sections[f"{role}_section"] = initial_id
    try:
        max_iterations = int(req.get("max_iterations", 8))
        if not 1 <= max_iterations <= 20:
            raise ValueError("max_iterations 必须为 1 到 20 的整数")
        target_utilization = float(req.get("target_utilization", 0.85))
        if not 0.6 <= target_utilization <= 0.9:
            raise ValueError("target_utilization 必须在 0.60 到 0.90 之间")
    except (TypeError, ValueError) as exc:
        return {"status": "needs_input", "errors": [str(exc)]}
    return {"status": "running", "request": {**req, "model_sections": sections, "candidate_sections": candidates, "max_iterations": max_iterations,
                                                  "target_utilization": target_utilization},
            "section_map": dict(req.get("initial_member_sections") or {}), "iteration_history": [], "errors": []}


def _section_iteration_loop(state: dict[str, Any]) -> dict[str, Any]:
    """Analyze, check each physical frame member, resize, and re-analyze (bounded)."""
    if state.get("status") != "running":
        return state
    from app import TOOLS

    req = state["request"]
    geometry, loads = req["geometry"], req["loads"]
    model_sections = req["model_sections"]
    beam_initial = model_sections.get("beam_section") or model_sections.get("beam", {}).get("name")
    col_initial = model_sections.get("column_section") or model_sections.get("column", {}).get("name")
    section_map: dict[str, str] = {}
    history: list[dict[str, Any]] = []
    final_analysis: dict[str, Any] = {}
    final_checks: list[dict[str, Any]] = []
    status = "max_iterations"
    steel = (req.get("material") or {}).get("steel_grade", "Q355")
    check_options = req.get("check_options") or {}

    for iteration in range(1, req["max_iterations"] + 1):
        analysis_payload = {
            "geometry": geometry, "loads": loads, "material": req.get("material", {}),
            "sections": {"beam": {"name": beam_initial}, "column": {"name": col_initial}},
            "member_sections": section_map, "iteration": iteration,
        }
        try:
            analysis_raw = _tool_text("opensees_frame_verify", analysis_payload)
            analysis_response = json.loads(analysis_raw)
            if not analysis_response.get("ok"):
                raise RuntimeError(analysis_response.get("error", analysis_raw))
            final_analysis = analysis_response
            analyzed_members = analysis_response.get("results", {}).get("members", [])
            if not analyzed_members:
                raise RuntimeError("OpenSees 未返回任何梁柱构件")
        except Exception as exc:
            return {"status": "failed", "errors": [f"第 {iteration} 轮 OpenSees 分析失败：{exc}"],
                    "section_map": section_map, "iteration_history": history,
                    "analysis_result": json.dumps(final_analysis, ensure_ascii=False)}

        updated_map = dict(section_map)
        iteration_checks: list[dict[str, Any]] = []
        failed_ids: list[str] = []
        changed_ids: list[dict[str, str]] = []
        for member in analyzed_members:
            mid, role = str(member["member_id"]), str(member["member_type"])
            current = section_map.get(mid, member.get("section", ""))
            base_check = {
                **{key: value for key, value in check_options.items() if key in {"section_class_x", "section_class_y", "beta_mx", "beta_b", "eta_b", "deflection_ratio"}},
                "member_id": mid, "member_type": role, "section": current, "steel": steel,
                "span_m": member.get("span_m"), "l0x_m": member.get("l0x_m", member.get("span_m")),
                "l0y_m": member.get("l0y_m", member.get("span_m")),
                "N_kn": member.get("N_kn", 0), "Mx_kNm": member.get("Mx_kNm", 0),
                "My_kNm": member.get("My_kNm", 0), "V_kn": member.get("V_kn", 0),
                "deflection_mm": member.get("deflection_mm", 0),
                "structured_output": True, "iteration": iteration,
            }
            try:
                current_result = json.loads(_tool_text("check_steel_member", base_check))
                if not current_result.get("ok"):
                    raise RuntimeError(current_result.get("error", "验算器未返回有效结果"))
            except Exception as exc:
                return {"status": "failed", "errors": [f"第 {iteration} 轮构件 {mid} 验算调用失败：{exc}"],
                        "section_map": section_map, "iteration_history": history,
                        "analysis_result": json.dumps(final_analysis, ensure_ascii=False)}
            selected = current
            selected_check = current_result
            if iteration == 1 or not current_result.get("passed", False):
                if not current_result.get("passed", False):
                    failed_ids.append(mid)
                candidate_list = (req.get("candidate_sections") or {}).get(role, [])
                try:
                    current_idx = candidate_list.index(current)
                except ValueError:
                    current_idx = -1
                start_idx = 0 if iteration == 1 else current_idx + 1
                # The first pass seeks a passing section near the target utilization.
                # Later passes only move upward, which prevents section oscillation.
                passing_candidates: list[tuple[float, int, str, dict[str, Any]]] = []
                last_candidate: tuple[str, dict[str, Any]] | None = None
                for candidate_index, candidate in enumerate(candidate_list[start_idx:], start=start_idx):
                    if candidate == current:
                        result = current_result
                    else:
                        candidate_payload = {**base_check, "section": candidate}
                        result = json.loads(_tool_text("check_steel_member", candidate_payload))
                    if not result.get("ok"):
                        raise RuntimeError(result.get("error", f"{mid} 候选截面 {candidate} 验算失败"))
                    last_candidate = (candidate, result)
                    if result.get("passed", False):
                        util = float(result.get("utilization", 0.0))
                        passing_candidates.append((abs(util - req["target_utilization"]), candidate_index, candidate, result))
                if passing_candidates:
                    _, _, selected, selected_check = min(passing_candidates, key=lambda item: (item[0], item[1]))
                elif last_candidate:
                    selected, selected_check = last_candidate
                if selected != current and iteration < req["max_iterations"]:
                    updated_map[mid] = selected
                    changed_ids.append({"member_id": mid, "from": current, "to": selected})
                elif iteration >= req["max_iterations"]:
                    # Do not report candidate checks as final results unless that
                    # candidate was actually used in an OpenSees analysis cycle.
                    selected, selected_check = current, current_result
            iteration_checks.append({**selected_check, "member_id": mid, "member_type": role,
                                     "section": selected, "analysis_section": current,
                                     "analysis_demands": {key: member.get(key) for key in ("N_kn", "Mx_kNm", "My_kNm", "V_kn", "deflection_mm")}})

        all_pass_current = all(item.get("passed", False) for item in iteration_checks)
        history.append({"iteration": iteration, "analyzed_sections": {m["member_id"]: section_map.get(m["member_id"], m["section"]) for m in analyzed_members},
                        "member_count": len(iteration_checks), "failed_before_resize": failed_ids,
                        "changes": changed_ids, "passed_after_resize_on_current_forces": sum(bool(c.get("passed")) for c in iteration_checks)})
        final_checks = iteration_checks
        if all_pass_current and not changed_ids:
            status = "converged"
            break
        if iteration == req["max_iterations"]:
            status = "max_iterations"
            break
        if not changed_ids:
            status = "needs_revision"
            break
        section_map = updated_map

    # If the last loop upgraded sections at its end, its checks correspond to the
    # previous model. Require a final analysis/check pass before claiming convergence.
    converged_checked = bool(history and status == "converged")
    vis_result = ""
    try:
        statuses = [{"member_id": c.get("member_id"), "member_type": c.get("member_type"),
                     "passed": c.get("passed"), "section": c.get("section"), "steel": c.get("steel"),
                     "span_m": c.get("span_m"), "demands": c.get("demands"), "checks": c.get("checks", []),
                     "result": c.get("result_text", ""), "error": c.get("error")} for c in final_checks]
        vis_result = _tool_text("opensees_frame_visualize", {"parameters": final_analysis.get("parameters", {}), "member_checks": statuses})
    except Exception as exc:
        state.setdefault("errors", []).append(f"三维可视化生成失败：{exc}")
    artifacts = {}
    final_sections = dict(section_map)
    for member in final_checks:
        final_sections[member["member_id"]] = member.get("section")
    report = {"project_name": req.get("project_name", "钢框架截面迭代与优化"), "status": status,
              "converged": converged_checked, "iterations": history, "final_sections": final_sections,
              "member_checks": final_checks, "analysis": final_analysis, "request": req,
              "run_id": uuid4().hex,
              "visualization": vis_result, "artifacts": artifacts, "errors": state.get("errors", []),
              "engineering_notice": "本功能为二维线弹性单静力工况的方案级迭代原型。轴力采用绝对值包络，弱轴弯矩取零，计算长度暂按几何长度；当前 GB 50017 验算器仍含筛查性简化。通过仅表示当前输入和已实现验算项未发现失败，不能作为设计签审或施工依据。"}
    if converged_checked:
        try:
            from engineering_drawings import inspect_drawing_bundle
            preflight = inspect_drawing_bundle(report)
            if preflight.get("valid") and preflight.get("bundle"):
                report["construction_drawing_bundle"] = preflight["bundle"]
            report["construction_drawing_preflight"] = {key: value for key, value in preflight.items() if key != "bundle"}
        except Exception as exc:
            report["construction_drawing_preflight"] = {
                "valid": False, "data_validation_status": "invalid", "upstream_check_summary": "INCOMPLETE",
                "draft": True, "draft_reasons": [f"图纸输入预检异常：{type(exc).__name__}: {exc}"],
                "errors": [{"code": "preflight_error", "message": str(exc), "path": "/"}], "warnings": [],
            }
    else:
        report["construction_drawing_preflight"] = {
            "valid": False, "data_validation_status": "invalid", "upstream_check_summary": "INCOMPLETE",
            "draft": True, "draft_reasons": ["工作流2未收敛，不能提交给图纸成果生成工具"],
            "errors": [], "warnings": [],
        }
    return {"status": status, "report": report}


SECTION_ITERATION_WORKFLOW = (
    RunnableLambda(lambda s: {**s, **_iteration_input(s)})
    | RunnableLambda(lambda s: {**s, **_section_iteration_loop(s)})
    | RunnableLambda(lambda s: {**s, "result": s.get("report", {"status": s.get("status"), "errors": s.get("errors", [])})})
)


def run_section_iteration(request: dict[str, Any]) -> dict[str, Any]:
    final = SECTION_ITERATION_WORKFLOW.invoke({"request": request})
    status = final.get("status", "failed")
    return {"ok": status in {"converged", "needs_revision", "max_iterations"},
            "status": status, "report": final.get("result", {})}


def _information_selection(request: dict[str, Any]) -> dict[str, Any]:
    req = request
    from app import TOOLS
    from section_catalog import section_record
    raw = _tool_text("validate_steel_frame_parameters", req)
    validation = json.loads(raw)
    if not validation.get("ok"):
        return {"ok": False, "status": "needs_input", "report": {"validation": validation}}

    knowledge = req.get("knowledge") or {}
    query = f"{req.get('region', '')} 钢结构框架设计 荷载取值 抗震设防 安全等级 设计依据".strip()
    rag = _tool_text("search_steel_standards", {
        "query": query, "top_k": req.get("knowledge_top_k", 5),
        "standard_ids": knowledge.get("standard_ids", req.get("standard_ids", [])),
        "source_dirs": knowledge.get("source_dirs", req.get("source_dirs", [])),
        "knowledge_enabled": knowledge.get("enabled", req.get("knowledge_enabled", True)),
    })
    loads = req["loads"]
    combination = _tool_text("calculate_load_combination", {
        "dead": loads["dead"], "live": loads["live"], "wind": loads.get("wind", 0) or 0,
        "seismic": loads.get("seismic", 0) or 0, "unit": loads.get("unit", "kN/m"),
    })
    geometry, material, sections = req["geometry"], req.get("material", {}), req["model_sections"]
    analysis = json.loads(_tool_text("opensees_frame_verify", {
        "geometry": geometry, "loads": loads, "material": material,
        "sections": {"beam": {"name": sections["beam_section"]}, "column": {"name": sections["column_section"]}},
    }))
    if not analysis.get("ok"):
        return {"ok": False, "status": "analysis_failed", "report": {"validation": validation, "analysis": analysis}}
    members = analysis.get("results", {}).get("members", [])
    if not members:
        return {"ok": False, "status": "analysis_failed", "report": {"error": "OpenSees 未返回构件内力"}}
    visualization = _tool_text("opensees_frame_visualize", analysis)

    target = float(req.get("target_utilization", .85))
    candidate_sections = req["candidate_sections"]
    chosen, checks = {}, []
    for member in members:
        role = str(member.get("member_type"))
        candidates = candidate_sections.get(role, [])
        if not candidates:
            continue
        results = []
        for candidate in candidates:
            catalog_row = section_record(str(candidate))
            if not catalog_row:
                continue
            candidate = catalog_row["id"]
            check_payload = {
                "member_id": member.get("member_id"), "member_type": role, "section": candidate,
                "steel": material.get("steel_grade", "Q355"), "span_m": member.get("span_m"),
                "l0x_m": member.get("l0x_m", member.get("span_m")), "l0y_m": member.get("l0y_m", member.get("span_m")),
                "N_kn": member.get("N_kn", 0), "Mx_kNm": member.get("Mx_kNm", 0),
                "My_kNm": member.get("My_kNm", 0), "V_kn": member.get("V_kn", 0),
                "deflection_mm": member.get("deflection_mm", 0), "structured_output": True,
            }
            result = json.loads(_tool_text("check_steel_member", check_payload))
            if result.get("ok"):
                results.append((candidate, result))
        passing = [(name, result) for name, result in results if result.get("passed")]
        pool = passing or results
        if pool:
            selected, result = min(pool, key=lambda row: abs(float(row[1].get("utilization", 0)) - target))
            chosen[str(member["member_id"])] = selected
            checks.append({**result, "member_id": member["member_id"], "member_type": role, "section": selected,
                           "preliminary_only": True})
    report = {
        "status": "preliminary", "validation": validation, "knowledge_result": rag,
        "load_combination": combination, "analysis": analysis, "visualization": visualization, "member_checks": checks,
        "initial_member_sections": chosen,
        "handoff": {**req, "initial_member_sections": chosen},
        "notice": "本流程为初算和截面初选。初选验算使用当前 OpenSees 内力，不会因初选截面变化重新分配内力；请将结果送入截面迭代与优化重新建模验证。",
    }
    return {"ok": True, "status": "preliminary", "report": report}


INFORMATION_SELECTION_WORKFLOW = RunnableLambda(lambda s: _information_selection(s["request"]))


def run_information_selection(request: dict[str, Any]) -> dict[str, Any]:
    return INFORMATION_SELECTION_WORKFLOW.invoke({"request": request})


def _engineering_outputs(payload: dict[str, Any]) -> dict[str, Any]:
    report = payload.get("final_report") or payload.get("report") or {}
    if not report.get("converged") or report.get("status") != "converged":
        return {"ok": False, "status": "not_converged", "errors": ["仅接受截面迭代工作流已收敛的最终报告"]}
    checks = report.get("member_checks") or []
    if not checks or any(not item.get("passed") for item in checks):
        return {"ok": False, "status": "checks_failed", "errors": ["最终报告缺少构件验算记录或存在未通过构件"]}
    preflight = report.get("construction_drawing_preflight") or {}
    if preflight.get("valid") is not True or not report.get("construction_drawing_bundle"):
        return {"ok": False, "status": "export_input_invalid",
                "errors": ["工作流2报告没有通过 DesignBundle 图纸输入预检；请查看 construction_drawing_preflight 后补充或重新分析"],
                "preflight": preflight}
    generated = _tool_text("generate_construction_drawing_package", {"final_report": report})
    try:
        parsed = json.loads(generated)
    except json.JSONDecodeError:
        return {"ok": False, "status": "export_tool_invalid_response", "errors": ["图纸成果工具返回内容无法解析"], "tool_output": generated}
    if not parsed.get("ok"):
        return {"ok": False, "status": parsed.get("status", "generation_failed"),
                "errors": [parsed.get("error", "图纸成果生成失败")], "preflight": parsed.get("preflight")}
    return {"ok": True, "status": parsed.get("generation_status", "completed"),
            "preflight": parsed.get("preflight"), "artifacts": {"engineering_package": parsed}}


ENGINEERING_OUTPUT_WORKFLOW = RunnableLambda(_engineering_outputs)


def run_engineering_outputs(payload: dict[str, Any]) -> dict[str, Any]:
    return ENGINEERING_OUTPUT_WORKFLOW.invoke(payload)
