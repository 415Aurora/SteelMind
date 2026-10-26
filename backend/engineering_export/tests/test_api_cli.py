import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient

from steelmind_export.api import create_app
from steelmind_export.examples import minimal_bundle


def test_api_validation_and_extra_fields_are_rejected(tmp_path):
    client = TestClient(create_app(tmp_path))
    bundle = minimal_bundle()
    assert client.post("/api/v1/validate", json={"bundle": bundle}).json()["valid"]
    bundle["model"]["nodes"][0]["x_m"] = True
    assert client.post("/api/v1/validate", json={"bundle": bundle}).status_code == 422
    invalid_reference = minimal_bundle()
    invalid_reference["model"]["members"][0]["node_j"] = "missing"
    assert client.post("/api/v1/validate", json={"bundle": invalid_reference}).status_code == 422
    nan = json.dumps({"bundle": minimal_bundle()}).replace('"x_m": 0.0', '"x_m": NaN', 1)
    assert client.post("/api/v1/validate", content=nan, headers={"content-type": "application/json"}).status_code == 422


def test_api_exports_and_safe_downloads(tmp_path):
    client = TestClient(create_app(tmp_path))
    response = client.post("/api/v1/calculation-books", json={"bundle": minimal_bundle(), "options": {"include_pdf": False}})
    assert response.status_code == 200
    result = response.json()
    assert result["generation_status"] == "success"
    assert "output_dir" not in result
    assert client.get(f'/api/v1/runs/{result["run_id"]}').json() == result
    file = next(a for a in result["artifacts"] if a["name"].endswith(".docx"))
    download = client.get(file["url"])
    assert download.status_code == 200
    assert download.content[:2] == b"PK"
    assert client.get(f'/api/v1/runs/{result["run_id"]}/files/a9999').status_code == 404
    assert client.get('/api/v1/runs/invalid').status_code == 404


def test_openapi_contains_typed_bundle_and_expected_routes(tmp_path):
    spec = create_app(tmp_path).openapi()
    assert "DesignBundle" in spec["components"]["schemas"]
    assert "/api/v1/packages" in spec["paths"]
    assert "/api/v1/design-files" in spec["paths"]


def test_cli_validate_build_and_exit_codes_match_sdk(tmp_path):
    source = tmp_path / "input.json"
    source.write_text(json.dumps(minimal_bundle()), encoding="utf-8")
    def cli(*args):
        return subprocess.run([sys.executable, "-m", "steelmind_export", *map(str, args)], capture_output=True, text=True)
    validation = cli("validate", source)
    assert validation.returncode == 0, validation.stderr
    assert json.loads(validation.stdout)["upstream_check_summary"] == "INCOMPLETE"
    built = cli("build", source, "--kind", "calculation-book", "--no-pdf", "--output", tmp_path / "runs")
    assert built.returncode == 0, built.stderr
    assert json.loads(built.stdout)["generation_status"] == "success"
    source.write_text('{"schema_version": "unsupported"}', encoding="utf-8")
    assert cli("validate", source).returncode == 2
