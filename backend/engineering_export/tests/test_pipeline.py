from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from zipfile import ZipFile

import pytest

from steelmind_export.examples import minimal_bundle, demo_bundle
from steelmind_export.pipeline import generate_package, generate_calculation_book, load_run, resolve_artifact
from steelmind_export.results import BundleValidationError, GenerationOptions


def test_invalid_model_writes_no_run(tmp_path):
    bundle = minimal_bundle()
    bundle["model"]["members"][0]["node_j"] = "missing"
    with pytest.raises(BundleValidationError):
        generate_package(bundle, GenerationOptions(include_pdf=False), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_artifact_hashes_match_payload_and_zip_contains_manifest(tmp_path):
    result = generate_package(minimal_bundle(), {"include_pdf": False}, tmp_path)
    assert result.generation_status == "success"
    assert result.draft
    assert result.upstream_check_summary == "INCOMPLETE"
    run = tmp_path / result.run_id
    assert load_run(tmp_path, result.run_id).input_sha256 == result.input_sha256
    for artifact in result.artifacts:
        path = resolve_artifact(tmp_path, result.run_id, artifact.id)
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact.sha256
    package = next(a for a in result.artifacts if a.name.endswith(".zip"))
    with ZipFile(run / package.relative_path) as z:
        assert "manifest.json" in z.namelist()
        assert "input.json" in z.namelist()
        assert not any(n.endswith(".zip") for n in z.namelist())
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["input_sha256"] == result.input_sha256


def test_dependency_failure_preserves_other_outputs_and_is_partial(tmp_path, monkeypatch):
    monkeypatch.setenv("STEELMIND_SOFFICE", "/missing/soffice")
    result = generate_calculation_book(minimal_bundle(), {}, tmp_path)
    assert result.generation_status == "partial"
    assert result.errors
    assert any(a.name.endswith(".docx") for a in result.artifacts)
    assert any(a.name.endswith(".xlsx") for a in result.artifacts)
    assert not any(a.name.endswith(".pdf") for a in result.artifacts)


def test_independent_runs_never_share_files(tmp_path):
    def build(_):
        return generate_calculation_book(minimal_bundle(), {"include_pdf": False}, tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(build, range(2)))
    assert a.run_id != b.run_id
    assert (tmp_path / a.run_id / "input.json").exists()
    assert (tmp_path / b.run_id / "input.json").exists()


def test_download_rejects_unlisted_artifact_and_tampering(tmp_path):
    result = generate_calculation_book(minimal_bundle(), {"include_pdf": False}, tmp_path)
    with pytest.raises(FileNotFoundError):
        resolve_artifact(tmp_path, "../../etc", "a0001")
    with pytest.raises(FileNotFoundError):
        resolve_artifact(tmp_path, result.run_id, "../input.json")
    artifact = result.artifacts[0]
    (tmp_path / result.run_id / artifact.relative_path).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="校验"):
        resolve_artifact(tmp_path, result.run_id, artifact.id)


def test_upstream_fail_is_preserved_when_files_succeed(tmp_path):
    result = generate_calculation_book(demo_bundle(), {"include_pdf": False}, tmp_path)
    assert result.generation_status == "success"
    assert result.upstream_check_summary == "FAIL"
