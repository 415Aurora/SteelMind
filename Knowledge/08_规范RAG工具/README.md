# SteelMind 规范检索工具

运行环境：Python 3.10 或更高版本。日常检索只使用 Python 标准库和 SQLite；OCR 仅用于重建知识库。

## 推荐调用方式

对智能体直接调用，推荐 MCP：

```text
命令：python
参数：D:/Documents/ChatGPT/作业/智能建造施工解决方案/08_规范RAG工具/mcp_server.py
```

可直接参考：

- `mcp_config.example.json`：通用 MCP 客户端配置。
- `mcp_config.codex.example.toml`：Codex 风格配置示例。

对现有 FastAPI + LangChain 工作流，推荐 HTTP：

```powershell
python http_server.py
```

服务默认监听 `http://127.0.0.1:8765`。

如果现有项目本来就是 FastAPI，也可以直接挂载路由：

```python
from fastapi_router import router as standards_router
app.include_router(standards_router)
```

LangChain 可直接导入：

```python
from langchain_tools import LANGCHAIN_TOOLS
```

## 可用工具

- `search_standards`：混合检索规范条款，适合“Q355钢材怎么取强度”这类自然语言问题。
- `get_clause`：按标准和条款号精确读取。
- `lookup_material`：按牌号和厚度精确查材料参数。
- `lookup_section`：按截面编号精确查 H 型钢参数。
- `get_chunk`：读取完整检索块。
- `list_standards`：列出知识库标准。

不建议让模型用 `search_standards` 查找材料数值或截面特性；这两个接口必须使用结构化参数查询。

## HTTP 示例

```powershell
Invoke-RestMethod "http://127.0.0.1:8765/search?q=压弯构件平面外稳定&top_k=5"
Invoke-RestMethod "http://127.0.0.1:8765/clause?standard_id=GB50017-2017&clause_no=8.2.1"
Invoke-RestMethod "http://127.0.0.1:8765/material?grade=Q355&thickness=13"
Invoke-RestMethod "http://127.0.0.1:8765/section?section_id=HN400x200x8x13"
```

## 命令行示例

```powershell
python rag_engine.py search "Q355 钢板 强度设计值" --top-k 5
python rag_engine.py clause GB50017-2017 4.4.1
python rag_engine.py material Q355 13
python rag_engine.py section HN400x200x8x13
```

## 数据与索引

- `07_机器可读规范库/documents.jsonl`：页级或节级结构化记录。
- `07_机器可读规范库/chunks.jsonl`：适合检索的文本块。
- `07_机器可读规范库/全文文本/`：逐标准 Markdown 全文。
- `07_机器可读规范库/standards.db`：SQLite、全文索引、向量和结构化参数。
- `07_机器可读规范库/build_state.json`：构建统计。

## 重新构建

OCR 预处理依赖：

```powershell
python -m pip install -r requirements-ocr.txt
$env:RAG_DEPS_DIR = "<rapidocr依赖安装目录>"
python build_corpus.py --mode all
python build_index.py
python build_file_index.py
```

重新构建是离线处理步骤。AI 日常调用只需要 `rag_engine.py`、`mcp_server.py` 或 `http_server.py`，不依赖 OCR。

## 检索策略

当前索引采用中文字符、词项、数字与标准号的混合特征向量，并叠加 SQLite FTS5 全文召回。优点是无需联网、可处理 Q355、4.4.1、l/400 等精确词项。

若后续需要更强语义检索，可在不改接口的前提下把向量生成器替换为 BGE-M3，或使用 BGE-small-zh-v1.5 做本地向量模型、BGE-reranker-v2-m3 做重排。材料表和截面表仍应调用结构化查询工具，不进入语义检索。
