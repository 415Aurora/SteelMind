"""可直接放入现有 LangChain 工作流的工具包装。"""

from __future__ import annotations

from langchain_core.tools import tool

from rag_engine import (
    get_clause,
    list_standards,
    lookup_material,
    lookup_section,
    search_standards,
)


@tool
def search_steel_standards(
    query: str,
    top_k: int = 5,
    standard_id: str | None = None,
) -> list[dict]:
    """混合检索钢结构规范条款，返回标准号、版本、页码、条款号和正文。"""
    return search_standards(query, top_k, standard_id)


@tool
def get_steel_clause(standard_id: str, clause_no: str) -> list[dict]:
    """按标准号和条款号精确读取条款。"""
    return get_clause(standard_id, clause_no)


@tool
def get_steel_material(grade: str, thickness_mm: float) -> list[dict]:
    """按钢材牌号和控制厚度查询设计强度。"""
    return lookup_material(grade, thickness_mm)


@tool
def get_h_section(section_id: str) -> list[dict]:
    """按 H 型钢截面编号查询截面参数。"""
    return lookup_section(section_id)


@tool
def get_standard_inventory() -> list[dict]:
    """列出规范知识库内的标准及版本。"""
    return list_standards()


LANGCHAIN_TOOLS = [
    search_steel_standards,
    get_steel_clause,
    get_steel_material,
    get_h_section,
    get_standard_inventory,
]
