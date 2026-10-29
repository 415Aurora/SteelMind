"""Single source of truth for SteelMind's locally bundled steel section data."""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).resolve().parent / "steel_sections.json"
WELDED_CSV_PATH = Path(__file__).resolve().parent / "tool_sources" / "截面库.csv"


def normalize_section_id(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().upper()
    text = text.replace("×", "X").replace("*", "X")
    return re.sub(r"[\s_\-]", "", text)


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    if not CATALOG_PATH.is_file():
        raise RuntimeError(f"本地型钢截面库缺失：{CATALOG_PATH}")
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        raise RuntimeError("本地型钢截面库为空或格式错误")
    hot_rolled_count = len(sections)
    welded = _load_welded_q235_sections()
    sections.extend(welded)
    metadata = payload.setdefault("metadata", {})
    metadata["hot_rolled_h_records"] = hot_rolled_count
    metadata["welded_q235_records"] = len(welded)
    metadata["records"] = len(sections)
    metadata["datasets"] = [
        {"catalog_type": "hot_rolled_h", "records": hot_rolled_count,
         "source_standard": "GB/T 11263-2024 附录A 表A.1"},
        {"catalog_type": "welded_q235", "records": len(welded),
         "source_csv": "backend/tool_sources/截面库.csv",
         "scope": "本地Q235焊接H型截面候选库；用于初选，不代表完整规范验算"},
    ]
    return payload


def _load_welded_q235_sections() -> list[dict[str, Any]]:
    if not WELDED_CSV_PATH.is_file():
        return []
    with WELDED_CSV_PATH.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"截面名称", "面积", "I2", "I3", "b2", "b3", "t2", "t3", "钢材牌号"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise RuntimeError(f"焊接Q235截面库字段不完整：{WELDED_CSV_PATH}")
        rows = []
        seen: set[str] = set()
        for source in reader:
            name = str(source["截面名称"]).strip()
            if not name or name in seen:
                raise RuntimeError(f"焊接Q235截面库存在空型号或重复型号：{name!r}")
            seen.add(name)
            h, b, tw, tf = (float(source[key]) for key in ("b2", "b3", "t2", "t3"))
            area = float(source["面积"])
            weak_i, strong_i = float(source["I2"]), float(source["I3"])
            if min(h, b, tw, tf, area, weak_i, strong_i) <= 0 or h <= 2 * tf or b <= tw:
                raise RuntimeError(f"截面 {name} 的几何或截面特性无效")
            rows.append({
                "id": f"WH-{name}",
                "designation": f"焊接Q235 {name.replace('x', '×')}",
                "series": "WH",
                "catalog_type": "welded_q235",
                "catalog_standard": "Q235焊接截面候选库",
                "catalog_table": "本地截面库.csv",
                "nominal_height_mm": h, "nominal_width_mm": b,
                "h_mm": h, "b_mm": b, "tw_mm": tw, "tf_mm": tf,
                "root_radius_mm": 0.0,
                "area_cm2": area / 100, "area_mm2": area,
                "mass_kg_m": area * 0.00785,
                "external_area_m2_m": (4 * b + 2 * h - 2 * tw) / 1000,
                "Ix_cm4": strong_i / 1e4, "Ix_mm4": strong_i,
                "Iy_cm4": weak_i / 1e4, "Iy_mm4": weak_i,
                "rx_cm": (strong_i / area) ** 0.5 / 10,
                "ry_cm": (weak_i / area) ** 0.5 / 10,
                "rx_mm": (strong_i / area) ** 0.5,
                "ry_mm": (weak_i / area) ** 0.5,
                "Wx_cm3": (strong_i / (h / 2)) / 1000,
                "Wx_mm3": strong_i / (h / 2),
                "Wy_cm3": (weak_i / (b / 2)) / 1000,
                "Wy_mm3": weak_i / (b / 2),
                "source_pdf_page": None,
                "source_material": str(source["钢材牌号"]).strip(),
                "aliases": ["WELDED-" + name],
            })
    return rows


@lru_cache(maxsize=1)
def _lookup_index() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for section in _catalog()["sections"]:
        for candidate in [section["id"], section["designation"], *section.get("aliases", [])]:
            key = normalize_section_id(candidate)
            previous = result.get(key)
            if previous and previous["id"] != section["id"]:
                raise RuntimeError(f"截面型号别名冲突：{candidate}")
            result[key] = section
    return result


def section_record(section_id: str) -> dict[str, Any] | None:
    """Return a copied catalog row by exact ID or explicitly registered alias."""
    row = _lookup_index().get(normalize_section_id(section_id))
    return dict(row) if row else None


def section_properties(section_id: str) -> dict[str, Any] | None:
    """Convert tabulated values to the units consumed by check/model tools."""
    row = section_record(section_id)
    if not row:
        return None
    h, b, tw, tf = (float(row[key]) for key in ("h_mm", "b_mm", "tw_mm", "tf_mm"))
    hw = h - 2 * tf
    area = float(row["area_mm2"])
    # Qx is a rectangular web/flange approximation; catalog area and inertias
    # remain the listed source values used by the solver/checker.
    sx = b * tf * (h - tf) / 2 + tw * hw**2 / 8
    return {
        "name": row["id"], "designation": row["designation"],
        "catalog_type": row.get("catalog_type", "hot_rolled_h"),
        "source_material": row.get("source_material"),
        "catalog_standard": row.get("catalog_standard", "GB/T 11263-2024"),
        "catalog_table": row.get("catalog_table", "附录A 表A.1"),
        "catalog_id": row["id"], "h": h, "b": b, "tw": tw, "t1": tf,
        "root_radius_mm": float(row["root_radius_mm"]), "h0": hw,
        "A": area, "Ix": float(row["Ix_mm4"]), "Wx": float(row["Wx_mm3"]),
        "ix": float(row["rx_mm"]), "Iy": float(row["Iy_mm4"]),
        "Wy": float(row["Wy_mm3"]), "iy": float(row["ry_mm"]), "Sx": sx,
        "mass_kg_m": float(row["mass_kg_m"]),
    }


def search_sections(
    query: str = "", *, series: str | None = None, min_height_mm: float | None = None,
    max_height_mm: float | None = None, min_area_cm2: float | None = None,
    max_area_cm2: float | None = None, catalog_type: str | None = None, top_k: int = 100,
) -> list[dict[str, Any]]:
    query_key = normalize_section_id(query)
    wanted_series = (series or "").strip().upper()
    limit = max(1, min(int(top_k), 1000))
    rows = []
    for section in _catalog()["sections"]:
        if wanted_series and section["series"].upper() != wanted_series:
            continue
        if catalog_type and section.get("catalog_type", "hot_rolled_h") != catalog_type:
            continue
        if min_height_mm is not None and section["nominal_height_mm"] < min_height_mm:
            continue
        if max_height_mm is not None and section["nominal_height_mm"] > max_height_mm:
            continue
        if min_area_cm2 is not None and section["area_cm2"] < min_area_cm2:
            continue
        if max_area_cm2 is not None and section["area_cm2"] > max_area_cm2:
            continue
        if query_key:
            haystack = normalize_section_id(" ".join([
                section["id"], section["designation"], *section.get("aliases", [])
            ]))
            if query_key not in haystack:
                continue
        rows.append(section)
    rows.sort(key=lambda item: (float(item["area_mm2"]), float(item["nominal_height_mm"]), item["id"]))
    return [dict(row) for row in rows[:limit]]


def catalog_info() -> dict[str, Any]:
    metadata = dict(_catalog()["metadata"])
    return {"available": True, **metadata}

