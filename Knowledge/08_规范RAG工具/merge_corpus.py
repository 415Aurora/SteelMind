from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JOBS = ROOT / "tmp" / "corpusjobs"
DEFAULT_OUTPUT = ROOT / "07_机器可读规范库"
SECTION_SOURCE = ROOT / "01_规范与基础数据" / "03_型钢截面" / "常用H型钢截面参数.csv"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", type=Path, default=DEFAULT_JOBS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "全文文本").mkdir(parents=True, exist_ok=True)
    (args.output / "structured").mkdir(parents=True, exist_ok=True)

    all_documents = {}
    all_chunks = {}
    for job_dir in sorted(path for path in args.jobs.iterdir() if path.is_dir()):
        for row in read_jsonl(job_dir / "documents.jsonl"):
            all_documents[row["id"]] = row
        for row in read_jsonl(job_dir / "chunks.jsonl"):
            all_chunks[row["id"]] = row
        text_dir = job_dir / "全文文本"
        if text_dir.exists():
            for text_path in text_dir.glob("*.md"):
                shutil.copy2(text_path, args.output / "全文文本" / text_path.name)
        structured_dir = job_dir / "structured"
        if structured_dir.exists():
            for structured_path in structured_dir.glob("*.json"):
                shutil.copy2(
                    structured_path,
                    args.output / "structured" / structured_path.name,
                )

    if SECTION_SOURCE.exists():
        with SECTION_SOURCE.open("r", encoding="utf-8", newline="") as stream:
            raw_sections = list(csv.DictReader(stream))
        (args.output / "structured" / "sections.json").write_text(
            json.dumps(raw_sections, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    documents = sorted(
        all_documents.values(),
        key=lambda row: (row["standard_id"], row.get("page_no") or 0, row.get("section_no") or 0),
    )
    chunks = sorted(all_chunks.values(), key=lambda row: row["id"])
    with (args.output / "documents.jsonl").open("w", encoding="utf-8") as stream:
        for row in documents:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (args.output / "chunks.jsonl").open("w", encoding="utf-8") as stream:
        for row in chunks:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    with (args.output / "OCR质量清单.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "standard_id",
                "page_no",
                "section_no",
                "source_type",
                "ocr_confidence",
                "text_length",
                "source_file",
            ]
        )
        for row in documents:
            writer.writerow(
                [
                    row["standard_id"],
                    row.get("page_no", ""),
                    row.get("section_no", ""),
                    row.get("source_type", ""),
                    row.get("ocr_confidence", ""),
                    len(row.get("text", "")),
                    row.get("source_file", ""),
                ]
            )

    manifest = {
        "built_at": date.today().isoformat(),
        "documents": len(documents),
        "chunks": len(chunks),
        "standards": sorted({row["standard_id"] for row in documents}),
        "ocr_pages": sum(
            1 for row in documents if row.get("source_type") in {"pdf_ocr", "html_text_image_ocr"}
        ),
    }
    (args.output / "build_state.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
