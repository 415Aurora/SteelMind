import sys
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from steelmind_export.runtime import ConversionError, convert_docx_to_pdf, resolve_font


def test_invalid_explicit_font_is_not_silently_replaced(monkeypatch):
    monkeypatch.setenv("STEELMIND_FONT", "/missing/font.ttf")
    with pytest.raises(FileNotFoundError, match="STEELMIND_FONT"):
        resolve_font()


def test_missing_converter_has_actionable_error(tmp_path):
    docx = tmp_path / "report.docx"
    docx.write_bytes(b"placeholder")
    with pytest.raises(ConversionError, match="LibreOffice"):
        convert_docx_to_pdf(docx, tmp_path, soffice_path="/missing/soffice")


def test_converter_timeout_is_not_a_success(tmp_path):
    import subprocess

    docx = tmp_path / "report.docx"
    docx.write_bytes(b"placeholder")
    with patch("steelmind_export.runtime.subprocess.run", side_effect=subprocess.TimeoutExpired("soffice", 1)):
        with pytest.raises(ConversionError, match="超时"):
            convert_docx_to_pdf(docx, tmp_path, soffice_path=sys.executable, timeout=1)


def test_converter_exit_zero_without_pdf_is_rejected(tmp_path):
    docx = tmp_path / "report.docx"
    docx.write_bytes(b"placeholder")
    with patch("steelmind_export.runtime.subprocess.run", return_value=subprocess.CompletedProcess([], 0, b"", b"")):
        with pytest.raises(ConversionError, match="PDF"):
            convert_docx_to_pdf(docx, tmp_path, soffice_path=sys.executable)


def test_stale_pdf_is_never_returned(tmp_path):
    docx = tmp_path / "report.docx"
    docx.write_bytes(b"placeholder")
    (tmp_path / "report.pdf").write_bytes(b"%PDF-stale")
    with pytest.raises(ConversionError, match="已存在"):
        convert_docx_to_pdf(docx, tmp_path, soffice_path=sys.executable)
