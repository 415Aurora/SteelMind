from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from statistics import mean
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from lxml import html as lxml_html
import numpy as np
from pypdf import PdfReader
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(
    os.environ.get("RAG_OUTPUT_DIR", str(ROOT / "07_机器可读规范库"))
).resolve()
TEXT_DIR = DATA_DIR / "全文文本"
DOCUMENTS_FILE = DATA_DIR / "documents.jsonl"
CHUNKS_FILE = DATA_DIR / "chunks.jsonl"
BUILD_STATE_FILE = DATA_DIR / "build_state.json"
STANDARD_DIR = ROOT / "01_规范与基础数据"

DEPS_DIR = Path(os.environ.get("RAG_DEPS_DIR", ROOT / "tmp" / "ocrdeps"))
if DEPS_DIR.exists():
    sys.path.insert(0, str(DEPS_DIR))

from rapidocr_onnxruntime import RapidOCR  # noqa: E402


PDF_DOCS = [
    {
        "standard_id": "GB50009-2012",
        "title": "建筑结构荷载规范",
        "version": "2012",
        "status": "现行",
        "path": STANDARD_DIR / "01_规范与依据" / "02_荷载与作用" / "GB50009-2012_建筑结构荷载规范.pdf",
        "source_url": "https://www.mohurd.gov.cn/file/old/2012/20120723/GB50009-2012%20%E5%BB%BA%E7%AD%91%E7%BB%93%E6%9E%84%E8%8D%B7%E8%BD%BD%E8%A7%84%E8%8C%83.pdf",
    },
    {
        "standard_id": "GB50017-2017",
        "title": "钢结构设计标准",
        "version": "2017",
        "status": "现行",
        "path": STANDARD_DIR / "01_规范与依据" / "01_结构设计与可靠性" / "GB50017-2017_钢结构设计标准.pdf",
        "source_url": "http://www.scboulton.com/uploads/upload/files/20240306/39c79d48c740d9400cbdfc19a6004d61.pdf",
    },
    {
        "standard_id": "GB55001-2021",
        "title": "工程结构通用规范",
        "version": "2021",
        "status": "现行",
        "path": STANDARD_DIR / "01_规范与依据" / "01_结构设计与可靠性" / "GB55001-2021_工程结构通用规范.pdf",
        "source_url": "https://www.mohurd.gov.cn/gongkai/zc/wjk/art/2024/art_17339_761192.html",
    },
    {
        "standard_id": "GB55006-2021",
        "title": "钢结构通用规范",
        "version": "2021",
        "status": "现行",
        "path": STANDARD_DIR / "01_规范与依据" / "01_结构设计与可靠性" / "GB55006-2021_钢结构通用规范.pdf",
        "source_url": "https://www.mohurd.gov.cn/gongkai/zc/wjk/art/2021/art_17339_761191.html",
    },
    {
        "standard_id": "GB50011-2010-2016",
        "title": "建筑抗震设计规范",
        "version": "2010（2016年版）",
        "status": "基础版本；2024版修订部分优先",
        "path": STANDARD_DIR / "01_规范与依据" / "03_抗震" / "GB50011-2010_2016版_建筑抗震设计规范.pdf",
        "source_url": "https://www.csdp.edu.cn/upload/attachment/201610/18/023005/%E5%BB%BA%E7%AD%91%E6%8A%97%E9%9C%87%E8%AE%BE%E8%AE%A1%E8%A7%84%E8%8C%83.pdf",
    },
    {
        "standard_id": "GB55002-2021",
        "title": "建筑与市政工程抗震通用规范",
        "version": "2021",
        "status": "现行",
        "path": STANDARD_DIR / "01_规范与依据" / "03_抗震" / "GB55002-2021_建筑与市政工程抗震通用规范.pdf",
        "source_url": "https://www.mohurd.gov.cn/gongkai/zc/wjk/art/2021/art_17339_761174.html",
    },
    {
        "standard_id": "GB-T50011-2010-2024-REV",
        "title": "建筑抗震设计标准（2024年局部修订条文）",
        "version": "GB/T 50011-2010（2024年版）",
        "status": "现行修订条文",
        "path": STANDARD_DIR / "01_规范与依据" / "03_抗震" / "GB_T50011-2010_2024局部修订_建筑抗震设计标准.pdf",
        "source_url": "https://www.mohurd.gov.cn/gongkai/zc/wjk/art/2024/art_17339_778179.html",
    },
    {
        "standard_id": "GB50205-2020",
        "title": "钢结构工程施工质量验收标准",
        "version": "2020",
        "status": "现行",
        "path": STANDARD_DIR / "01_规范与依据" / "04_施工验收与防火" / "GB50205-2020_钢结构工程施工质量验收标准.pdf",
        "source_url": "https://www.cnass.cn/upload/gjgfenhui/file/20230116/1673863571460192.pdf",
    },
    {
        "standard_id": "GB50661-2011",
        "title": "钢结构焊接规范",
        "version": "2011",
        "status": "现行",
        "path": STANDARD_DIR / "01_规范与依据" / "04_施工验收与防火" / "GB50661-2011_钢结构焊接规范.pdf",
        "source_url": "https://www.tongtest.cn/uploadfile/file/20201204/1607051104123700.pdf",
    },
    {
        "standard_id": "GB51249-2017",
        "title": "建筑钢结构防火技术规范",
        "version": "2017",
        "status": "现行",
        "path": STANDARD_DIR / "01_规范与依据" / "04_施工验收与防火" / "GB51249-2017_建筑钢结构防火技术规范.pdf",
        "source_url": "https://www.mohurd.gov.cn/file/old/2017/20170731/GB%2051249-2017%20%E5%BB%BA%E7%AD%91%E9%92%A2%E7%BB%93%E6%9E%84%E9%98%B2%E7%81%AB%E6%8A%80%E6%9C%AF%E8%A7%84%E8%8C%83.pdf",
    },
    {
        "standard_id": "GB-T1591-2018",
        "title": "低合金高强度结构钢",
        "version": "2018",
        "status": "现行",
        "path": STANDARD_DIR / "02_材料标准" / "GB_T1591-2018_低合金高强度结构钢.pdf",
        "source_url": "https://www.bsteel.com.cn/ywsj/upload/2020120810224394548644826.pdf",
    },
    {
        "standard_id": "GB-T700-2006",
        "title": "碳素结构钢",
        "version": "2006",
        "status": "现行",
        "path": STANDARD_DIR / "02_材料标准" / "GB_T700-2006_碳素结构钢.pdf",
        "source_url": "https://www.cnass.cn/upload/gjgfenhui/file/20230116/1673863753822158.pdf",
    },
    {
        "standard_id": "GB-T11263-2024",
        "title": "热轧H型钢和剖分T型钢",
        "version": "2024",
        "status": "现行",
        "path": STANDARD_DIR / "03_型钢截面" / "GB_T11263-2024_热轧H型钢和剖分T型钢.pdf",
        "source_url": "https://source.coyis.com/wp-content/uploads/2025/04/1744291525-GBT11263-2024-%E7%83%AD%E8%BD%A7H%E5%9E%8B%E9%92%A2%E5%92%8C%E5%89%96%E5%88%86T%E5%9E%8B%E9%92%A2.pdf",
    },
]

HTML_DOCS = [
    {
        "standard_id": "GB50068-2018",
        "title": "建筑结构可靠性设计统一标准",
        "version": "2018",
        "status": "现行",
        "path": STANDARD_DIR / "01_规范与依据" / "01_结构设计与可靠性" / "GB50068-2018_建筑结构可靠性设计统一标准_全文网页归档.html",
        "source_url": "https://gf.cabr-fire.com/list-1639.htm",
    }
]

MATERIALS = [
    ("Q235", "Q235", "≤16", 235, 370, 215, 125, 320),
    ("Q235", "Q235", ">16, ≤40", 225, 370, 205, 120, 320),
    ("Q235", "Q235", ">40, ≤100", 215, 370, 200, 115, 320),
    ("Q355", "Q345", "≤16", 345, 470, 305, 175, 400),
    ("Q355", "Q345", ">16, ≤40", 335, 470, 295, 170, 400),
    ("Q355", "Q345", ">40, ≤63", 325, 470, 290, 165, 400),
    ("Q355", "Q345", ">63, ≤80", 315, 470, 280, 160, 400),
    ("Q355", "Q345", ">80, ≤100", 305, 470, 270, 155, 400),
    ("Q390", "Q390", "≤16", 390, 490, 345, 200, 415),
    ("Q390", "Q390", ">16, ≤40", 370, 490, 330, 190, 415),
    ("Q390", "Q390", ">40, ≤63", 350, 490, 310, 180, 415),
    ("Q390", "Q390", ">63, ≤100", 330, 490, 295, 170, 415),
    ("Q420", "Q420", "≤16", 420, 520, 375, 215, 440),
    ("Q420", "Q420", ">16, ≤40", 400, 520, 355, 205, 440),
    ("Q420", "Q420", ">40, ≤63", 380, 520, 320, 185, 440),
    ("Q420", "Q420", ">63, ≤100", 360, 520, 305, 175, 440),
    ("Q460", "Q460", "≤16", 460, 550, 410, 235, 470),
    ("Q460", "Q460", ">16, ≤40", 440, 550, 390, 225, 470),
    ("Q460", "Q460", ">40, ≤63", 420, 550, 355, 205, 470),
    ("Q460", "Q460", ">63, ≤100", 400, 550, 340, 195, 470),
]


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_pdf_text(reader: PdfReader, page_no: int) -> str:
    try:
        return normalize_text(reader.pages[page_no - 1].extract_text() or "")
    except Exception:
        return ""


def has_usable_text(text: str) -> bool:
    chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
    return len(text) >= 100 and chinese >= 20


def render_pages(pdf_path: Path, first: int, last: int, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "pdftoppm",
        "-f",
        str(first),
        "-l",
        str(last),
        "-png",
        "-r",
        "160",
        str(pdf_path),
        str(output_dir / "page"),
    ]
    subprocess.run(command, check=True, capture_output=True)


def render_one_page(pdf_path: Path, page_no: int, output_base: Path) -> Path:
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(page_no),
            "-l",
            str(page_no),
            "-singlefile",
            "-png",
            "-r",
            "160",
            str(pdf_path),
            str(output_base),
        ],
        check=True,
        capture_output=True,
    )
    return output_base.with_suffix(".png")


def ocr_image(engine: RapidOCR, image_source) -> tuple[str, float | None]:
    if isinstance(image_source, Image.Image):
        image_source = np.asarray(image_source.convert("RGB"))
    result, _ = engine(image_source)
    if not result:
        return "", None
    lines = [row[1].strip() for row in result if len(row) >= 3 and row[1].strip()]
    scores = [float(row[2]) for row in result if len(row) >= 3 and row[2] is not None]
    return normalize_text("\n".join(lines)), mean(scores) if scores else None


_WORKER_ENGINE: RapidOCR | None = None


def ocr_path_worker(image_path: str) -> tuple[str, float | None]:
    global _WORKER_ENGINE
    if _WORKER_ENGINE is None:
        _WORKER_ENGINE = RapidOCR(
            intra_op_num_threads=1,
            print_verbose=False,
        )
    return ocr_image(_WORKER_ENGINE, image_path)


def chunk_text(text: str, max_chars: int = 1100, overlap: int = 140) -> list[str]:
    text = normalize_text(text)
    if len(text) <= max_chars:
        return [text] if text else []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paragraphs) == 1:
        paragraphs = [p.strip() for p in text.splitlines() if p.strip()]
    chunks: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            start = 0
            while start < len(paragraph):
                chunks.append(paragraph[start : start + max_chars])
                start += max_chars - overlap
            continue
        candidate = f"{buffer}\n\n{paragraph}".strip()
        if len(candidate) <= max_chars:
            buffer = candidate
        else:
            if buffer:
                chunks.append(buffer)
            buffer = paragraph
    if buffer:
        chunks.append(buffer)
    return chunks


def detect_clause_no(text: str) -> str | None:
    match = re.search(r"(?m)^\s*(\d{1,2}(?:\.\d{1,2}){1,3})\s+", text)
    return match.group(1) if match else None


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_pdf_document(
    engine: RapidOCR,
    doc: dict,
    workers: int,
) -> tuple[list[dict], list[dict]]:
    pdf_path = doc["path"]
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    reader = PdfReader(str(pdf_path))
    page_texts = [extract_pdf_text(reader, index + 1) for index in range(len(reader.pages))]
    usable = [has_usable_text(text) for text in page_texts]
    scanned_ratio = 1 - (sum(usable) / len(usable) if usable else 1)
    page_records: list[dict] = []
    chunk_records: list[dict] = []
    ocr_results: dict[int, tuple[str, float | None]] = {}
    temporary_dir = Path(tempfile.mkdtemp(prefix="steelmind_ocr_"))
    bulk_rendered = False

    if scanned_ratio >= 0.6:
        render_pages(pdf_path, 1, len(reader.pages), temporary_dir)
        bulk_rendered = True

    try:
        ocr_tasks: list[tuple[int, Path]] = []
        for page_no, text in enumerate(page_texts, start=1):
            if usable[page_no - 1]:
                continue
            candidates = sorted(temporary_dir.glob(f"page-{page_no:03d}.png"))
            if not candidates:
                candidates = sorted(temporary_dir.glob(f"page-{page_no}.png"))
            if bulk_rendered and candidates:
                image_path = candidates[0]
            else:
                image_path = render_one_page(
                    pdf_path, page_no, temporary_dir / f"single-{page_no:04d}"
                )
            ocr_tasks.append((page_no, image_path))

        if ocr_tasks:
            if workers <= 1:
                for completed, (page_no, image_path) in enumerate(ocr_tasks, start=1):
                    ocr_results[page_no] = ocr_path_worker(str(image_path))
                    if completed % 10 == 0 or completed == len(ocr_tasks):
                        print(
                            f"{doc['standard_id']}: OCR {completed}/{len(ocr_tasks)}",
                            flush=True,
                        )
            else:
                with ProcessPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(ocr_path_worker, str(image_path)): page_no
                        for page_no, image_path in ocr_tasks
                    }
                    for completed, future in enumerate(as_completed(futures), start=1):
                        page_no = futures[future]
                        ocr_results[page_no] = future.result()
                        if completed % 10 == 0 or completed == len(ocr_tasks):
                            print(
                                f"{doc['standard_id']}: OCR {completed}/{len(ocr_tasks)}",
                                flush=True,
                            )

        for page_no, text in enumerate(page_texts, start=1):
            source_type = "pdf_text"
            confidence = None
            if not usable[page_no - 1]:
                source_type = "pdf_ocr"
                text, confidence = ocr_results.get(page_no, ("", None))
            text = normalize_text(text)
            record_id = f"{doc['standard_id']}__p{page_no:04d}"
            page_record = {
                "id": record_id,
                "standard_id": doc["standard_id"],
                "title": doc["title"],
                "version": doc["version"],
                "status": doc["status"],
                "page_no": page_no,
                "source_file": str(pdf_path.relative_to(ROOT)),
                "source_url": doc["source_url"],
                "source_type": source_type,
                "ocr_confidence": round(confidence, 4) if confidence is not None else None,
                "text": text,
            }
            page_records.append(page_record)
            for index, chunk in enumerate(chunk_text(text), start=1):
                chunk_records.append(
                    {
                        **{key: page_record[key] for key in (
                            "standard_id",
                            "title",
                            "version",
                            "status",
                            "page_no",
                            "source_file",
                            "source_url",
                            "source_type",
                        )},
                        "id": f"{record_id}__c{index:02d}",
                        "clause_no": detect_clause_no(chunk),
                        "text": chunk,
                    }
                )
            if page_no % 20 == 0 or page_no == len(reader.pages):
                print(
                    f"{doc['standard_id']}: {page_no}/{len(reader.pages)} pages",
                    flush=True,
                )
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)
    return page_records, chunk_records


def fetch_image(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 SteelMind-OCR"})
    with urlopen(request, timeout=30) as response:
        return response.read()


def build_html_document(
    engine: RapidOCR,
    doc: dict,
    workers: int,
) -> tuple[list[dict], list[dict]]:
    source_html = doc["path"]
    tree = lxml_html.fromstring(source_html.read_text(encoding="utf-8"))
    base_url = tree.xpath("//base/@href")
    base_url = base_url[0] if base_url else doc["source_url"]
    sections = tree.xpath("//section[contains(@class,'clause')]")
    records: list[dict] = []
    chunks: list[dict] = []
    temporary_dir = Path(tempfile.mkdtemp(prefix="steelmind_web_ocr_"))

    try:
        section_data = []
        image_tasks = []
        for index, section in enumerate(sections, start=1):
            heading_nodes = section.xpath("./h2")
            heading = (
                " ".join(heading_nodes[0].text_content().split())
                if heading_nodes
                else f"第 {index} 节"
            )
            text = normalize_text(" ".join(section.text_content().split()))
            image_info = []
            for image_no, image in enumerate(section.xpath(".//img"), start=1):
                src = image.get("src")
                if not src:
                    continue
                image_path = temporary_dir / f"section-{index:04d}-image-{image_no:03d}.png"
                error = None
                try:
                    image_bytes = fetch_image(urljoin(base_url, src))
                    image_obj = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                    image_obj.save(image_path)
                except Exception as exc:  # noqa: BLE001
                    error = str(exc)
                image_info.append((image_no, image_path, error))
                if image_path.exists():
                    image_tasks.append((index, image_no, image_path))
            section_data.append((index, heading, text, image_info))

        image_ocr = {}
        if image_tasks:
            if workers <= 1:
                for completed, (section_no, image_no, image_path) in enumerate(
                    image_tasks, start=1
                ):
                    image_ocr[(section_no, image_no)] = ocr_path_worker(str(image_path))
                    if completed % 10 == 0 or completed == len(image_tasks):
                        print(
                            f"{doc['standard_id']}: image OCR {completed}/{len(image_tasks)}",
                            flush=True,
                        )
            else:
                with ProcessPoolExecutor(max_workers=workers) as executor:
                    futures = {
                        executor.submit(ocr_path_worker, str(image_path)): (
                            section_no,
                            image_no,
                        )
                        for section_no, image_no, image_path in image_tasks
                    }
                    for completed, future in enumerate(as_completed(futures), start=1):
                        key = futures[future]
                        image_ocr[key] = future.result()
                        if completed % 10 == 0 or completed == len(image_tasks):
                            print(
                                f"{doc['standard_id']}: image OCR {completed}/{len(image_tasks)}",
                                flush=True,
                            )

        for index, heading, text, image_info in section_data:
            ocr_fragments = []
            for image_no, image_path, error in image_info:
                if error:
                    ocr_fragments.append(f"[图片 {image_no} 下载失败：{error}]")
                    continue
                ocr_text, confidence = image_ocr.get(
                    (index, image_no), ("", None)
                )
                if ocr_text:
                    ocr_fragments.append(
                        f"[表格或公式图片 {image_no}，OCR置信度 {confidence or 0:.3f}]\n{ocr_text}"
                    )
            combined_text = normalize_text("\n\n".join([text, *ocr_fragments]))
            record_id = f"{doc['standard_id']}__s{index:04d}"
            clause_no = detect_clause_no(heading)
            records.append(
                {
                    "id": record_id,
                    "standard_id": doc["standard_id"],
                    "title": doc["title"],
                    "version": doc["version"],
                    "status": doc["status"],
                    "section_no": index,
                    "heading": heading,
                    "clause_no": clause_no,
                    "source_file": str(source_html.relative_to(ROOT)),
                    "source_url": doc["source_url"],
                    "source_type": "html_text_image_ocr",
                    "text": combined_text,
                }
            )
            for chunk_index, chunk in enumerate(chunk_text(combined_text), start=1):
                chunks.append(
                    {
                        "id": f"{record_id}__c{chunk_index:02d}",
                        "standard_id": doc["standard_id"],
                        "title": doc["title"],
                        "version": doc["version"],
                        "status": doc["status"],
                        "page_no": None,
                        "section_no": index,
                        "heading": heading,
                        "clause_no": clause_no,
                        "source_file": str(source_html.relative_to(ROOT)),
                        "source_url": doc["source_url"],
                        "source_type": "html_text_image_ocr",
                        "text": chunk,
                    }
                )
            if index % 10 == 0 or index == len(sections):
                print(f"{doc['standard_id']}: {index}/{len(sections)} sections", flush=True)
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)
    return records, chunks


def build_structured_data() -> None:
    output_dir = DATA_DIR / "structured"
    output_dir.mkdir(parents=True, exist_ok=True)
    materials = []
    for grade, design_grade, thickness, fy, fu, f, fv, fce in MATERIALS:
        materials.append(
            {
                "grade": grade,
                "design_table_grade": design_grade,
                "thickness_range_mm": thickness,
                "fy_mpa": fy,
                "fu_mpa": fu,
                "f_mpa": f,
                "fv_mpa": fv,
                "fce_mpa": fce,
                "E_mpa": 206000,
                "G_mpa": 79000,
                "density_kg_m3": 7850,
                "source": "GB 50017-2017 表4.4.1",
                "review_status": "需复核" if grade == "Q355" else "可直接采用",
            }
        )
    (output_dir / "materials.json").write_text(
        json.dumps(materials, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    import csv

    csv_path = STANDARD_DIR / "03_型钢截面" / "常用H型钢截面参数.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as stream:
        sections = list(csv.DictReader(stream))
    (output_dir / "sections.json").write_text(
        json.dumps(sections, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["all", "pdf", "html"], default="all")
    parser.add_argument("--only", default="", help="Comma-separated standard_id filter")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    only = {item.strip() for item in args.only.split(",") if item.strip()}

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    engine = RapidOCR(
        intra_op_num_threads=1,
        print_verbose=False,
    )
    document_records: list[dict] = []
    chunk_records: list[dict] = []

    if args.mode in {"all", "pdf"}:
        for doc in PDF_DOCS:
            if only and doc["standard_id"] not in only:
                continue
            print(f"START {doc['standard_id']}", flush=True)
            pages, chunks = build_pdf_document(engine, doc, args.workers)
            document_records.extend(pages)
            chunk_records.extend(chunks)
            markdown = [
                f"# {doc['standard_id']} {doc['title']}",
                "",
                f"- 版本：{doc['version']}",
                f"- 状态：{doc['status']}",
                f"- 来源：{doc['source_url']}",
                f"- 原始文件：{doc['path'].relative_to(ROOT)}",
                "",
            ]
            for page in pages:
                markdown.append(
                    f"\n## 第 {page['page_no']} 页 `{page['source_type']}`\n\n{page['text']}"
                )
            (TEXT_DIR / f"{doc['standard_id']}_全文.md").write_text(
                "\n".join(markdown).strip() + "\n",
                encoding="utf-8",
            )

    if args.mode in {"all", "html"}:
        for doc in HTML_DOCS:
            if only and doc["standard_id"] not in only:
                continue
            print(f"START {doc['standard_id']}", flush=True)
            sections, chunks = build_html_document(engine, doc, args.workers)
            document_records.extend(sections)
            chunk_records.extend(chunks)
            markdown = [
                f"# {doc['standard_id']} {doc['title']}",
                "",
                f"- 版本：{doc['version']}",
                f"- 状态：{doc['status']}",
                f"- 来源：{doc['source_url']}",
                f"- 原始文件：{doc['path'].relative_to(ROOT)}",
                "",
            ]
            for row in sections:
                markdown.append(
                    f"\n## {row['heading']}\n\n{row['text']}"
                )
            (TEXT_DIR / f"{doc['standard_id']}_全文.md").write_text(
                "\n".join(markdown).strip() + "\n",
                encoding="utf-8",
            )

    build_structured_data()
    write_jsonl(DOCUMENTS_FILE, document_records)
    write_jsonl(CHUNKS_FILE, chunk_records)
    manifest = {
        "built_at": date.today().isoformat(),
        "source_kind": "PDF text with selective OCR; HTML text with image OCR",
        "documents": len(document_records),
        "chunks": len(chunk_records),
        "pdf_documents": len([d for d in PDF_DOCS if not only or d["standard_id"] in only])
        if args.mode in {"all", "pdf"}
        else 0,
        "html_documents": len([d for d in HTML_DOCS if not only or d["standard_id"] in only])
        if args.mode in {"all", "html"}
        else 0,
        "standards": sorted({row["standard_id"] for row in document_records}),
    }
    BUILD_STATE_FILE.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
