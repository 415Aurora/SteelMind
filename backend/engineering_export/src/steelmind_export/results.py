"""Transport types shared by the SDK, CLI and HTTP adapter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GenerationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_pdf: bool = True
    include_dwg: bool = False
    office_timeout_s: int = Field(default=120, ge=1, le=300)


class ExportOutcome(BaseModel):
    files: list[Path] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class Artifact(BaseModel):
    id: str
    name: str
    relative_path: str
    media_type: str
    bytes: int
    sha256: str
    url: str


class PublicGenerationResult(BaseModel):
    run_id: str
    created_at: datetime
    kind: Literal["calculation-book", "design-files", "package"]
    generation_status: Literal["success", "partial", "failed"]
    data_validation_status: Literal["valid", "invalid"]
    upstream_check_summary: Literal["PASS", "FAIL", "INCOMPLETE"]
    draft: bool
    draft_reasons: list[str]
    input_sha256: str
    normalized_sha256: str
    artifacts: list[Artifact] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class GenerationResult(PublicGenerationResult):
    output_dir: str


class BundleValidationError(ValueError):
    def __init__(self, report):
        self.report = report
        super().__init__("输入未通过校核；未生成成果。")


def public_result(result: GenerationResult) -> dict:
    """HTTP does not disclose absolute server paths."""
    data = result.model_dump(mode="json")
    data.pop("output_dir")
    return data
