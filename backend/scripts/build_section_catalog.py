"""Extract the normative GB/T 11263-2024 Appendix A.1 H-section table.

The source PDF is kept in Knowledge/01_规范与基础数据/03_型钢截面/.
Run from the repository root with the backend environment installed.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PDF = ROOT / "Knowledge" / "01_规范与基础数据" / "03_型钢截面" / "GB_T11263-2024_热轧H型钢和剖分T型钢.pdf"
SOURCE_CSV = ROOT / "Knowledge" / "01_规范与基础数据" / "03_型钢截面" / "常用H型钢截面参数.csv"
OUTPUT = ROOT / "backend" / "steel_sections.json"
HEADER = re.compile(r"H\s*(\d+(?:\.\d+)?)\s*×\s*(\d+(?:\.\d+)?)")
NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")


def extract_rows() -> list[dict]:
    if not SOURCE_PDF.is_file():
        raise FileNotFoundError(f"GB/T 11263-2024 source PDF is missing: {SOURCE_PDF}")
    records: list[dict] = []
    for pdf_page, page in enumerate(PdfReader(str(SOURCE_PDF)).pages, start=1):
        text = page.extract_text() or ""
        if "表 A.1" not in text and "H-型号" not in text:
            continue
        nominal: tuple[float, float] | None = None
        for raw_line in text.splitlines():
            line = raw_line.strip().replace("△", "").strip()
            header = HEADER.fullmatch(line)
            if header:
                nominal = (float(header.group(1)), float(header.group(2)))
                continue
            values = NUMBER.findall(line)
            # A.1 rows have 14 numbers: H, B, t1, t2, r, A, mass,
            # external area, Ix, Iy, ix, iy, Wx, Wy.
            if nominal is None or len(values) != 14:
                continue
            n = [float(value) for value in values]
            h_nom, b_nom = nominal
            h, b, tw, tf, radius, area, mass, external_area, ix, iy, rx, ry, wx, wy = n
            section_id = f"H{_num(h_nom)}x{_num(b_nom)}x{_num(tw)}x{_num(tf)}"
            records.append({
                "id": section_id,
                "designation": f"H{_num(h_nom)}×{_num(b_nom)}×{_num(tw)}×{_num(tf)}",
                "series": "H",
                "nominal_height_mm": h_nom,
                "nominal_width_mm": b_nom,
                "h_mm": h,
                "b_mm": b,
                "tw_mm": tw,
                "tf_mm": tf,
                "root_radius_mm": radius,
                "area_cm2": area,
                "area_mm2": round(area * 100, 6),
                "mass_kg_m": mass,
                "external_area_m2_m": external_area,
                "Ix_cm4": ix,
                "Ix_mm4": round(ix * 1.0e4, 6),
                "Iy_cm4": iy,
                "Iy_mm4": round(iy * 1.0e4, 6),
                "rx_cm": rx,
                "ry_cm": ry,
                "rx_mm": rx * 10,
                "ry_mm": ry * 10,
                "Wx_cm3": wx,
                "Wx_mm3": round(wx * 1.0e3, 6),
                "Wy_cm3": wy,
                "Wy_mm3": round(wy * 1.0e3, 6),
                "source_pdf_page": pdf_page,
                "aliases": [],
            })
    return records


def _num(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value).rstrip("0").rstrip(".")


def _add_legacy_aliases(records: list[dict]) -> None:
    if not SOURCE_CSV.is_file():
        return
    by_dimensions = {
        tuple(row[key] for key in ("h_mm", "b_mm", "tw_mm", "tf_mm")): row
        for row in records
    }
    with SOURCE_CSV.open("r", encoding="utf-8-sig", newline="") as stream:
        for old in csv.DictReader(stream):
            dims = tuple(float(old[key]) for key in ("h(mm)", "b(mm)", "tw(mm)", "tf(mm)"))
            row = by_dimensions.get(dims)
            if not row:
                continue
            designation = old["截面编号"]
            alias = designation.replace("×", "x")
            row["aliases"].append(alias)
            prefix = old["系列"]
            nominal_h = _num(float(row["nominal_height_mm"]))
            nominal_b = _num(float(row["nominal_width_mm"]))
            row["aliases"].append(f"{prefix}{nominal_h}x{nominal_b}")
            # Preserve existing HN/HW/HM shorthand names where these were the
            # profiles selected by the old SteelMind demo/model templates.
            legacy = {
                ("HN", 200, 100): "HN200x100",
                ("HN", 250, 125): "HN250x125",
                ("HN", 300, 150): "HN300x150",
                ("HN", 350, 175): "HN350x175",
                ("HN", 400, 200): "HN400x200",
                ("HW", 150, 150): "HW150x150",
                ("HW", 200, 200): "HW200x200",
                ("HW", 250, 250): "HW250x250",
                ("HW", 300, 300): "HW300x300",
                ("HW", 350, 350): "HW350x350",
                ("HW", 400, 400): "HW400x400",
                ("HM", 300, 200): "HM300x200",
                ("HM", 350, 250): "HM350x250",
                ("HM", 400, 300): "HM400x300",
                ("HM", 450, 300): "HM440x300",
            }.get((prefix, int(float(row["nominal_height_mm"])), int(float(row["nominal_width_mm"]))))
            if legacy:
                row["aliases"].append(legacy)
    for row in records:
        row["aliases"] = sorted(set(row["aliases"]))


def main() -> None:
    records = extract_rows()
    if len(records) < 400:
        raise RuntimeError(f"Only extracted {len(records)} rows from Appendix A.1; refusing to write an incomplete catalog")
    ids = [row["id"] for row in records]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Duplicate canonical section IDs were found")
    _add_legacy_aliases(records)
    payload = {
        "metadata": {
            "catalog_version": "1.0.0",
            "title": "SteelMind hot-rolled H-section catalog",
            "source_standard": "GB/T 11263-2024",
            "source_table": "Normative Appendix A, Table A.1",
            "source_pdf": "Knowledge/01_规范与基础数据/03_型钢截面/GB_T11263-2024_热轧H型钢和剖分T型钢.pdf",
            "source_csv": "Knowledge/01_规范与基础数据/03_型钢截面/常用H型钢截面参数.csv (legacy alias mapping only)",
            "units": {"dimensions": "mm", "area": "mm2", "inertia": "mm4", "section_modulus": "mm3", "mass": "kg/m"},
            "records": len(records),
            "scope": "Hot-rolled H sections from normative Appendix A.1. This v1 catalog does not include HK, T, I, channel, angle, or hollow sections.",
        },
        "sections": records,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} sections to {OUTPUT}")


if __name__ == "__main__":
    main()
