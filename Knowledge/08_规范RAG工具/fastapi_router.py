"""可挂载到现有 FastAPI 服务的路由示例。"""

from __future__ import annotations

from fastapi import APIRouter, Query

from rag_engine import (
    get_clause,
    list_standards,
    lookup_material,
    lookup_section,
    search_standards,
)


router = APIRouter(prefix="/standards", tags=["钢结构规范知识库"])


@router.get("/search")
def search(
    q: str = Query(..., description="自然语言问题或关键词"),
    top_k: int = Query(5, ge=1, le=20),
    standard_id: str | None = None,
):
    return search_standards(q, top_k, standard_id)


@router.get("/clause")
def clause(standard_id: str, clause_no: str):
    return get_clause(standard_id, clause_no)


@router.get("/material")
def material(grade: str, thickness: float):
    return lookup_material(grade, thickness)


@router.get("/section")
def section(section_id: str):
    return lookup_section(section_id)


@router.get("/inventory")
def inventory():
    return list_standards()
