"""Single source of truth for SteelMind's locally bundled steel section data."""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).resolve().parent / "steel_sections.json"


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
    return payload


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
    # GB/T 11263 gives rounded tabulated A/I/W/r values. Qx is a rectangular
    # web/flange approximation because the standard table does not include it;
    # the listed area and inertias remain the values used by the solver/checker.
    sx = b * tf * (h - tf) / 2 + tw * hw**2 / 8
    return {
        "name": row["id"], "designation": row["designation"],
        "catalog_standard": "GB/T 11263-2024", "catalog_table": "附录A 表A.1",
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
    max_area_cm2: float | None = None, top_k: int = 100,
) -> list[dict[str, Any]]:
    query_key = normalize_section_id(query)
    wanted_series = (series or "").strip().upper()
    limit = max(1, min(int(top_k), 500))
    rows = []
    for section in _catalog()["sections"]:
        if wanted_series and section["series"].upper() != wanted_series:
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

