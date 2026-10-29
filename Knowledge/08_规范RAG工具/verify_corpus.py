from __future__ import annotations

import json
import sqlite3
import statistics
from pathlib import Path

from rag_engine import (
    get_clause,
    list_standards,
    lookup_material,
    lookup_section,
    search_standards,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "07_机器可读规范库"


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    documents = read_jsonl(DATA_DIR / "documents.jsonl")
    chunks = read_jsonl(DATA_DIR / "chunks.jsonl")
    document_ids = {row["id"] for row in documents}
    chunk_ids = {row["id"] for row in chunks}
    required = {"id", "standard_id", "title", "source_file", "source_url", "text"}

    connection = sqlite3.connect(DATA_DIR / "standards.db")
    db_count = connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    fts_count = connection.execute(
        "SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH ?",
        ("q355",),
    ).fetchone()[0]
    connection.close()

    ocr_scores = [
        row["ocr_confidence"]
        for row in documents
        if row.get("ocr_confidence") is not None
    ]
    short_records = [
        {
            "standard_id": row["standard_id"],
            "page_no": row.get("page_no"),
            "section_no": row.get("section_no"),
        }
        for row in documents
        if len(row.get("text", "").strip()) < 10
    ]

    search_results = search_standards("压弯构件平面外稳定", top_k=3)
    clause_results = get_clause("GB50017-2017", "8.2.1")
    material_results = lookup_material("Q355", 13)
    section_results = lookup_section("HN400x200x8x13")

    checks = {
        "document_ids_unique": len(document_ids) == len(documents),
        "chunk_ids_unique": len(chunk_ids) == len(chunks),
        "required_fields_present": all(required.issubset(row.keys()) for row in documents),
        "sqlite_integrity_ok": integrity == "ok",
        "sqlite_count_matches_jsonl": db_count == len(chunks),
        "fts_q355_has_results": fts_count > 0,
        "search_returns_gb50017": any(
            row["standard_id"] == "GB50017-2017" for row in search_results
        ),
        "clause_lookup_returns_8_2_1": any(
            "8.2.1" in (row.get("text") or "") for row in clause_results
        ),
        "material_lookup_q355_ok": bool(material_results)
        and material_results[0]["f_mpa"] == 305,
        "section_lookup_hn400_ok": bool(section_results)
        and section_results[0]["Ix(cm4)"] == "23500",
    }

    report = {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "documents": len(documents),
        "chunks": len(chunks),
        "standards": len(list_standards()),
        "source_methods": {
            method: sum(1 for row in documents if row.get("source_type") == method)
            for method in sorted({row.get("source_type") for row in documents})
        },
        "ocr_pages": sum(1 for row in documents if row.get("source_type") == "pdf_ocr"),
        "ocr_scored_pages": len(ocr_scores),
        "ocr_confidence_average": round(statistics.mean(ocr_scores), 4)
        if ocr_scores
        else None,
        "ocr_confidence_min": round(min(ocr_scores), 4) if ocr_scores else None,
        "short_text_records": short_records,
        "smoke_tests": {
            "search_top_standard": search_results[0]["standard_id"]
            if search_results
            else None,
            "clause_top_page": clause_results[0].get("page_no")
            if clause_results
            else None,
            "material_f_mpa": material_results[0].get("f_mpa")
            if material_results
            else None,
            "section_Ix_cm4": section_results[0].get("Ix(cm4)")
            if section_results
            else None,
        },
    }
    (DATA_DIR / "质量核验结果.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
