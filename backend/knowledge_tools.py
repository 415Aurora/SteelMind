"""SteelMind adapters for the local standards RAG corpus (Knowledge/07 and 08)."""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import unicodedata
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


def _selected_search(query: str, top_k: int = 5, standard_ids: list[str] | None = None) -> list[dict[str, Any]]:
    top_k = max(1, min(int(top_k), 20))
    selected = [str(item).strip() for item in (standard_ids or []) if str(item).strip()]
    if not selected:
        return rag_engine.search_standards(query, top_k=top_k)
    hits: dict[str, dict[str, Any]] = {}
    # Search each selected standard separately because the supplied RAG API
    # accepts one standard_id filter per call.
    each_k = min(20, max(top_k, (top_k + len(selected) - 1) // len(selected) + 2))
    for standard_id in selected:
        for hit in rag_engine.search_standards(query, top_k=each_k, standard_id=standard_id):
            hits[str(hit.get("id") or f"{standard_id}:{hit.get('page_no')}:{hit.get('clause_no')}")] = hit
    return sorted(hits.values(), key=lambda item: item.get("score", 0), reverse=True)[:top_k]


def _compact(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def knowledge_inventory() -> dict[str, Any]:
    standards = rag_engine.list_standards()
    return {
        "available": True,
        "source": "Knowledge/07_机器可读规范库/standards.db",
        "count": len(standards),
        "knowledge_bases": standards,
    }


def search_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("knowledge_enabled") is False:
        return {"ok": False, "status": "knowledge_base_disabled", "results": [], "message": "网页已关闭本地知识库检索。"}
    query = str(payload.get("query", "")).strip()
    if not query:
        return {"ok": False, "status": "needs_input", "results": [], "message": "请提供检索问题或关键词。"}
    hits = _selected_search(query, payload.get("top_k", 5), payload.get("standard_ids"))
    return {"ok": True, "status": "matched" if hits else "not_found", "query": query,
            "source": "local_standards_rag", "count": len(hits), "results": hits,
            "message": "结果来自本地规范检索；工程应用前请核对原文、版本和适用条件。"}


@tool
def search_steel_standards(
    query: str,
    top_k: int = 5,
    standard_ids: list[str] | None = None,
    knowledge_enabled: bool = True,
) -> dict[str, Any]:
    """从本地 07 规范知识库进行混合检索，返回条文片段及来源元数据。"""
    return search_payload({"query": query, "top_k": top_k, "standard_ids": standard_ids,
                           "knowledge_enabled": knowledge_enabled})


@tool
def query_region_params(
    region: str,
    items: list[str] | None = None,
    standard_ids: list[str] | None = None,
    knowledge_enabled: bool = True,
) -> dict[str, Any]:
    """在本地规范 RAG 中检索地区荷载/抗震参数的候选依据；不联网、不把片段自动认定为取值。"""
    if not knowledge_enabled:
        return {"ok": False, "status": "knowledge_base_disabled", "region": region,
                "message": "网页已关闭本地知识库检索。"}
    if not str(region or "").strip():
        return {"ok": False, "status": "needs_input", "message": "请提供省、市、区县等地区名称。"}
    requested = items or ["基本风压", "基本雪压", "抗震设防烈度", "设计基本地震加速度", "设计地震分组", "设计反应谱特征周期", "地面粗糙度"]
    query = f"{region} 地区参数 " + "；".join(str(item) for item in requested)
    region_terms = re.findall(r"[\u4e00-\u9fff]{2,}?(?:自治区|自治州|地区|省|市|盟|县|区|旗)", region)
    compact_region_terms = [_compact(term) for term in region_terms if len(_compact(term)) >= 2]
    candidates = _selected_search(query, 20, standard_ids)
    # A regional lookup must have an actual place-name match in the retrieved
    # text; otherwise generic clauses are not evidence of a city's parameters.
    hits = [hit for hit in candidates if any(term in _compact(str(hit.get("text", ""))) for term in compact_region_terms)]
    hits = hits[:8]
    return {
        "ok": bool(hits), "status": "candidate_evidence_found" if hits else "pending_no_region_match",
        "source": "local_standards_rag", "region": region, "requested_items": requested,
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
