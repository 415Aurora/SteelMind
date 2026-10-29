from __future__ import annotations

import json
import sys
from typing import Callable

from rag_engine import (
    get_chunk,
    get_clause,
    list_standards,
    lookup_material,
    lookup_section,
    search_standards,
)


TOOLS = [
    {
        "name": "search_standards",
        "description": (
            "混合检索钢结构和荷载规范条款。输入设计问题；返回标准号、版本、"
            "条款号、页码、来源和正文片段。适合语义问题和不完全记得条款号的情况。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "自然语言问题或关键词"},
                "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                "standard_id": {
                    "type": "string",
                    "description": "可选标准号，例如 GB50017-2017",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_clause",
        "description": "按标准号和条款号精确读取条款。例如 GB50017-2017 的 8.2.1。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "standard_id": {"type": "string"},
                "clause_no": {"type": "string"},
            },
            "required": ["standard_id", "clause_no"],
        },
    },
    {
        "name": "lookup_material",
        "description": "按钢材牌号和控制厚度精确返回设计强度参数。不要用文本检索替代本工具。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "grade": {"type": "string", "description": "例如 Q235、Q355、Q390"},
                "thickness_mm": {"type": "number", "description": "控制板件厚度，mm"},
            },
            "required": ["grade", "thickness_mm"],
        },
    },
    {
        "name": "lookup_section",
        "description": "按 H 型钢截面编号查询面积、惯性矩、截面模量和回转半径。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "section_id": {
                    "type": "string",
                    "description": "例如 HN400x200x8x13 或 HN400×200×8×13",
                }
            },
            "required": ["section_id"],
        },
    },
    {
        "name": "get_chunk",
        "description": "按检索结果中的 chunk id 读取完整文本块。",
        "inputSchema": {
            "type": "object",
            "properties": {"chunk_id": {"type": "string"}},
            "required": ["chunk_id"],
        },
    },
    {
        "name": "list_standards",
        "description": "列出知识库收录的全部标准和文本块数量。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_FUNCTIONS: dict[str, Callable] = {
    "search_standards": search_standards,
    "get_clause": get_clause,
    "lookup_material": lookup_material,
    "lookup_section": lookup_section,
    "get_chunk": get_chunk,
    "list_standards": list_standards,
}


def send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(message: dict) -> dict | None:
    method = message.get("method")
    message_id = message.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "steelmind-standards",
                    "version": "1.0.0",
                },
            },
        }
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": message_id, "result": {}}
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": {"tools": TOOLS},
        }
    if method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in TOOL_FUNCTIONS:
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"},
            }
        try:
            result = TOOL_FUNCTIONS[name](**arguments)
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, ensure_ascii=False),
                        }
                    ],
                    "isError": False,
                },
            }
        except Exception as error:  # noqa: BLE001
            return {
                "jsonrpc": "2.0",
                "id": message_id,
                "result": {
                    "content": [{"type": "text", "text": f"工具调用失败：{error}"}],
                    "isError": True,
                },
            }
    if message_id is None:
        return None
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            response = handle(json.loads(line))
            if response is not None:
                send(response)
        except Exception as error:  # noqa: BLE001
            send(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Invalid JSON: {error}"},
                }
            )


if __name__ == "__main__":
    main()
