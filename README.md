# Ultra Steel Agent（SteelMind 钢结构智能设计助手）

这是一个可通过网页访问的初版智能体前端。当前版本采用静态 HTML/JavaScript，支持 OpenAI-compatible `POST /chat/completions` 接口。

## 本地运行

### Windows（推荐）

安装 Anaconda 或 Miniconda 后，双击项目根目录的 `start_tool_gateway.bat`。如果项目没有 `.venv`，启动器会自动查找 Conda、创建名为 `steelmind` 的 Python 环境、安装工具依赖，随后启动服务并打开 Agent 网页。首次部署需要联网下载环境和依赖。也可以直接双击 `start_tool_gateway_conda.bat`。

Conda 默认安装路径会自动查找；如果安装在自定义路径，可设置 `CONDA_EXE` 环境变量，指向该安装目录下的 `Scripts\conda.exe`。

### Linux/macOS

安装并初始化 Conda 后，运行 `./start_tool_gateway_conda.sh`；或者运行 `./start_tool_gateway.sh`，后者会使用项目 `.venv`。启动器会在服务就绪后自动打开 Agent 网页。详细说明见 [`backend/README.md`](backend/README.md)。

### Python 环境清单

- `environment-steelmind-win64.yml`：Anaconda 导出的完整 `steelmind` 环境，适用于 Windows 64 位，包含 Python 3.12.16、Conda 运行库和已解析的 pip 包版本。使用 `conda env create -f environment-steelmind-win64.yml` 可重建。
- 根目录 `requirements.txt`：与该导出同步的 pip 包版本快照；它不包含 Python 解释器和 Conda 运行库。
- `backend/requirements.txt`：启动脚本使用的兼容版本范围清单，便于在不同机器上安装更新的兼容版本。

`environment-steelmind-win64.yml` 含 Windows 专用运行库和 `openseespywin`，不能直接用于 Linux/macOS；其他系统请使用对应系统的启动脚本和依赖安装流程。

## 仅启动静态网页

如只需预览前端，可在 `dist` 目录启动静态服务器：

```powershell
cd .\steel-agent
python -m http.server 8080 --directory dist
```

然后打开 `http://localhost:8080`。需要调用 Python 工具时，应使用上面的网关启动器。

## Token 与安全

DeepSeek API Key 由使用者在页面中输入，只留在当前页面内存，不写入 `sessionStorage` 或源代码。聊天使用 OpenAI-compatible SSE 流式输出，生成中可点击“停止回答”中止当前请求。系统提示词可在左侧“系统提示词”面板查看、编辑、保存或恢复默认，内容保存于当前浏览器的 `localStorage`；API Key 不会随提示词保存。

Python 工具由独立 FastAPI 网关提供，参阅 `backend/README.md`。线上网页填写的 `127.0.0.1` 指向访问者自己的电脑；公网使用需部署可访问的 HTTPS 网关，并配置来源白名单与服务端依赖。

## LangChain LCEL 整体设计工作流

后端使用 LangChain LCEL 组织整体工作流，网页右侧“LangChain 整体工作流”调用 `POST /workflow/run-stream`。`RunnableSequence` 串联输入校验、荷载组合、OpenSeesPy 简化框架分析、构件验算和成果生成；`RunnableLambda` 负责按用户给定候选截面进行有界迭代。运行期间以 SSE 逐次推送工具的输入与输出，网页同步显示阶段状态和调用记录。工作流不让模型臆造荷载、内力或截面。原有 `POST /workflow/run` 同步接口仍保留，`GET /workflow/health` 检查 LangChain LCEL 是否可用。DeepSeek 对话提示词负责指导回复，工具调用仍由结构化工作流或单项工具入口触发。

工作流 JSON 的主要字段：

```json
{
  "project_name": "教学楼钢框架初步设计",
  "geometry": {"bays": 1, "stories": 1, "bay_m": 6, "height_m": 6, "base_support": "fixed"},
  "loads": {"dead": 120, "live": 50, "wind": 20, "seismic": 80, "unit": "kN/m", "q_kNm": 10, "lateral_kn": 5},
  "model_sections": {"beam_section": "HN400x200", "column_section": "HW250x250"},
  "members": [{"member_id": "B1", "member_type": "beam", "section": "HN400x200", "candidate_sections": ["HN400x200", "HN450x200"], "steel": "Q355", "span_m": 6, "Mx_kNm": 120, "V_kn": 40, "deflection_mm": 12}],
  "generate_outputs": true
}
```

安装/升级服务端依赖后重启 FastAPI：

```powershell
python -m pip install -r "C:\Users\Administrator\Desktop\小论文\AIwork\steel-agent\backend\requirements.txt"
```

本版本的工作流是确定性工具编排，不会让 DeepSeek 自动猜测荷载或擅自选截面；截面迭代只会按请求中的候选列表顺序尝试。当前 OpenSees 工具只建立线弹性二维框架简化模型，不会将 Excel 模板中的任意三维节点、杆件、连接释放、荷载工况完整映射到有限元模型。没有提供构件内力输入时也不会声称完成构件验算。计算书和 DXF 是方案级辅助成果，必须经工程师核验，DXF 并非可直接施工的正式图纸。

DeepSeek 聊天 API 与 LangChain 工程流程是两条分开的路径：前者用于对话解释，后者按结构化参数通过 LCEL 运行确定性工具。后续可再加入模型提取 Excel 参数、指出缺项并征求人类确认的步骤，但结构计算和验算仍应由明确的数值工具执行。

## 项目代码与工具位置

运行中的 Python 工具源码现已集中在 `backend/tool_sources/`，网关默认从仓库内加载，不再依赖 `C:\Users\Administrator\Downloads`。下载目录中的原件保留未动。工具与工作流代码位置、网页代码及 RAG 代码索引见 [`backend/README.md`](backend/README.md) 的“代码与工具索引”。

主要入口：`backend/app.py` 是 HTTP 网关，`backend/workflow.py` 编排三条 LangChain LCEL 工作流，`backend/knowledge_tools.py` 连接本地规范 RAG，`dist/index.html` 是网页，`tools/build_model_template.mjs` 生成 Excel 参数模板。Python 环境安装和启动步骤请看 [`backend/README.md`](backend/README.md)。

工作流3现接入 `backend/tool_sources/engineering_drawings.py` 与 `backend/engineering_export/`。工作流2最终报告会先转换并预检为 DesignBundle，再生成计算书、结果表、DXF/PDF二维方案图和 ZIP；数据缺项会拦截或标为草稿。该组件目前只支持二维方案级表达，不能代替正式施工图、规范组合分析或专业审查，详细输入输出契约见 [`backend/README.md`](backend/README.md)。
