"""Real converter isolation test; skipped only on hosts without LibreOffice."""
from concurrent.futures import ThreadPoolExecutor

from docx import Document
from pypdf import PdfReader
import pytest

from steelmind_export.runtime import ConversionError, convert_docx_to_pdf, find_soffice


def test_two_real_office_profiles_produce_distinct_pdfs(tmp_path):
    try:
        find_soffice()
    except ConversionError:
        pytest.skip("LibreOffice not installed; see Docker image for complete export environment")
    def convert(number):
        folder = tmp_path / str(number)
        folder.mkdir()
        source = folder / "report.docx"
        doc = Document()
        doc.add_paragraph(f"Concurrent report {number}")
        doc.save(source)
        return convert_docx_to_pdf(source, folder)
    with ThreadPoolExecutor(max_workers=2) as pool:
        files = list(pool.map(convert, [1, 2]))
    assert files[0] != files[1]
    assert "Concurrent report 1" in PdfReader(files[0]).pages[0].extract_text()
    assert "Concurrent report 2" in PdfReader(files[1]).pages[0].extract_text()
