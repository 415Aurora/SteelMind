import pytest

pytest.importorskip("langchain_core")

from steelmind_export.adapters import make_langchain_tools
from steelmind_export.examples import minimal_bundle


def test_langchain_tool_preserves_draft_and_input_hash(tmp_path):
    book, drawing = make_langchain_tools(tmp_path)
    assert book.name == "calculation_book_generate"
    assert drawing.name == "design_files_generate"
    result = book.invoke({"bundle": minimal_bundle(), "options": {"include_pdf": False}})
    assert result["generation_status"] == "success"
    assert result["draft"]
    assert result["upstream_check_summary"] == "INCOMPLETE"
    assert "output_dir" not in result
    assert any(a["name"].endswith(".docx") for a in result["artifacts"])
