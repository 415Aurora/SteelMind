"""Validate once, export immutable runs, then register hashed artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import traceback
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from .models import DesignBundle
from .results import Artifact, BundleValidationError, GenerationOptions, GenerationResult
from .validation import validate_bundle


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _write_json(path: Path, value) -> None:
    path.write_bytes(_json_bytes(value))


def _artifact(path: Path, run: Path, run_id: str, index: int) -> Artifact:
    artifact_id = f"a{index:04d}"
    return Artifact(
        id=artifact_id, name=path.name, relative_path=path.relative_to(run).as_posix(),
        media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        url=f"/api/v1/runs/{run_id}/files/{artifact_id}",
    )


def _generate(bundle, options, output_dir, kind: str) -> GenerationResult:
    opts = options if isinstance(options, GenerationOptions) else GenerationOptions.model_validate(options or {})
    validation = validate_bundle(bundle)
    if not validation.valid:
        raise BundleValidationError(validation)
    raw = bundle.model_dump(mode="json") if isinstance(bundle, DesignBundle) else bundle
    normalized = DesignBundle.model_validate(bundle)
    canonical = normalized.model_dump(mode="json")
    input_hash = hashlib.sha256(_json_bytes(raw)).hexdigest()
    normalized_hash = hashlib.sha256(_json_bytes(canonical)).hexdigest()
    root = Path(output_dir or os.environ.get("STEELMIND_OUTPUT_ROOT", "runs")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex
    run = root / run_id
    run.mkdir()  # Never reuse an existing run, even if the caller repeats the same input.
    created = datetime.now(timezone.utc)
    _write_json(run / "input.json", raw)
    _write_json(run / "normalized.json", canonical)
    _write_json(run / "validation.json", validation.model_dump(mode="json"))
    _write_json(run / "traces.json", [t.model_dump(mode="json") for t in normalized.traces])
    _write_json(run / "run_metadata.json", dict(
        run_id=run_id, created_at=created.isoformat(), schema_version="1.0", generator_version="1.0.0",
        input_sha256=input_hash, normalized_sha256=normalized_hash, options=opts.model_dump(),
        note="上游验算项汇总、数据校核及文件生成状态相互独立；本模块不执行结构分析或规范独立复核。",
    ))
    warnings = [issue.message for issue in validation.warnings]
    errors: list[str] = []
    registered = set(p for p in run.iterdir() if p.is_file())
    log = [f"{created.isoformat()} 校核完成；draft={validation.draft}", f"input_sha256={input_hash}"]
    stages = []
    if kind in ("calculation-book", "package"):
        stages.append(("计算书与结果表", "reports", "export_calculation_book"))
    if kind in ("design-files", "package"):
        stages.append(("CAD设计文件", "cad", "export_design_files"))
    for title, module, function in stages:
        log.append(f"开始 {title}")
        try:
            from importlib import import_module

            exporter = getattr(import_module(f".{module}", __package__), function)
            outcome = exporter(normalized, validation, run, opts)
            warnings.extend(outcome.warnings)
            errors.extend(outcome.errors)
            for file in outcome.files:
                path = Path(file).resolve()
                if path.is_relative_to(run) and path.is_file() and path.stat().st_size:
                    registered.add(path)
                else:
                    errors.append(f'{title}返回了无效成果路径；该文件未发布。')
            log.append(f"{title}：{len(outcome.files)} 个文件；{len(outcome.errors)} 个生成错误")
        except Exception as exc:
            errors.append(f"{title}生成失败：{exc}")
            log.append(traceback.format_exc())
    substantial = any(p.suffix.lower() in {".docx", ".xlsx", ".dxf", ".pdf", ".dwg"} for p in registered)
    status = "success" if not errors else ("partial" if substantial else "failed")
    log.append(f"generation_status={status}; upstream_check_summary={validation.upstream_check_summary}")
    (run / "generation.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    registered.add(run / "generation.log")
    # Only files explicitly accepted by an exporter are downloadable. Failed
    # conversions can leave temporary/partial files in their working folder.
    payload = sorted(registered)
    artifacts = [_artifact(p, run, run_id, i) for i, p in enumerate(payload, 1)]
    _write_json(run / "manifest.json", dict(
        schema="steelmind.manifest.v1", run_id=run_id, input_sha256=input_hash,
        normalized_sha256=normalized_hash, generation_status=status,
        data_validation_status=validation.data_validation_status,
        upstream_check_summary=validation.upstream_check_summary, draft=validation.draft,
        warnings=warnings, errors=errors, files=[a.model_dump() for a in artifacts],
        hash_exclusions=["manifest.json", "result.json", "成果包.zip"],
        hash_note="避免循环哈希：清单覆盖所有payload；清单和ZIP的哈希由result.json/API返回。",
    ))
    manifest = run / "manifest.json"
    package = run / "成果包.zip"
    with ZipFile(package, "w", compression=ZIP_DEFLATED) as archive:
        for path in [*payload, manifest]:
            archive.write(path, path.relative_to(run).as_posix())
    for path in [manifest, package]:
        artifacts.append(_artifact(path, run, run_id, len(artifacts) + 1))
    result = GenerationResult(
        run_id=run_id, created_at=created, kind=kind, generation_status=status,
        data_validation_status=validation.data_validation_status,
        upstream_check_summary=validation.upstream_check_summary, draft=validation.draft,
        draft_reasons=validation.draft_reasons, input_sha256=input_hash,
        normalized_sha256=normalized_hash, output_dir=str(run), artifacts=artifacts,
        warnings=warnings, errors=errors,
    )
    _write_json(run / "result.json", result.model_dump(mode="json"))
    return result


def generate_calculation_book(bundle, options=None, output_dir=None) -> GenerationResult:
    return _generate(bundle, options, output_dir, "calculation-book")


def generate_design_files(bundle, options=None, output_dir=None) -> GenerationResult:
    return _generate(bundle, options, output_dir, "design-files")


def generate_package(bundle, options=None, output_dir=None) -> GenerationResult:
    return _generate(bundle, options, output_dir, "package")


def _run_dir(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise FileNotFoundError("运行编号无效")
    root = Path(root).resolve()
    run = (root / run_id).resolve()
    if not run.is_relative_to(root) or not run.is_dir():
        raise FileNotFoundError("运行不存在")
    return run


def load_run(root: Path, run_id: str) -> GenerationResult:
    path = _run_dir(root, run_id) / "result.json"
    if not path.is_file():
        raise FileNotFoundError("成果尚未就绪或不存在")
    return GenerationResult.model_validate_json(path.read_text(encoding="utf-8"))


def resolve_artifact(root: Path, run_id: str, artifact_id: str) -> Path:
    if not re.fullmatch(r"a\d{4,}", artifact_id):
        raise FileNotFoundError("文件编号无效")
    run = _run_dir(root, run_id)
    result = load_run(root, run_id)
    artifact = next((a for a in result.artifacts if a.id == artifact_id), None)
    if artifact is None:
        raise FileNotFoundError("文件未登记")
    path = (run / artifact.relative_path).resolve()
    if not path.is_relative_to(run) or not path.is_file():
        raise FileNotFoundError("文件不可访问")
    if path.stat().st_size != artifact.bytes or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.sha256:
        raise ValueError("成果文件完整性校验失败；请重新生成。")
    return path
