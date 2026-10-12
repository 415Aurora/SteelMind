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
S3_SOURCE = SOURCE / "s3_storage.py"
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


def _install_coze_compat() -> None:
    """让用户提供的 Coze 工具可在本地 torch 环境复用。"""
    if "coze_coding_utils.log.write_log" not in sys.modules:
        utils = sys.modules.setdefault("coze_coding_utils", types.ModuleType("coze_coding_utils"))
        log = sys.modules.setdefault("coze_coding_utils.log", types.ModuleType("coze_coding_utils.log"))
        write_log = types.ModuleType("coze_coding_utils.log.write_log")
        from contextvars import ContextVar
        write_log.request_context = ContextVar("request_context", default=None)
        sys.modules["coze_coding_utils.log.write_log"] = write_log
        setattr(log, "write_log", write_log)
        setattr(utils, "log", log)
    if "coze_coding_utils.runtime_ctx.context" not in sys.modules:
        runtime_ctx = sys.modules.setdefault("coze_coding_utils.runtime_ctx", types.ModuleType("coze_coding_utils.runtime_ctx"))
        context = types.ModuleType("coze_coding_utils.runtime_ctx.context")
        context.new_context = lambda **kwargs: kwargs
        sys.modules["coze_coding_utils.runtime_ctx.context"] = context
        setattr(runtime_ctx, "context", context)

    identity = sys.modules.setdefault("coze_workload_identity", types.ModuleType("coze_workload_identity"))
    if not hasattr(identity, "Client"):
        class Client:
            def get_project_env_vars(self):
                return [types.SimpleNamespace(key=k, value=v) for k, v in os.environ.items() if k.startswith("COZE_BUCKET_")]

            def get_access_token(self):
                token = os.getenv("COZE_WORKLOAD_IDENTITY_TOKEN") or os.getenv("COZE_STORAGE_TOKEN")
                if not token:
                    raise RuntimeError("未设置 COZE_WORKLOAD_IDENTITY_TOKEN 或 COZE_STORAGE_TOKEN")
                return token

            def close(self):
                return None
        identity.Client = Client

    if "coze_coding_dev_sdk.s3" not in sys.modules and S3_SOURCE.exists():
        s3_module = _load_module("s3_storage.py")
        base = s3_module.S3SyncStorage

        class S3SyncStorage(base):
            def __init__(self, **kwargs):
                kwargs["access_key"] = kwargs.get("access_key") or os.getenv("COZE_BUCKET_ACCESS_KEY", "")
                kwargs["secret_key"] = kwargs.get("secret_key") or os.getenv("COZE_BUCKET_SECRET_KEY", "")
                kwargs["bucket_name"] = kwargs.get("bucket_name") or os.getenv("COZE_BUCKET_NAME", "")
                super().__init__(**kwargs)

        sdk = sys.modules.setdefault("coze_coding_dev_sdk", types.ModuleType("coze_coding_dev_sdk"))
        s3 = types.ModuleType("coze_coding_dev_sdk.s3")
        s3.S3SyncStorage = S3SyncStorage
        sys.modules["coze_coding_dev_sdk.s3"] = s3
        setattr(sdk, "s3", s3)


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
    _install_coze_compat()
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
