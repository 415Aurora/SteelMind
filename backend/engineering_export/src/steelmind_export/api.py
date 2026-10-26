"""Local HTTP adapter. Persisted artifact IDs are the only download surface."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .models import DesignBundle
from .pipeline import generate_calculation_book, generate_design_files, generate_package, load_run, resolve_artifact
from .results import BundleValidationError, GenerationOptions, PublicGenerationResult, public_result
from .validation import ValidationReport, validate_bundle


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bundle: DesignBundle
    options: GenerationOptions = Field(default_factory=GenerationOptions)


def create_app(output_root: str | Path | None = None) -> FastAPI:
    root = Path(output_root or os.environ.get("STEELMIND_OUTPUT_ROOT", "runs")).resolve()
    app = FastAPI(title="SteelMind 成果生成接口", version=__version__, description=(
        "二维钢框架方案成果生成。文件生成、数据校核与上游验算项汇总分别报告。"
        "部署默认仅用于本地/团队受控网关。"
    ))
    app.state.output_root = root

    @app.exception_handler(RequestValidationError)
    async def request_error(request, exc):
        # Do not echo raw non-finite values or the full design input in an error.
        detail = [{"loc": list(e["loc"]), "type": e["type"], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": "SCHEMA_INVALID", "detail": detail})

    @app.exception_handler(BundleValidationError)
    async def bundle_error(request, exc):
        return JSONResponse(status_code=422, content={"error": "INPUT_INVALID", "validation": exc.report.model_dump(mode="json")})

    @app.get("/healthz")
    def health():
        return {"status": "ok", "version": __version__, "schema_version": "1.0"}

    @app.post("/api/v1/validate", response_model=ValidationReport)
    def validate(request: ExportRequest):
        report = validate_bundle(request.bundle)
        if not report.valid:
            raise BundleValidationError(report)
        return report.model_dump(mode="json")

    @app.post("/api/v1/calculation-books", response_model=PublicGenerationResult)
    def calculation_books(request: ExportRequest):
        return public_result(generate_calculation_book(request.bundle, request.options, root))

    @app.post("/api/v1/design-files", response_model=PublicGenerationResult)
    def design_files(request: ExportRequest):
        return public_result(generate_design_files(request.bundle, request.options, root))

    @app.post("/api/v1/packages", response_model=PublicGenerationResult)
    def packages(request: ExportRequest):
        return public_result(generate_package(request.bundle, request.options, root))

    @app.get("/api/v1/runs/{run_id}", response_model=PublicGenerationResult)
    def run_result(run_id: str):
        try:
            return public_result(load_run(root, run_id))
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/v1/runs/{run_id}/files/{artifact_id}")
    def download(run_id: str, artifact_id: str):
        try:
            path = resolve_artifact(root, run_id, artifact_id)
            metadata = next(a for a in load_run(root, run_id).artifacts if a.id == artifact_id)
            return FileResponse(path, filename=metadata.name, media_type=metadata.media_type)
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    return app


app = create_app()
