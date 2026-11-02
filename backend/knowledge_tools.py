"""SteelMind adapters for the local standards RAG corpus (Knowledge/07 and 08)."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAG_TOOL_DIR = Path(
    os.getenv("STEEL_RAG_TOOL_DIR", str(PROJECT_ROOT / "Knowledge" / "08_规范RAG工具"))
).expanduser().resolve()
ENGINE_PATH = RAG_TOOL_DIR / "rag_engine.py"
_spec = importlib.util.spec_from_file_location("steelmind_local_rag_engine", ENGINE_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f"无法加载规范 RAG 引擎：{ENGINE_PATH}")
rag_engine = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = rag_engine
_spec.loader.exec_module(rag_engine)


def _normalize_source_dir(value: str) -> str:
    return str(value or "").replace("\\", "/").strip("/")


def _source_matches(hit: dict[str, Any], selected_dirs: set[str]) -> bool:
    if not selected_dirs:
        return True
    source_path = _normalize_source_dir(str(hit.get("source_file", "")))
    source_dir = source_path.rsplit("/", 1)[0] if "/" in source_path else ""
    return any(
        source_dir == directory or source_dir.startswith(directory + "/")
        for directory in selected_dirs
    )


def _row_to_hit(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _expand_page_siblings(
    candidates: list[dict[str, Any]],
    top_k: int,
    selected_dirs: set[str],
) -> list[dict[str, Any]]:
    """Attach all chunks from the most relevant pages.

    PDF pages are often split into several chunks, for example GB 50011 page 108
    contains A.0.1 and A.0.2 in separate chunks.  Keeping one chunk without its
    page sibling can make the model believe that a row is absent.
    """
    ordered = sorted(candidates, key=lambda item: item.get("score", 0), reverse=True)
    if not ordered:
        return []
    hits = {
        str(item.get("id") or f"{item.get('standard_id')}:{item.get('page_no')}:{item.get('clause_no')}"): item
        for item in ordered
    }
    page_keys: list[tuple[str, int]] = []
    parent_ids: set[str] = set()
    for item in ordered[: min(5, len(ordered))]:
        page_no = item.get("page_no")
        standard_id = str(item.get("standard_id") or "")
        if page_no is None or not standard_id:
            continue
        if item.get("id"):
            parent_ids.add(str(item["id"]))
        key = (standard_id, int(page_no))
        if key not in page_keys:
            page_keys.append(key)
    if not page_keys:
        return ordered[:top_k]

    connection, _ = rag_engine.load_index()
    connection.row_factory = sqlite3.Row
    for standard_id, page_no in page_keys:
        parent_score = max(
            float(item.get("score", 0))
            for item in ordered
            if str(item.get("standard_id") or "") == standard_id
            and item.get("page_no") == page_no
        )
        page_rows = connection.execute(
            "SELECT * FROM chunks WHERE standard_id=? AND page_no=? "
            "ORDER BY row_id",
            (standard_id, page_no),
        ).fetchall()
        for index, row in enumerate(page_rows):
            item = _row_to_hit(row)
            key = str(item.get("id"))
            if not _source_matches(item, selected_dirs):
                continue
            sibling_score = round(max(0.0, parent_score - 0.000001 * (index + 1)), 6)
            if key in hits:
                # The sibling may already be a low-ranked candidate. Promote it
                # to its relevant page's score so it is not lost at the top-k cut.
                hits[key]["score"] = max(float(hits[key].get("score", 0)), sibling_score)
                if key not in parent_ids:
                    hits[key]["expanded_from_page"] = True
                continue
            item["score"] = sibling_score
            item["expanded_from_page"] = True
            if len(str(item.get("text") or "")) > 2200:
                item["text"] = str(item["text"])[:2200]
            hits[key] = item
    return sorted(hits.values(), key=lambda item: item.get("score", 0), reverse=True)[:top_k]


def _extract_table_no(query: str) -> str:
    match = re.search(
        r"(?:表|表格)\s*([A-Z]?\.?\d+(?:\.\d+)*(?:-\d+)?)",
        unicodedata.normalize("NFKC", query or ""),
        flags=re.IGNORECASE,
    )
    return match.group(1).upper() if match else ""


def _expand_adjacent_table_pages(
    candidates: list[dict[str, Any]],
    query: str,
    top_k: int,
    selected_dirs: set[str],
) -> list[dict[str, Any]]:
    """Add the immediately preceding/following page for explicit table queries.

    Table headers and continuation rows are frequently split across adjacent
    pages (for example GB 50017 tables 4.4.5/4.4.6).  Same-page expansion alone
    cannot reconnect those blocks.
    """
    if not _extract_table_no(query) or not candidates:
        return candidates[:top_k]
    ordered = sorted(candidates, key=lambda item: item.get("score", 0), reverse=True)
    seed_pages: list[tuple[str, int, float]] = []
    for item in ordered[:3]:
        page_no = item.get("page_no")
        standard_id = str(item.get("standard_id") or "")
        if page_no is None or not standard_id:
            continue
        key = (standard_id, int(page_no))
        if any(existing[0] == key[0] and existing[1] == key[1] for existing in seed_pages):
            continue
        seed_pages.append((standard_id, int(page_no), float(item.get("score", 0))))
    if not seed_pages:
        return ordered[:top_k]

    hits = {
        str(item.get("id") or f"{item.get('standard_id')}:{item.get('page_no')}"): item
        for item in ordered
    }
    connection, _ = rag_engine.load_index()
    connection.row_factory = sqlite3.Row
    for standard_id, page_no, parent_score in seed_pages:
        for adjacent_page in (page_no - 1, page_no + 1):
            if adjacent_page < 1:
                continue
            rows = connection.execute(
                "SELECT * FROM chunks WHERE standard_id=? AND page_no=? "
                "ORDER BY row_id",
                (standard_id, adjacent_page),
            ).fetchall()
            for index, row in enumerate(rows):
                item = _row_to_hit(row)
                if not _source_matches(item, selected_dirs):
                    continue
                key = str(item.get("id"))
                score = round(max(0.0, parent_score - 0.05 - index * 0.000001), 6)
                if key in hits:
                    hits[key]["score"] = max(float(hits[key].get("score", 0)), score)
                else:
                    item["score"] = score
                    item["expanded_from_table"] = True
                    if len(str(item.get("text") or "")) > 2200:
                        item["text"] = str(item["text"])[:2200]
                    hits[key] = item
    return sorted(hits.values(), key=lambda item: item.get("score", 0), reverse=True)[:top_k]


def _selected_search(query: str, top_k: int = 5, standard_ids: list[str] | None = None,
                     source_dirs: list[str] | None = None) -> list[dict[str, Any]]:
    top_k = max(1, min(int(top_k), 20))
    selected = [str(item).strip() for item in (standard_ids or []) if str(item).strip()]
    selected_dirs = {
        _normalize_source_dir(item)
        for item in (source_dirs or [])
        if str(item).strip()
    }
    directory_standards = _directory_standard_map() if selected_dirs else {}
    all_standards = {
        standard_id
        for standard_ids_in_dir in directory_standards.values()
        for standard_id in standard_ids_in_dir
    }
    selected_set = set(selected)
    # The browser selects every standard by default. Treat that as "no standard
    # filter" so the engine performs one mixed search instead of fourteen serial
    # searches, which was a common source of the front-end 8 second timeout.
    if selected_set and all_standards and all_standards.issubset(selected_set):
        selected = []

    narrow_by_dirs = bool(selected_dirs) and not (
        directory_standards and set(directory_standards).issubset(selected_dirs)
    )
    if narrow_by_dirs:
        allowed_standards = {
            standard_id for directory, standard_ids_in_dir in directory_standards.items()
            if any(directory == selected_dir or directory.startswith(selected_dir + "/")
                   for selected_dir in selected_dirs)
            for standard_id in standard_ids_in_dir
        }
        selected = sorted(allowed_standards if not selected else set(selected) & allowed_standards)
        if not selected:
            return []
    hits: dict[str, dict[str, Any]] = {}
    if not selected:
        candidates = rag_engine.search_standards(query, top_k=top_k)
    else:
        # The RAG engine supports a per-standard filter; resolve selected
        # directories to indexed standards, then enforce exact source paths.
        each_k = min(20, max(top_k, (top_k + len(selected) - 1) // len(selected) + 2))
        candidates = []
        for standard_id in selected:
            candidates.extend(rag_engine.search_standards(query, top_k=each_k, standard_id=standard_id))
    for hit in candidates:
        if not _source_matches(hit, selected_dirs):
            continue
        standard_id = str(hit.get("standard_id", ""))
        if not selected or standard_id in selected:
            hits[str(hit.get("id") or f"{standard_id}:{hit.get('page_no')}:{hit.get('clause_no')}")] = hit
    selected_hits = _expand_page_siblings(list(hits.values()), top_k, selected_dirs)
    return _expand_adjacent_table_pages(selected_hits, query, top_k, selected_dirs)


def _directory_standard_map() -> dict[str, set[str]]:
    connection, _ = rag_engine.load_index()
    result: dict[str, set[str]] = {}
    for source_file, standard_id in connection.execute("SELECT source_file, standard_id FROM chunks"):
        path = str(source_file or "").replace("\\", "/")
        directory = path.rsplit("/", 1)[0] if "/" in path else "未分类"
        result.setdefault(directory, set()).add(str(standard_id))
    return result


def _compact(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _region_aliases(region: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", str(region or "")).strip()
    aliases: list[str] = []
    if not normalized:
        return aliases

    def add(value: str) -> None:
        value = value.strip()
        if len(_compact(value)) >= 2 and value not in aliases:
            aliases.append(value)

    add(normalized)
    for match in re.finditer(
        r"[\u4e00-\u9fff]{2,}?(?:特别行政区|自治区|自治州|地区|省|市|盟|县|区|旗)",
        normalized,
    ):
        term = match.group(0)
        add(term)
        base = re.sub(
            r"(?:特别行政区|自治区|自治州|地区|省|市|盟|县|区|旗)$",
            "",
            term,
        )
        add(base)
    # Prefer the shorter city/region name for retrieval (北京 vs 北京市), while
    # retaining the full spelling for matching exact table rows.
    aliases.sort(key=lambda item: (len(_compact(item)), item))
    return aliases


def _standard_ids_matching(
    standard_ids: list[str] | None,
    fragments: tuple[str, ...],
    defaults: tuple[str, ...],
) -> list[str]:
    requested = [str(item).strip() for item in (standard_ids or []) if str(item).strip()]
    if not requested:
        return list(defaults)
    matched = [
        item
        for item in requested
        if any(fragment.casefold() in _compact(item) for fragment in fragments)
    ]
    return matched


def _extract_region_from_query(query: str) -> str:
    """Read a city/region name from a normal-language question without requiring
    the user to mention a standard number or table number."""
    normalized = unicodedata.normalize("NFKC", str(query or "")).strip()
    candidates: list[str] = []
    for match in re.finditer(
        r"([\u4e00-\u9fff]{2,10}?)(?:特别行政区|自治区|自治州|中心城区|市区|城区|地区|市|省|县|区)",
        normalized,
    ):
        value = match.group(1)
        value = re.sub(
            r"^(?:请问|请查询|请帮|查询|查一下|帮我|我想知道|项目位于|项目在|位于|关于|看看|查)+",
            "",
            value,
        )
        value = value.strip("的，,。；;：: ")
        if len(_compact(value)) >= 2:
            candidates.append(value)
    for match in re.finditer(
        r"([\u4e00-\u9fff]{2,10}?)的"
        r"(?:基本风压|基本雪压|雪压|风压|抗震|设防烈度|设计基本地震加速度|设计地震分组)",
        normalized,
    ):
        value = re.sub(
            r"^(?:请问|请查询|请帮|查询|查一下|帮我|我想知道|项目位于|项目在|位于|关于|看看|查)+",
            "",
            match.group(1),
        ).strip()
        if len(_compact(value)) >= 2:
            candidates.append(value)
    return min(candidates, key=len) if candidates else ""


def _query_region_intent(query: str) -> str:
    lowered = str(query or "").casefold()
    has_seismic = any(
        term in lowered
        for term in ("抗震", "设防烈度", "地震加速度", "设计地震分组")
    )
    has_snow_wind = any(
        term in lowered
        for term in ("风压", "雪压", "海拔", "地面粗糙度")
    )
    if has_seismic and has_snow_wind:
        return "combined"
    if has_seismic:
        return "seismic"
    if has_snow_wind:
        return "snow_wind"
    return ""


def knowledge_inventory() -> dict[str, Any]:
    standards = rag_engine.list_standards()
    directory_map = _directory_standard_map()
    standard_titles = {str(item["standard_id"]): str(item.get("title") or "") for item in standards}
    directories = []
    connection, _ = rag_engine.load_index()
    counts = {}
    for source_file, in connection.execute("SELECT source_file FROM chunks"):
        path = str(source_file or "").replace("\\", "/")
        directory = path.rsplit("/", 1)[0] if "/" in path else "未分类"
        counts[directory] = counts.get(directory, 0) + 1
    for directory, ids in sorted(directory_map.items()):
        directories.append({"directory_id": directory, "title": directory.split("/")[-1],
                            "chunks": counts.get(directory, 0), "standard_count": len(ids),
                            "standards": sorted(ids),
                            "standard_titles": [standard_titles.get(item, "") for item in sorted(ids)]})
    return {
        "available": True,
        "source": "Knowledge/07_机器可读规范库/standards.db",
        "count": len(standards),
        "knowledge_bases": standards,
        "directories": directories,
        "directory_count": len(directories),
    }


def search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("knowledge_enabled") is False:
        return {"ok": False, "status": "knowledge_base_disabled", "results": [], "message": "网页已关闭本地知识库检索。"}
    query = str(payload.get("query", "")).strip()
    if not query:
        return {"ok": False, "status": "needs_input", "results": [], "message": "请提供检索问题或关键词。"}
    hits = _selected_search(query, payload.get("top_k", 5), payload.get("standard_ids"),
                            payload.get("source_dirs"))
    auto_region_query = None
    region = _extract_region_from_query(query)
    region_intent = _query_region_intent(query)
    if region and region_intent:
        try:
            region_result = query_region_params.invoke({
                "region": region,
                "items": (
                    ["基本风压", "基本雪压"]
                    if region_intent == "snow_wind"
                    else ["抗震设防烈度", "设计基本地震加速度", "设计地震分组"]
                    if region_intent == "seismic"
                    else ["基本风压", "基本雪压", "抗震设防烈度",
                          "设计基本地震加速度", "设计地震分组"]
                ),
                "standard_ids": payload.get("standard_ids"),
                "source_dirs": payload.get("source_dirs"),
                "knowledge_enabled": payload.get("knowledge_enabled", True),
            })
            region_hits = list(region_result.get("results") or [])
            if region_hits:
                merged = {
                    str(item.get("id") or f"{item.get('standard_id')}:{item.get('page_no')}"): item
                    for item in region_hits
                }
                for item in hits:
                    key = str(item.get("id") or f"{item.get('standard_id')}:{item.get('page_no')}")
                    merged.setdefault(key, item)
                hits = list(merged.values())[: max(1, min(int(payload.get("top_k", 5)), 20))]
            auto_region_query = {
                "region": region,
                "intent": region_intent,
                "status": region_result.get("status"),
            }
        except Exception as exc:
            auto_region_query = {
                "region": region,
                "intent": region_intent,
                "status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
    return {"ok": True, "status": "matched" if hits else "not_found", "query": query,
            "source": "local_standards_rag", "count": len(hits), "results": hits,
            "auto_region_query": auto_region_query,
            "message": "结果来自本地规范检索；工程应用前请核对原文、版本和适用条件。"}


@tool
def search_steel_standards(
    query: str,
    top_k: int = 5,
    standard_ids: list[str] | None = None,
    source_dirs: list[str] | None = None,
    knowledge_enabled: bool = True,
) -> dict[str, Any]:
    """从本地 07 规范知识库进行混合检索，返回条文片段及来源元数据。"""
    return search_payload({"query": query, "top_k": top_k, "standard_ids": standard_ids,
                           "source_dirs": source_dirs,
                           "knowledge_enabled": knowledge_enabled})


@tool
def query_region_params(
    region: str,
    items: list[str] | None = None,
    standard_ids: list[str] | None = None,
    source_dirs: list[str] | None = None,
    knowledge_enabled: bool = True,
) -> dict[str, Any]:
    """在本地规范 RAG 中检索地区荷载/抗震参数的候选依据；不联网、不把片段自动认定为取值。"""
    if not knowledge_enabled:
        return {"ok": False, "status": "knowledge_base_disabled", "region": region,
                "message": "网页已关闭本地知识库检索。"}
    if not str(region or "").strip():
        return {"ok": False, "status": "needs_input", "message": "请提供省、市、区县等地区名称。"}
    requested = items or ["基本风压", "基本雪压", "抗震设防烈度", "设计基本地震加速度", "设计地震分组", "设计反应谱特征周期", "地面粗糙度"]
    aliases = _region_aliases(str(region))
    if not aliases:
        return {"ok": False, "status": "needs_input", "message": "地区名称无法识别。"}
    compact_aliases = [_compact(item) for item in aliases if len(_compact(item)) >= 2]
    primary_region = aliases[0]
    wants_snow_wind = any(
        any(term in str(item) for term in ("风压", "雪压", "海拔", "温度", "地面粗糙度"))
        for item in requested
    )
    wants_seismic = any(
        any(term in str(item) for term in ("抗震", "设防烈度", "地震加速度", "设计地震分组"))
        for item in requested
    )

    e5_standards = _standard_ids_matching(
        standard_ids, ("gb50009",), ("GB50009-2012",)
    )
    seismic_standards = _standard_ids_matching(
        standard_ids,
        ("gb50011", "gbt50011"),
        ("GB50011-2010-2016", "GB-T50011-2010-2024-REV"),
    )
    queries: list[tuple[str, str, list[str]]] = []
    if e5_standards and wants_snow_wind:
        queries.append((
            "snow_wind",
            f"{primary_region} 表E.5 城市名 海拔高度 雪压 风压",
            e5_standards,
        ))
    if seismic_standards and wants_seismic:
        queries.append((
            "seismic",
            f"{primary_region} 附录A",
            seismic_standards,
        ))

    grouped_hits: dict[str, dict[str, Any]] = {}
    evidence_kinds: dict[str, list[str]] = defaultdict(list)
    for kind, query, query_standards in queries:
        for hit in _selected_search(query, 10, query_standards, source_dirs):
            text = _compact(str(hit.get("text", "")))
            if not any(term in text for term in compact_aliases):
                continue
            standard_id = str(hit.get("standard_id", ""))
            if "GB50009" in standard_id:
                table_evidence = (
                    "表e5" in text
                    or "城市名" in text
                    or ("海拔" in text and ("雪压" in text or "风压" in text))
                )
            else:
                # Appendix A is split into A.0.1 ... A.0.2x by province or
                # municipality.  Accept any numbered subsection, but not the
                # explanatory chapter that merely mentions "附录 A".
                table_evidence = re.search(r"a0\d+", text) is not None
            if not table_evidence:
                continue
            key = str(hit.get("id") or f"{standard_id}:{hit.get('page_no')}:{hit.get('clause_no')}")
            grouped_hits[key] = hit
            if kind not in evidence_kinds[key]:
                evidence_kinds[key].append(kind)
    hits = sorted(
        (
            {**hit, "evidence_kinds": evidence_kinds[key]}
            for key, hit in grouped_hits.items()
        ),
        key=lambda item: item.get("score", 0),
        reverse=True,
    )[:8]
    return {
        "ok": bool(hits), "status": "candidate_evidence_found" if hits else "pending_no_region_match",
        "source": "local_standards_rag", "region": region,
        "region_aliases": aliases, "requested_items": requested,
        "queries": [{"purpose": kind, "query": query} for kind, query, _ in queries],
        "results": hits,
        "project_specific_items": {
            "结构安全等级": "须结合建筑用途、破坏后果和项目条件判定，不可仅由地区查询确定。",
            "建筑抗震设防类别": "须结合建筑用途及设防分类标准判定，不可仅由地区查询确定。",
            "地基基础设计等级": "须结合工程规模、地基复杂程度及勘察资料判定。",
        },
        "message": ("检索片段仅为候选依据，不是已确认的地区参数值；请核对标准原文、表号/条款、版本、重现期、场地类别及地方区划。"
                    if hits else "本地规范库未检索到足以支持该地区取值的片段；请补充经审核的地区资料，不能据此推测。"),
    }


LANGCHAIN_TOOLS = [search_steel_standards, query_region_params]
KNOWLEDGE_TOOL_NAMES = {tool.name for tool in LANGCHAIN_TOOLS}
