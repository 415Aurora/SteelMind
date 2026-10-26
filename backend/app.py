"""SteelMind HTTP gateway for the user's allow-listed structural tools."""
from __future__ import annotations

import importlib.util
import json
import os
import queue
import re
import sys
import threading
import types
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

SOURCE = Path(os.getenv("STEEL_TOOL_SOURCE", str(Path(__file__).resolve().parent / "tool_sources"))).expanduser().resolve()
ARTIFACT_DIR = Path(os.getenv("STEEL_ARTIFACT_DIR", str(Path(__file__).parent / "artifacts"))).resolve()
SITE_ORIGIN = "https://steelmind-design-assistant.siwuxiegroup.chatgpt.site"
DEFAULT_ORIGINS = [SITE_ORIGIN, "http://localhost:8080", "http://127.0.0.1:8080"]
ALLOWED_ORIGINS = [x.strip() for x in os.getenv("STEEL_ALLOWED_ORIGINS", ",".join(DEFAULT_ORIGINS)).split(",") if x.strip()]
S3_SOURCE = SOURCE / "s3_storage.py"

app = FastAPI(title="SteelMind Tool Gateway", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    # Required by browsers that still use Private Network Access preflights
    # when an HTTPS Site calls its user's loopback companion service.
    # Exact-origin allowlisting above remains mandatory.
    allow_private_network=True,
)

TOOL_SPECS = {
    "validate_steel_frame_parameters": ("structural_calc.py", "validate_steel_frame_parameters", "校验钢框架几何、荷载、材料与初选截面参数"),
    "query_region_params": ("__knowledge__", "query_region_params", "从本地规范 RAG 检索地区参数候选依据（需核验）"),
    "search_steel_standards": ("__knowledge__", "search_steel_standards", "检索本地 07 规范知识库并返回可追溯条文片段"),
    "calculate_load_combination": ("structural_calc.py", "calculate_load_combination", "按输入荷载生成组合设计值"),
    "check_steel_member": ("structural_calc.py", "check_steel_member", "进行钢结构梁柱截面验算"),
    "optimize_steel_truss_members": ("structural_calc.py", "optimize_steel_truss_members", "兼容旧版：对 ANSYS 导出的钢网架杆件结果逐根筛查；钢框架迭代请用 /workflow/section-iteration/run-stream"),
    "opensees_frame_verify": ("opensees_analysis.py", "opensees_frame_verify", "运行 OpenSeesPy 平面框架静力验证"),
    "opensees_frame_visualize": ("opensees_visualize.py", "opensees_frame_visualize", "生成可拖拽旋转的 OpenSees 框架三维视图"),
    "draw_steel_section": ("opensees_visualize.py", "draw_steel_section", "根据型钢型号绘制截面并返回几何尺寸与截面特性"),
    "generate_calculation_book": ("generate_design_files.py", "generate_calculation_book", "生成结构计算书"),
    "generate_design_outputs": ("generate_design_files.py", "generate_design_outputs", "生成 Excel、Word 和 DXF 设计产物"),
    "generate_construction_drawing_package": ("engineering_drawings.py", "generate_construction_drawing_package", "将工作流2收敛结果映射为可追溯 DesignBundle 并生成计算书、结果表与二维 DXF 方案图包"),
}
TOOLS: dict[str, Any] = {}
LOAD_ERRORS: dict[str, str] = {}


class LocalArtifactStorage:
    """本地对象存储兼容层；无需 S3 即可生成并下载工具产物。"""

    def upload_file(self, *, file_content: bytes, file_name: str, content_type: str = "application/octet-stream", **_: Any) -> str:
        ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^\w.-]+", "_", Path(file_name).name, flags=re.UNICODE).strip("._") or "artifact.bin"
        artifact_id = f"{uuid4().hex}_{safe_name}"
        target = (ARTIFACT_DIR / artifact_id).resolve()
        if target.parent != ARTIFACT_DIR:
            raise ValueError("非法产物文件名")
        target.write_bytes(file_content)
        return artifact_id

    def generate_presigned_url(self, *, key: str, expire_time: int = 86400, **_: Any) -> str:
        # 本地链接不是签名链接；有效期参数仅为兼容 Coze/S3 工具接口。
        base = os.getenv("STEEL_TOOL_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
        return f"{base}/files/{quote(key, safe='_.-')}"


def _install_langchain_compat() -> None:
    """结构工具本身不依赖 LangChain；提供轻量 @tool/.invoke 兼容层。"""
    try:
        from langchain.tools import tool as _tool  # noqa: F401
        return
    except Exception:
        package = sys.modules.setdefault("langchain", types.ModuleType("langchain"))
        tools_module = types.ModuleType("langchain.tools")

        def tool(function):
            function.invoke = lambda value: function(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
            return function

        tools_module.tool = tool
        sys.modules["langchain.tools"] = tools_module
        setattr(package, "tools", tools_module)


def _install_coze_compat() -> None:
    """Support the context imports used by the user's Coze-authored functions."""
    if "coze_coding_utils.log.write_log" not in sys.modules:
        utils = sys.modules.setdefault("coze_coding_utils", types.ModuleType("coze_coding_utils"))
        log = sys.modules.setdefault("coze_coding_utils.log", types.ModuleType("coze_coding_utils.log"))
        write_log = types.ModuleType("coze_coding_utils.log.write_log")
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

    sdk = sys.modules.setdefault("coze_coding_dev_sdk", types.ModuleType("coze_coding_dev_sdk"))
    if "coze_coding_dev_sdk.s3" not in sys.modules:
        s3_module = types.ModuleType("coze_coding_dev_sdk.s3")
        try:
            if S3_SOURCE.exists():
                base = _load_module("s3_storage.py").S3SyncStorage

                class S3SyncStorage(base):
                    def __init__(self, **kwargs):
                        kwargs["access_key"] = kwargs.get("access_key") or os.getenv("COZE_BUCKET_ACCESS_KEY", "")
                        kwargs["secret_key"] = kwargs.get("secret_key") or os.getenv("COZE_BUCKET_SECRET_KEY", "")
                        kwargs["bucket_name"] = kwargs.get("bucket_name") or os.getenv("COZE_BUCKET_NAME", "")
                        super().__init__(**kwargs)

                s3_module.S3SyncStorage = S3SyncStorage
            else:
                raise FileNotFoundError(S3_SOURCE)
        except Exception as exc:
            LOAD_ERRORS["s3_storage.py"] = f"S3 兼容模块不可用：{type(exc).__name__}: {exc}"

            class S3SyncStorage:
                def __init__(self, **_kwargs):
                    raise RuntimeError(LOAD_ERRORS["s3_storage.py"])

            s3_module.S3SyncStorage = S3SyncStorage
        sys.modules["coze_coding_dev_sdk.s3"] = s3_module
        setattr(sdk, "s3", s3_module)


def _load_module(filename: str):
    path = SOURCE / filename
    if not path.is_file():
        raise FileNotFoundError(f"工具源文件不存在：{path}")
    name = f"steelmind_user_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    if not spec or not spec.loader:
        raise ImportError(f"无法加载工具源文件：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _s3_is_configured() -> bool:
    required = ("COZE_BUCKET_ENDPOINT_URL", "COZE_BUCKET_NAME", "COZE_BUCKET_ACCESS_KEY", "COZE_BUCKET_SECRET_KEY")
    has_identity = bool(os.getenv("COZE_WORKLOAD_IDENTITY_TOKEN") or os.getenv("COZE_STORAGE_TOKEN"))
    return all(os.getenv(name) for name in required) and has_identity and importlib.util.find_spec("boto3") is not None


def load_tools() -> None:
    TOOLS.clear()
    LOAD_ERRORS.clear()
    try:
        _install_langchain_compat()
        _install_coze_compat()
    except Exception as exc:
        LOAD_ERRORS["compatibility"] = f"{type(exc).__name__}: {exc}"

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
    try:
        from knowledge_tools import LANGCHAIN_TOOLS
        TOOLS.update({tool.name: tool for tool in LANGCHAIN_TOOLS})
    except Exception as exc:
        LOAD_ERRORS["local_standards_rag"] = f"{type(exc).__name__}: {exc}"
    for filename, attr, _ in TOOL_SPECS.values():
        if filename == "__knowledge__":
            continue
        if attr in TOOLS:
            continue
        try:
            module = module_cache.get(filename)
            if module is None:
                module = _load_module(filename)
                module_cache[filename] = module
            if filename == "engineering_drawings.py":
                sys.modules["engineering_drawings"] = module
            TOOLS[attr] = getattr(module, attr)
            if filename == "generate_design_files.py" and not _s3_is_configured():
                module._get_storage = LocalArtifactStorage
            if filename == "opensees_visualize.py":
                module.ARTIFACT_DIR = ARTIFACT_DIR
                module.PUBLIC_BASE = os.getenv("STEEL_TOOL_PUBLIC_URL", "http://127.0.0.1:8000").rstrip("/")
        except Exception as exc:
            LOAD_ERRORS[attr] = f"{type(exc).__name__}: {exc}"


@app.on_event("startup")
def startup() -> None:
    load_tools()


def _availability_error(name: str) -> str | None:
    if name not in TOOLS:
        return LOAD_ERRORS.get("local_standards_rag", LOAD_ERRORS.get(name, "工具未加载")) if name in {"query_region_params", "search_steel_standards"} else LOAD_ERRORS.get(name, "工具未加载")
    if name == "opensees_frame_verify":
        try:
            if importlib.util.find_spec("openseespy.opensees") is None:
                return "未安装 openseespy；请在工具服务所用 Python 环境安装 OpenSeesPy。"
        except (ImportError, ModuleNotFoundError, ValueError):
            return "未安装 openseespy；请在工具服务所用 Python 环境安装 OpenSeesPy。"
    if name == "generate_construction_drawing_package":
        missing = [module for module in ("ezdxf", "matplotlib", "pypdfium2", "pypdf")
                   if importlib.util.find_spec(module) is None]
        if missing:
            return "施工图成果包依赖未安装：" + ", ".join(missing) + "；请按 backend/requirements.txt 安装。"
    return None


def _tool_status() -> list[dict[str, Any]]:
    result = []
    for name, (_, _, description) in TOOL_SPECS.items():
        error = _availability_error(name)
        result.append({"name": name, "description": description, "available": error is None, "error": error})
    return result


class InvokeRequest(BaseModel):
    payload: Any = Field(default_factory=dict)


class WorkflowRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
def health() -> dict[str, Any]:
    statuses = _tool_status()
    return {
        "ok": True,
        "source": str(SOURCE),
        "loaded": sorted(TOOLS),
        "available_count": sum(item["available"] for item in statuses),
        "tool_count": len(TOOL_SPECS),
        "errors": {item["name"]: item["error"] for item in statuses if item["error"]},
    }


@app.get("/tools")
def list_tools() -> list[dict[str, Any]]:
    return _tool_status()


@app.get("/knowledge/bases")
def list_knowledge_bases() -> dict[str, Any]:
    """Expose the local RAG index inventory to the webpage."""
    try:
        from knowledge_tools import knowledge_inventory
        return knowledge_inventory()
    except Exception as exc:
        return {"available": False, "source": "local_standards_rag", "count": 0,
                "knowledge_bases": [], "error": f"{type(exc).__name__}: {exc}"}


class KnowledgeSearchRequest(BaseModel):
    query: str = ""
    top_k: int = Field(default=5, ge=1, le=20)
    standard_ids: list[str] = Field(default_factory=list)
    source_dirs: list[str] = Field(default_factory=list)
    knowledge_enabled: bool = True


@app.post("/knowledge/search")
def search_local_knowledge(request: KnowledgeSearchRequest) -> dict[str, Any]:
    try:
        from knowledge_tools import search_payload
        return search_payload(request.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"本地规范知识库检索失败：{type(exc).__name__}: {exc}") from exc


@app.get("/workflow/health")
def workflow_health() -> dict[str, Any]:
    try:
        from langchain_core.runnables import RunnableLambda  # noqa: F401
        from workflow import WORKFLOW  # noqa: F401
        from workflow import SECTION_ITERATION_WORKFLOW  # noqa: F401
        from workflow import INFORMATION_SELECTION_WORKFLOW, ENGINEERING_OUTPUT_WORKFLOW  # noqa: F401
        return {"available": True, "engine": "LangChain LCEL", "workflows": ["information-selection-v1", "steel-frame-section-iteration-v1", "engineering-outputs-v1"]}
    except Exception as exc:
        return {"available": False, "engine": "LangChain LCEL", "error": f"{type(exc).__name__}: {exc}"}


@app.post("/workflow/run")
def run_design_workflow(request: WorkflowRequest) -> dict[str, Any]:
    """Run the LangChain LCEL steel design pipeline."""
    try:
        from workflow import run_workflow
        result = run_workflow(request.payload)
        if result.get("status") == "failed":
            raise HTTPException(status_code=422, detail=result)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"工作流执行异常：{type(exc).__name__}: {exc}") from exc


@app.post("/workflow/run-stream")
def run_design_workflow_stream(request: WorkflowRequest) -> StreamingResponse:
    """Stream each real tool call's input/output and the final workflow result."""
    try:
        from workflow import reset_tool_trace_callback, run_workflow, set_tool_trace_callback
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"LangChain 工作流不可用：{type(exc).__name__}: {exc}") from exc

    events: queue.Queue[Any] = queue.Queue()
    finished = object()

    def execute() -> None:
        token = set_tool_trace_callback(events.put)
        try:
            events.put({"type": "workflow_started"})
            result = run_workflow(request.payload)
            events.put({"type": "workflow_completed", "result": result})
        except Exception as exc:
            events.put({"type": "workflow_error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            reset_tool_trace_callback(token)
            events.put(finished)

    threading.Thread(target=execute, name="steel-workflow-stream", daemon=True).start()

    def stream_events():
        while True:
            event = events.get()
            if event is finished:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/workflow/section-iteration/run")
def run_section_iteration(request: WorkflowRequest) -> dict[str, Any]:
    """Bounded OpenSees → member checks → section update/re-analysis loop."""
    try:
        from workflow import run_section_iteration as execute_iteration
        return execute_iteration(request.payload)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"截面迭代工作流异常：{type(exc).__name__}: {exc}") from exc


@app.post("/workflow/information-selection/run-stream")
def run_information_selection_stream(request: WorkflowRequest) -> StreamingResponse:
    try:
        from workflow import reset_tool_trace_callback, run_information_selection, set_tool_trace_callback
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"信息获取与截面初选工作流不可用：{type(exc).__name__}: {exc}") from exc
    events: queue.Queue[Any] = queue.Queue()
    finished = object()
    def execute() -> None:
        token = set_tool_trace_callback(events.put)
        try:
            events.put({"type": "workflow_started", "workflow": "information_selection"})
            events.put({"type": "workflow_completed", "result": run_information_selection(request.payload)})
        except Exception as exc:
            events.put({"type": "workflow_error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            reset_tool_trace_callback(token)
            events.put(finished)
    threading.Thread(target=execute, name="steel-information-selection", daemon=True).start()
    def stream_events():
        while True:
            event = events.get()
            if event is finished:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(stream_events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/workflow/engineering-outputs/run-stream")
def run_engineering_outputs_stream(request: WorkflowRequest) -> StreamingResponse:
    try:
        from workflow import reset_tool_trace_callback, run_engineering_outputs, set_tool_trace_callback
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"工程文件输出工作流不可用：{type(exc).__name__}: {exc}") from exc
    events: queue.Queue[Any] = queue.Queue()
    finished = object()
    def execute() -> None:
        token = set_tool_trace_callback(events.put)
        try:
            events.put({"type": "workflow_started", "workflow": "engineering_outputs"})
            events.put({"type": "workflow_completed", "result": run_engineering_outputs(request.payload)})
        except Exception as exc:
            events.put({"type": "workflow_error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            reset_tool_trace_callback(token)
            events.put(finished)
    threading.Thread(target=execute, name="steel-engineering-outputs", daemon=True).start()
    def stream_events():
        while True:
            event = events.get()
            if event is finished:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(stream_events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/workflow/section-iteration/run-stream")
def run_section_iteration_stream(request: WorkflowRequest) -> StreamingResponse:
    """Stream each OpenSees and GB 50017 screening tool call during iteration."""
    try:
        from workflow import reset_tool_trace_callback, run_section_iteration as execute_iteration, set_tool_trace_callback
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"截面迭代工作流不可用：{type(exc).__name__}: {exc}") from exc

    events: queue.Queue[Any] = queue.Queue()
    finished = object()

    def execute() -> None:
        token = set_tool_trace_callback(events.put)
        try:
            events.put({"type": "workflow_started", "workflow": "section_iteration"})
            result = execute_iteration(request.payload)
            events.put({"type": "workflow_completed", "result": result})
        except Exception as exc:
            events.put({"type": "workflow_error", "message": f"{type(exc).__name__}: {exc}"})
        finally:
            reset_tool_trace_callback(token)
            events.put(finished)

    threading.Thread(target=execute, name="steel-section-iteration", daemon=True).start()

    def stream_events():
        while True:
            event = events.get()
            if event is finished:
                break
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream_events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/files/{artifact_id}")
def download_artifact(artifact_id: str) -> FileResponse:
    if not re.fullmatch(r"[0-9a-f]{32}_[A-Za-z0-9._-]+", artifact_id):
        raise HTTPException(status_code=404, detail="文件不存在")
    path = (ARTIFACT_DIR / artifact_id).resolve()
    if path.parent != ARTIFACT_DIR or not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在或已清理")
    return FileResponse(path, filename=path.name.split("_", 1)[1])


@app.post("/invoke/{tool_name}")
def invoke(tool_name: str, request: InvokeRequest) -> dict[str, Any]:
    if tool_name not in TOOL_SPECS:
        raise HTTPException(status_code=404, detail=f"未允许调用的工具：{tool_name}")
    reason = _availability_error(tool_name)
    if reason:
        raise HTTPException(status_code=503, detail=reason)
    tool = TOOLS[tool_name]
    payload = request.payload if isinstance(request.payload, str) else json.dumps(request.payload, ensure_ascii=False)
    try:
        if tool_name in {"search_steel_standards", "query_region_params"}:
            structured_payload = request.payload if isinstance(request.payload, dict) else json.loads(payload)
            result = tool.invoke(structured_payload) if hasattr(tool, "invoke") else tool(**structured_payload)
        else:
            result = tool.invoke(payload) if hasattr(tool, "invoke") else tool(payload)
        if result is None or result == "":
            return {"ok": False, "tool": tool_name, "error": "工具返回空结果；请检查输入参数和工具日志。"}
        return {"ok": True, "tool": tool_name, "result": result}
    except Exception as exc:
        return {"ok": False, "tool": tool_name, "error": f"{type(exc).__name__}: {exc}"}
