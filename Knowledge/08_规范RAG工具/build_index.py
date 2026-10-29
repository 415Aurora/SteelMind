from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "07_机器可读规范库"
CHUNKS_FILE = DATA_DIR / "chunks.jsonl"
DB_FILE = DATA_DIR / "standards.db"
VECTOR_DIM = 1024

ASCII_TOKEN = re.compile(r"[a-zA-Z]+\d*(?:[-./]\d+)*|\d+(?:\.\d+)?")
CHINESE_RUN = re.compile(r"[\u4e00-\u9fff]+")


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
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        index = value % VECTOR_DIM
        sign = -1.0 if ((value >> 63) & 1) else 1.0
        vector[index] += sign * (1.0 + math.log(count)) * idf.get(token, 1.0)
    norm = math.sqrt(sum(item * item for item in vector))
    if norm:
        vector = [item / norm for item in vector]
    return vector


def parse_thickness_range(label: str) -> tuple[float, float]:
    parts = [part.strip() for part in label.split(",")]
    low, high = 0.0, 999.0
    for part in parts:
        numbers = [float(value) for value in re.findall(r"\d+(?:\.\d+)?", part)]
        if not numbers:
            continue
        value = numbers[0]
        if part.startswith("≤") or part.startswith("<"):
            high = value
        elif part.startswith(">") and "≤" not in part:
            low = math.nextafter(value, math.inf)
        elif "≤" in part:
            high = value
        else:
            low = value
    return low, high


def load_chunks() -> list[dict]:
    if not CHUNKS_FILE.exists():
        raise FileNotFoundError(
            f"找不到 {CHUNKS_FILE}，请先运行 build_corpus.py。"
        )
    rows = []
    with CHUNKS_FILE.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS chunks;
        DROP TABLE IF EXISTS chunks_fts;
        DROP TABLE IF EXISTS vectors;
        DROP TABLE IF EXISTS index_meta;

        CREATE TABLE chunks (
            row_id INTEGER PRIMARY KEY,
            id TEXT UNIQUE NOT NULL,
            standard_id TEXT NOT NULL,
            title TEXT NOT NULL,
            version TEXT,
            status TEXT,
            page_no INTEGER,
            section_no INTEGER,
            heading TEXT,
            clause_no TEXT,
            source_file TEXT,
            source_url TEXT,
            source_type TEXT,
            text TEXT NOT NULL
        );
        CREATE INDEX idx_chunks_standard ON chunks(standard_id);
        CREATE INDEX idx_chunks_clause ON chunks(standard_id, clause_no);

        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            id UNINDEXED,
            terms,
            title,
            heading,
            text
        );

        CREATE TABLE vectors (
            row_id INTEGER PRIMARY KEY,
            vector BLOB NOT NULL
        );

        CREATE TABLE index_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )


def build_material_file() -> None:
    source = DATA_DIR / "structured" / "materials.json"
    if not source.exists():
        raise FileNotFoundError(source)
    material_rows = json.loads(source.read_text(encoding="utf-8"))
    normalized = []
    for row in material_rows:
        low, high = parse_thickness_range(row["thickness_range_mm"])
        normalized.append({**row, "min_thickness_mm": low, "max_thickness_mm": high})
    (DATA_DIR / "structured" / "materials_indexed.json").write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    chunks = load_chunks()
    token_lists = [tokenize(row["text"]) for row in chunks]
    document_frequency: dict[str, int] = defaultdict(int)
    for tokens in token_lists:
        for token in set(tokens):
            document_frequency[token] += 1
    total = max(1, len(chunks))
    idf = {
        token: math.log((total + 1) / (frequency + 0.5)) + 1.0
        for token, frequency in document_frequency.items()
    }

    connection = sqlite3.connect(DB_FILE)
    create_schema(connection)
    for row_id, (row, tokens) in enumerate(zip(chunks, token_lists), start=1):
        counts = Counter(tokens)
        connection.execute(
            """
            INSERT INTO chunks(
                row_id, id, standard_id, title, version, status, page_no,
                section_no, heading, clause_no, source_file, source_url,
                source_type, text
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                row["id"],
                row["standard_id"],
                row["title"],
                row.get("version"),
                row.get("status"),
                row.get("page_no"),
                row.get("section_no"),
                row.get("heading"),
                row.get("clause_no"),
                row.get("source_file"),
                row.get("source_url"),
                row.get("source_type"),
                row["text"],
            ),
        )
        connection.execute(
            "INSERT INTO chunks_fts(id, terms, title, heading, text) VALUES (?, ?, ?, ?, ?)",
            (
                row["id"],
                " ".join(sorted(counts)),
                row["title"],
                row.get("heading") or "",
                row["text"],
            ),
        )
        vector = vectorize(counts, idf)
        connection.execute(
            "INSERT INTO vectors(row_id, vector) VALUES (?, ?)",
            (row_id, struct.pack(f"<{VECTOR_DIM}f", *vector)),
        )
    metadata = {
        "embedding_method": "hashed_char_word_tfidf",
        "dimension": VECTOR_DIM,
        "chunk_count": len(chunks),
        "token_count": len(idf),
        "idf": idf,
    }
    connection.execute(
        "INSERT INTO index_meta(key, value) VALUES (?, ?)",
        ("metadata", json.dumps(metadata, ensure_ascii=False)),
    )
    connection.commit()
    connection.close()
    build_material_file()
    print(
        json.dumps(
            {
                "database": str(DB_FILE),
                "chunks": len(chunks),
                "vocabulary": len(idf),
                "dimension": VECTOR_DIM,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
