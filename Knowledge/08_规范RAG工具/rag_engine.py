from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
import struct
import unicodedata
from collections import Counter
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "07_机器可读规范库"
DB_FILE = DATA_DIR / "standards.db"
MATERIALS_FILE = DATA_DIR / "structured" / "materials_indexed.json"
SECTIONS_FILE = DATA_DIR / "structured" / "sections.json"
VECTOR_DIM = 1024

ASCII_TOKEN = re.compile(r"[a-zA-Z]+\d*(?:[-./]\d+)*|\d+(?:\.\d+)?")
CHINESE_RUN = re.compile(r"[\u4e00-\u9fff]+")
STANDARD_CODE = re.compile(r"(GB(?:/T)?\s*\d+(?:\.\d+)?(?:-\d{4})?)", re.I)


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens = ASCII_TOKEN.findall(lowered)
    for run in CHINESE_RUN.findall(lowered):
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(len(run) - 1))
        tokens.extend(run[index : index + 3] for index in range(len(run) - 2))
    return tokens


def vectorize(token_counts: Counter[str], idf: dict[str, float]) -> list[float]:
    vector = [0.0] * VECTOR_DIM
    for token, count in token_counts.items():
        value = int.from_bytes(
            hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(),
            "little",
        )
        index = value % VECTOR_DIM
        sign = -1.0 if ((value >> 63) & 1) else 1.0
        vector[index] += sign * (1.0 + math.log(count)) * idf.get(token, 1.0)
    norm = math.sqrt(sum(item * item for item in vector))
    if norm:
        vector = [item / norm for item in vector]
    return vector


def normalize_standard_id(value: str) -> str:
    return re.sub(r"[\s_/]", "-", value.upper())


def compact_standard_id(value: str) -> str:
    return re.sub(r"[^A-Z0-9.]", "", value.upper())


def compact_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


@lru_cache(maxsize=1)
def load_index():
    if not DB_FILE.exists():
        raise RuntimeError(
            f"向量索引不存在：{DB_FILE}。请先运行 build_index.py。"
        )
    connection = sqlite3.connect(DB_FILE, check_same_thread=False)
    metadata = json.loads(
        connection.execute(
            "SELECT value FROM index_meta WHERE key='metadata'"
        ).fetchone()[0]
    )
    return connection, metadata


@lru_cache(maxsize=1)
def load_vectors() -> list[list[float]]:
    connection, metadata = load_index()
    vectors = []
    for (blob,) in connection.execute("SELECT vector FROM vectors ORDER BY row_id"):
        vectors.append(list(struct.unpack(f"<{metadata['dimension']}f", blob)))
    return vectors


@lru_cache(maxsize=1)
def load_chunk_tokens() -> dict[int, set[str]]:
    connection, _ = load_index()
    return {
        row_id: set(tokenize(text))
        for row_id, text in connection.execute(
            "SELECT row_id, text FROM chunks ORDER BY row_id"
        )
    }


def row_to_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def search_standards(
    query: str,
    top_k: int = 5,
    standard_id: str | None = None,
) -> list[dict]:
    if not query.strip():
        return []
    connection, metadata = load_index()
    connection.row_factory = sqlite3.Row
    tokens = tokenize(query)
    counts = Counter(tokens)
    query_vector = vectorize(counts, metadata["idf"])
    vectors = load_vectors()
    chunk_tokens = load_chunk_tokens()

    filter_id = compact_standard_id(standard_id) if standard_id else None
    if filter_id:
        allowed = {
            row["row_id"]
            for row in connection.execute(
                "SELECT row_id, standard_id FROM chunks"
            )
            if compact_standard_id(row["standard_id"]) == filter_id
        }
    else:
        allowed = set(chunk_tokens)


    lexical_terms = [
        token for token in dict.fromkeys(tokens)
        if len(token) >= 2 and re.search(r"[\u4e00-\u9fffA-Za-z]", token)
    ][:30]
    fts_ids = set()
    if lexical_terms:
        fts_query = " OR ".join(f'"{term}"' for term in lexical_terms)
        try:
            fts_rows = connection.execute(
                "SELECT id FROM chunks_fts WHERE chunks_fts MATCH ? LIMIT 80",
                (fts_query,),
            ).fetchall()
            fts_ids = {row["id"] for row in fts_rows}
        except sqlite3.OperationalError:
            fts_ids = set()

    scored = []
    query_code = STANDARD_CODE.search(query)
    compact_query = compact_text(query)
    query_token_set = {
        token
        for token in tokens
        if len(token) >= 2 or not re.search(r"[\u4e00-\u9fff]", token)
    }
    query_idf_total = sum(metadata["idf"].get(token, 1.0) for token in query_token_set)
    for row_id in allowed:
        vector = vectors[row_id - 1]
        vector_score = sum(
            query_vector[index] * vector[index]
            for index in range(metadata["dimension"])
        )
        row = connection.execute(
            "SELECT * FROM chunks WHERE row_id=?", (row_id,)
        ).fetchone()
        if row["text"].count("...") > 30 or row["text"].strip().startswith("目次"):
            continue
        token_overlap = query_token_set & chunk_tokens[row_id]
        lexical_score = (
            sum(metadata["idf"].get(token, 1.0) for token in token_overlap)
            / max(1.0, query_idf_total)
        )
        if compact_query and compact_query in compact_text(row["text"]):
            lexical_score += 1.5
        if compact_query and compact_query in compact_text(row["heading"] or ""):
            lexical_score += 0.8
        if row["id"] in fts_ids:
            lexical_score += 0.2
        if query_code:
            query_code_normalized = compact_standard_id(query_code.group(1))
            if query_code_normalized in compact_standard_id(row["standard_id"]):
                lexical_score += 0.8
        score = vector_score * 0.08 + lexical_score * 0.92
        if score > 0.02:
            item = row_to_dict(row)
            item["score"] = round(score, 6)
            item["text"] = item["text"][:2200]
            scored.append(item)
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:top_k]


def _clause_matches(value: str, target: str) -> bool:
    """Match a clause as a complete identifier, allowing formula suffixes."""
    normalized = unicodedata.normalize("NFKC", value or "")
    target = unicodedata.normalize("NFKC", target or "").strip()
    if not target:
        return False
    if normalized.strip() == target:
        return True
    # Do not let 4.4.1 match 14.4.1.  A following "-1" is accepted because it is
    # a formula/subclause of the requested identifier.
    pattern = rf"(?<![0-9A-Z]){re.escape(target)}(?![0-9]|\.\d)"
    return re.search(pattern, normalized, flags=re.IGNORECASE) is not None


def get_clause(standard_id: str, clause_no: str) -> list[dict]:
    connection, _ = load_index()
    connection.row_factory = sqlite3.Row
    target_id = compact_standard_id(standard_id)
    target_clause = unicodedata.normalize("NFKC", clause_no).strip()
    matched = []
    for row in connection.execute(
        "SELECT * FROM chunks ORDER BY page_no, section_no"
    ):
        if compact_standard_id(row["standard_id"]) != target_id:
            continue
        clause_value = unicodedata.normalize("NFKC", row["clause_no"] or "").strip()
        heading_value = unicodedata.normalize("NFKC", row["heading"] or "")
        text_value = unicodedata.normalize("NFKC", row["text"])
        if (
            clause_value == target_clause
            or _clause_matches(heading_value, target_clause)
            or _clause_matches(text_value, target_clause)
        ):
            matched.append(row_to_dict(row))
        if len(matched) >= 10:
            break
    return matched


def lookup_material(grade: str, thickness_mm: float) -> list[dict]:
    if not MATERIALS_FILE.exists():
        return []
    rows = json.loads(MATERIALS_FILE.read_text(encoding="utf-8"))
    normalized_grade = grade.strip().upper()
    matched = [
        row
        for row in rows
        if row["grade"].upper() == normalized_grade
        and row["min_thickness_mm"] <= thickness_mm <= row["max_thickness_mm"]
    ]
    return matched


def normalize_section_id(value: str) -> str:
    return (
        value.upper()
        .replace("×", "X")
        .replace("*", "X")
        .replace(" ", "")
        .replace("MM", "")
    )


def lookup_section(section_id: str) -> list[dict]:
    if not SECTIONS_FILE.exists():
        return []
    rows = json.loads(SECTIONS_FILE.read_text(encoding="utf-8"))
    query = normalize_section_id(section_id)
    return [
        row
        for row in rows
        if query in normalize_section_id(row.get("截面编号", ""))
        or normalize_section_id(row.get("截面编号", "")) in query
    ]


def list_standards() -> list[dict]:
    connection, _ = load_index()
    connection.row_factory = sqlite3.Row
    rows = connection.execute(
        """
        SELECT standard_id, title, version, status, COUNT(*) AS chunks
        FROM chunks
        GROUP BY standard_id, title, version, status
        ORDER BY standard_id
        """
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def get_chunk(chunk_id: str) -> dict | None:
    connection, _ = load_index()
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        "SELECT * FROM chunks WHERE id=?", (chunk_id,)
    ).fetchone()
    return row_to_dict(row) if row else None


def main() -> None:
    parser = argparse.ArgumentParser(description="SteelMind 规范混合检索工具")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--top-k", type=int, default=5)
    search_parser.add_argument("--standard-id")

    clause_parser = subparsers.add_parser("clause")
    clause_parser.add_argument("standard_id")
    clause_parser.add_argument("clause_no")

    material_parser = subparsers.add_parser("material")
    material_parser.add_argument("grade")
    material_parser.add_argument("thickness", type=float)

    section_parser = subparsers.add_parser("section")
    section_parser.add_argument("section_id")

    subparsers.add_parser("standards")
    args = parser.parse_args()
    if args.command == "search":
        result = search_standards(args.query, args.top_k, args.standard_id)
    elif args.command == "clause":
        result = get_clause(args.standard_id, args.clause_no)
    elif args.command == "material":
        result = lookup_material(args.grade, args.thickness)
    elif args.command == "section":
        result = lookup_section(args.section_id)
    else:
        result = list_standards()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
