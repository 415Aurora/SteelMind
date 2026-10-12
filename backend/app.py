"""SteelMind tool gateway for the user's allow-listed Python tools."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

SOURCE = Path(os.getenv("STEEL_TOOL_SOURCE", r"C:\Users\Administrator\Downloads"))
app = FastAPI(title="SteelMind Tool Gateway", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])
TOOL_SPECS = {
    "query_region_params": ("region_params.py", "query_region_params", "联网检索地区抗震、风压和雪压参数"),
    "calculate_load_combination": ("structural_calc.py", "calculate_load_combination", "按输入荷载生成组合设计值"),
    "check_steel_member": ("structural_calc.py", "check_steel_member", "进行钢结构梁柱截面验算"),
    "opensees_frame_verify": ("opensees_analysis.py", "opensees_frame_verify", "运行 OpenSeesPy 平面框架静力验证"),
    "generate_calculation_book": ("generate_design_files.py", "generate_calculation_book", "生成并上传结构计算书"),
    "generate_design_outputs": ("generate_design_files.py", "generate_design_outputs", "生成 Excel、Word 和 DXF 设计产物"),
}
TOOLS: dict[str, Any] = {}
LOAD_ERRORS: dict[str, str] = {}


def _load_module(filename: str):
    path = SOURCE / filename
    if not path.exists():
        raise FileNotFoundError(path)
    name = f"steelmind_user_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise ImportError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_tools() -> None:
    structural = None
    try:
        structural = _load_module("structural_calc.py")
        sys.modules["steelmind_structural_calc"] = structural
        pkg = sys.modules.setdefault("tools", types.ModuleType("tools"))
        setattr(pkg, "structural_calc", structural)
        sys.modules["tools.structural_calc"] = structural
    except Exception as exc:
        LOAD_ERRORS["structural_calc.py"] = f"{type(exc).__name__}: {exc}"

    module_cache: dict[str, Any] = {"structural_calc.py": structural}
    for filename, attr, _ in TOOL_SPECS.values():
        if attr in TOOLS:
            continue
        try:
            module = module_cache.get(filename)
            if module is None:
                module = _load_module(filename)
                module_cache[filename] = module
            TOOLS[attr] = getattr(module, attr)
        except Exception as exc:
            LOAD_ERRORS[attr] = f"{type(exc).__name__}: {exc}"


class InvokeRequest(BaseModel):
    payload: Any = {}


@app.on_event("startup")
def startup() -> None:
    load_tools()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "source": str(SOURCE), "loaded": sorted(TOOLS), "errors": LOAD_ERRORS}


@app.get("/tools")
def list_tools() -> list[dict[str, Any]]:
    return [{"name": name, "description": desc, "available": name in TOOLS, "error": LOAD_ERRORS.get(name)} for name, (_, _, desc) in TOOL_SPECS.items()]


@app.post("/invoke/{tool_name}")
def invoke(tool_name: str, request: InvokeRequest) -> dict[str, Any]:
    if tool_name not in TOOL_SPECS:
        raise HTTPException(status_code=404, detail=f"未允许调用的工具: {tool_name}")
    tool = TOOLS.get(tool_name)
    if tool is None:
        raise HTTPException(status_code=503, detail=LOAD_ERRORS.get(tool_name, "工具不可用"))
    payload = request.payload if isinstance(request.payload, str) else json.dumps(request.payload, ensure_ascii=False)
    try:
        result = tool.invoke(payload) if hasattr(tool, "invoke") else tool(payload)
        return {"ok": True, "tool": tool_name, "result": result}
    except Exception as exc:
        return {"ok": False, "tool": tool_name, "error": f"{type(exc).__name__}: {exc}"}
