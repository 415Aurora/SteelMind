# SteelMind Python Tool Gateway

FastAPI 网关默认从仓库内 `backend/tool_sources/` 加载结构工具；只有显式设置 `STEEL_TOOL_SOURCE` 时才切换到指定目录。`/health` 报告总体连通性，`/tools` 逐项报告依赖是否满足，`/invoke/{tool_name}` 执行单个工具。网页将设计拆为三条 LCEL 工作流：`/workflow/information-selection/run-stream` 信息获取与截面初选、`/workflow/section-iteration/run-stream` 截面迭代与优化、`/workflow/engineering-outputs/run-stream` 工程文件输出；各接口以 SSE 推送实际工具输入/输出。规范 RAG 直接读取项目 `Knowledge/07_机器可读规范库/standards.db`，无需另起 8765 HTTP 服务。

## 启动

Windows 可双击项目根目录的 `start_tool_gateway.bat` 启动本地服务。已有项目 `.venv` 时会补齐后端依赖；没有 `.venv` 时会自动切换到 Conda 启动器，查找 Anaconda/Miniconda 并创建 `steelmind` 环境。启动器会等待 `/health` 检查通过后自动打开 Agent 页面；服务窗口需要保持运行，关闭窗口会停止网关。若已存在健康的 SteelMind 网关，启动器会复用并打开页面，不会重复绑定端口。首次安装需要联网下载 Python 和依赖包。

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Linux/macOS 使用项目根目录的 `start_tool_gateway.sh`。首次启动时，脚本会创建 `.venv` 并安装后端依赖；之后直接运行脚本即可。网关就绪后会自动打开 Agent 页面。推荐安装 Python 3.12。若 Python 不在默认路径，可通过 `STEELMIND_PYTHON` 指定解释器；也可通过 `STEELMIND_VENV` 指定虚拟环境目录。

```bash
chmod +x start_tool_gateway.sh
./start_tool_gateway.sh
```

启动器会在服务健康后打开 `http://127.0.0.1:8000/`。如需手动检查状态，可访问 `http://127.0.0.1:8000/health`。PDF 导出还需要安装 LibreOffice；中文 PDF 需要安装 Noto Sans CJK SC 字体。

### 使用 Anaconda/Miniconda 自动部署环境

每台需要运行本地工具网关的电脑都需要安装项目依赖。用户不必手动创建 Python 虚拟环境；以下启动器会使用 `environment.yml` 创建名为 `steelmind` 的 Conda 环境（Python 3.12），安装 `backend/requirements.txt` 中的依赖，然后启动网关。首次运行需要联网下载 Conda 与 pip 包。

- Windows：双击仓库根目录的 `start_tool_gateway.bat` 或 `start_tool_gateway_conda.bat`；Conda 不必预先创建 `steelmind` 环境。若 Anaconda 安装在自定义目录且启动器找不到它，可设置环境变量 `CONDA_EXE` 指向 `...\Scripts\conda.exe`，或在 Anaconda Prompt 中启动。
- Linux/macOS：先初始化 Anaconda/Miniconda shell，然后运行 `chmod +x start_tool_gateway_conda.sh && ./start_tool_gateway_conda.sh`。

后续仍可使用同一个启动器；它会检查环境、补齐依赖并启动服务。环境名可通过 `STEELMIND_CONDA_ENV` 修改。PDF 导出还需要系统安装 LibreOffice；中文 PDF 需要 Noto Sans CJK SC 字体。若本机已安装 `steelmind` Conda 环境，也可直接从激活该环境的终端启动：`python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8000`。

在安装了 Python 依赖的 Anaconda Prompt / PowerShell 中运行：

```powershell
conda activate torch
python -m pip install -r "C:\Users\Administrator\Desktop\小论文\AIwork\steel-agent\backend\requirements.txt"
python -m uvicorn app:app --app-dir 'C:\Users\Administrator\Desktop\小论文\AIwork\steel-agent\backend' --host 127.0.0.1 --port 8000
```

服务启动后打开 `http://127.0.0.1:8000/` 可进入本地 SteelMind 网页；`http://127.0.0.1:8000/health` 用于检查工具网关状态。页面会从同一网关调用工具并提供建模参数模板下载。本机服务绑定 loopback，避免默认暴露到局域网。

## 代码与工具索引

| 文件 | 职责 / 提供的工具 |
|---|---|
| `app.py` | FastAPI 网关、工具动态加载、单工具调用/API、SSE 工作流路由、健康检查、产物下载及本地/S3 存储适配 |
| `workflow.py` | LangChain LCEL 工作流编排：信息获取与截面初选、截面迭代优化、工程文件输出；记录步骤输入/输出 |
| `knowledge_tools.py` | SteelMind 对本地规范 RAG 的适配：`search_steel_standards`、`query_region_params` |
| `tool_sources/structural_calc.py` | `validate_steel_frame_parameters`、`query_steel_sections`、`calculate_load_combination`、`check_steel_member`；另有旧兼容工具 `optimize_steel_truss_members` |
| `tool_sources/q235_section_optimizer.py`、`tool_sources/Q235_钢结构强度选截面工具/steel_section_optimizer.py` | `optimize_q235_steel_sections` Agent 适配器与原始离散选截面算法；可接收内力样本或本项目 OpenSees 的 `end_forces_local`，对311个Q235焊接截面作强度筛选 |
| `section_catalog.py`、`steel_sections.json`、`tool_sources/截面库.csv` | 统一检索与设计属性接口：430个 GB/T 11263-2024 热轧H型钢 + 311个本地Q235焊接H型截面，共741个记录。热轧记录存 JSON，焊接数据运行时从CSV合并；焊接型号加 `WH-` 前缀，避免与4个同名但尺寸/特性不同的热轧记录混淆。`scripts/build_section_catalog.py` 从本地规范 PDF 重建热轧JSON核心库 |
| `tool_sources/opensees_analysis.py` | `opensees_frame_verify`：参数化二维钢框架 OpenSeesPy 建模与静力分析；为成果导出返回实体节点、位移、支座反力、杆件节点关系和局部端力 |
| `tool_sources/opensees_visualize.py` | `opensees_frame_visualize`、`draw_steel_section`：按 X/Z 双向跨数与跨度生成空间几何展示、构件验算着色和截面图形数据；当前 OpenSees 求解器仍为二维，不把面外几何当作计算结果 |
| `tool_sources/generate_design_files.py` | `generate_calculation_book`、`generate_design_outputs`：生成计算书及 Excel/Word/DXF 文件 |
| `tool_sources/engineering_drawings.py` | `generate_construction_drawing_package`：把工作流2最终报告映射为严格的 DesignBundle、预检数据、生成成果包并转成网关下载链接 |
| `engineering_export/src/steelmind_export/` | 新接入的成果生成组件：DesignBundle 契约、输入/覆盖校核、计算书与结果表、DXF/PDF 图纸、成果清单/哈希/ZIP；随包保留 README、测试、示例和中文字体授权 |
| `tool_sources/s3_storage.py` | Coze/S3 对象存储后端；未配置 S3 时网关改用 `app.py` 的本地存储适配 |
| `tool_sources/legacy/region_params.py` | 历史版独立地区 JSON 查询实现，当前未注册到网关；当前地区检索由 `knowledge_tools.py` 调本地规范 RAG |
| `tool_sources/legacy/region_params_kb.json` | 上述历史工具的空知识库样例数据，当前未被工作流读取 |
| `requirements.txt` | Python 网关、文档生成、OpenSeesPy、LangChain 等依赖 |
| `../dist/index.html` | SteelMind 网页前端：模型/API配置、对话、可编辑参数表、工具及工作流输入输出和 OpenSees 可视化入口 |
| `../tools/build_model_template.mjs` | 生成 `dist/steel_modeling_parameters_template.xlsx` 的 Excel 模板脚本 |
| `../Knowledge/08_规范RAG工具/rag_engine.py` | 本地规范检索核心：检索条文、精确读取条款、材料/型钢参数查询、读取索引 |
| `../Knowledge/08_规范RAG工具/langchain_tools.py` | 将 RAG 检索接口封装成 LangChain 工具 |
| `../Knowledge/08_规范RAG工具/build_index.py`、`build_file_index.py`、`build_corpus.py`、`merge_corpus.py`、`verify_corpus.py` | 构建规范语料、文件索引、合并与校验；属于离线知识库维护工具，不是每次请求都运行 |
| `../Knowledge/08_规范RAG工具/fastapi_router.py`、`http_server.py`、`mcp_server.py` | RAG 的可选 FastAPI 路由、独立 HTTP 和 MCP 入口；SteelMind 当前通过 `knowledge_tools.py` 直接调用检索引擎，不需启动独立 RAG 服务 |
| `../Knowledge/07_机器可读规范库/` | RAG 使用的规范 Markdown、结构化记录和 `standards.db` 索引数据；随项目提交，克隆后可直接供本地网关检索 |

历史工具原件仍保留在 `C:\Users\Administrator\Downloads`，运行服务默认不再依赖该目录。若需临时加载另一份工具源码，可设置 `STEEL_TOOL_SOURCE` 为包含工具 `.py` 文件的目录。`Knowledge/07_机器可读规范库/` 与 `Knowledge/08_规范RAG工具/` 随本项目提交；原始规范资料 `Knowledge/01_规范与基础数据/` 仍按本地资料规则忽略。截面库 JSON 已随源码提交，若要从标准 PDF 重建它，需要另行准备对应 PDF。

## 工作流2 → DesignBundle → 工程成果包

工作流2收敛后，`opensees_frame_verify` 会提供图纸契约需要的实体节点坐标/位移、支座与反力、每根梁柱的实体端点/截面/两端局部内力；验算器提供每个构件的利用率数值与结论。`engineering_drawings.py` 只从这些实际返回值构造模型、荷载、分析和检查记录，并调用 `validate_bundle` 预检。输入引用、数值或必需结果缺失时，工作流3拒绝生成，不使用默认值补成工程数据。

工具 `generate_construction_drawing_package` 的工作流输入为 `{"final_report": <工作流2最终报告>, "options": {"include_pdf": true, "include_dwg": false, "office_timeout_s": 120}}`。内部转换为 DesignBundle 1.0，并由成果组件返回生成状态、数据校核状态、上游验算汇总、草稿标识/原因、警告错误及每个文件的名称、类型、字节数、SHA-256 和网关可下载 URL。可下载内容包括计算书 DOCX、结果 XLSX、二维 DXF/PDF 方案图、审计 JSON 和 ZIP 成果包；缺失 LibreOffice 时计算书 PDF 会明确列为失败，其他已完成产物仍保留，整体状态为 `partial`。

现阶段工作流2只执行单一静力荷载模式，不是规范 ULS/SLS 多工况组合；传入 DesignBundle 的状态明确为 `ANALYSIS`，导出校核因此标为 `INCOMPLETE`/草稿，不会伪装成规范组合。现有构件验算没有结构化返回规范条文号，条文字段保留缺项提示。图纸按该生成器定义属于二维框架方案图，不含节点连接、螺栓/焊缝、基础和面外构造，**不是正式施工图**；须由结构专业人员补齐组合、规范条款和节点设计并审查。

安装新版依赖：

```powershell
conda activate torch
python -m pip install -r "C:\Users\Administrator\Desktop\小论文\AIwork\steel-agent\backend\requirements.txt"
```

本机缺少 LibreOffice 时，计算书 DOCX、结果表 XLSX 和 DXF/PDF 图纸仍可生成；只有计算书 PDF 转换会返回明确错误。需要该 PDF 时另行安装 LibreOffice Writer，并确保服务能找到 `soffice.exe`。

## 工具要求与输出

- 参数校验、荷载组合、钢构件验算、OpenSeesPy 分析、截面绘制和成果生成：使用 LangChain 工具接口；工作流通过 LCEL 编排，分析后自动遍历 OpenSees 返回的物理构件列表。
- 本地截面库 `/sections`、`/sections/{section_id}` 和 `query_steel_sections` 提供合并检索；`catalog_type` 可设为 `hot_rolled_h` 或 `welded_q235`，`series` 可用 `H` 或 `WH`。热轧截面沿用原规范ID；焊接截面使用 `WH-H400x200x8x13` 形式的唯一ID。OpenSees、构件验算、绘图和成果导出读取同一截面记录。原始的同名未加前缀写法在发生冲突时仍指向原热轧截面。
- 单项工具 `optimize_q235_steel_sections` 仅从Q235焊接候选库选截面，接收格式见工具目录中的示例 JSON；也可传 `opensees_result` 或完整分析对象自动展开二维单元端力。该算法输出固定内力下的强度初选，不做整体稳定、局部稳定、长细比、变形、连接与荷载组合，也不会自动重分析；要进入工作流2，需把建议截面纳入模型后重算，并完成其余验算。自动映射的二维结果将弱轴内力和扭矩置零，不能据此声称完整三维验算。
- `draw_steel_section` 根据本地截面库返回尺寸、表列面积/惯性矩、来源与轧制圆角；框架查看器读取同一记录并按截面尺寸绘图，点击构件后展示截面与验算数据。当前图形用 h/b/tw/tf 表示 H 形轮廓，r 作为截面库标注值；不会把示意轮廓声明为制造详图。
- 旧版网架筛选：`/invoke/optimize_steel_truss_members` 暂保留为兼容接口，仅供 ANSYS 后处理导出的钢网架杆件 JSON 使用；不读取 `.rst/.db`。新项目钢框架不要调用此单项网架工具，使用下述“截面迭代与优化”工作流。
- OpenSeesPy 框架验证：需要当前启动网关的 Python 环境已安装 `openseespy`。
- 规范 RAG：`/knowledge/bases` 返回 07 索引的目录与规范清单；网页可多选来源目录，`source_dirs` 会贯通 `/knowledge/search`、单项工具和 LCEL 地区查询，并与可选的 `standard_ids` 进一步取交集。`/invoke/search_steel_standards` 和 `query_region_params` 可由网页及工作流调用。地区查询返回候选原文片段，不自动将其解释为地区参数值；版本、表号、重现期、场地和地方适用条件须人工核对。规范 RAG 数据与代码在 GitHub 源码仓库中；线上静态网页部署包只含 `dist/`，访问者仍需连接已运行的工具网关。
- 计算书、设计文件：默认生成文件保存在 `backend/artifacts/`，返回 `/files/...` 下载链接；如需 Coze S3，请完整配置下面的 S3/identity 变量。`STEEL_TOOL_PUBLIC_URL` 应设置为浏览器能访问到的网关根地址（本机默认 `http://127.0.0.1:8000`）。

### 本地截面库

现有库由 GB/T 11263-2024 附录A表A.1提取，含430个热轧H型钢；新增本地Q235焊接库含311个记录。两份 CSV 的311个型号、尺寸和主截面特性一致，嵌套工具目录内的版本另外含局部稳定筛选说明。热轧记录保存在 `backend/steel_sections.json`，焊接记录从 `backend/tool_sources/截面库.csv` 合并，无需联网或规范 PDF。两库有4个同名型号，但新旧尺寸和惯性矩不同，因此保持两个独立ID，焊接记录加 `WH-` 前缀。查询可用 `GET /sections?limit=1000`、`GET /sections?catalog_type=welded_q235`、`GET /sections/{型号}` 或 `query_steel_sections`；示例 `WH-H400x200x6x10`。

截面目录重建命令（只重建热轧 JSON 核心库；服务启动后会再合并焊接 CSV）：

```powershell
.venv\Scripts\python.exe backend\scripts\build_section_catalog.py
```

当前合并库仅含以上两种来源，不含T型钢、GB/T 706工字钢/槽钢/角钢和钢管。焊接选型算法所述“通过”只覆盖其实现的Q235强度筛选及有限的翼缘几何筛查；腹板稳定、整体稳定和其他设计检查仍需另外完成。热轧型钢表未列腹板剪切面积一阶矩时，`Sx` 使用矩形分解近似，计算报告应保留该假定说明。

## OpenSees → 逐构件验算 → 报告/可视化

在 `/workflow/run` 或 `/workflow/run-stream` 提交模型几何、材料、截面和荷载。建议显式给出每层的分析荷载数组（当前被视为本次静力分析所用荷载，不会自动生成多工况包络）：

```json
{
  "project_name": "钢框架初步验算",
  "geometry": {"bays": 1, "stories": 1, "bay_m": 6, "height_m": 3, "base_support": "fixed"},
  "loads": {"q_by_story_kN_per_m": [10], "lateral_by_story_kN": [5]},
  "material": {"steel_grade": "Q355"},
  "model_sections": {"beam_section": "HN400x200", "column_section": "HW250x250"}
}
```

`opensees_frame_verify` 将每根梁/柱离散为 8 段，返回稳定的构件编号（例如 `B-S1-G1`、`C-S1-G1`）、截面、钢材、几何长度、暂定计算长度、分段端部局部力、轴力/弯矩/剪力包络及构件弦线相对横向变形。工作流将这些值交给 `check_steel_member` 逐根验算，并在结果中提供机器可读 `passed`、验算项明细和计算文字；再将构件验算状态传给 `opensees_frame_visualize` 着色显示。工程文件现在由第三条工作流独立输出。

重要边界：当前分析是二维、线弹性、单次静力工况；弱轴弯矩在平面模型中取 0，轴力按绝对值包络保守传递，计算长度暂按构件几何长度。层间位移角被输出但因未输入项目限值，不自动判定合格。挠度限值使用工具缺省值，须按用途和适用规范核对。当前截面库范围为 GB/T 11263-2024 附录A表A.1热轧H型钢，不包括T、槽钢、角钢、圆/矩形管和焊接自定义截面；型钢表列值用于计算，腹板剪切面积的一阶矩采用矩形近似并在工具中标明。此原型不等同多荷载组合包络、完整 GB 50017 设计验算或工程审查，不能据此作安全结论。

## 三条设计工作流

1. 信息获取与截面初选：`validate_steel_frame_parameters` 检查参数后，执行本地规范 RAG、荷载组合、OpenSees 初算与梁柱候选截面逐构件初筛。初选沿用当前分析内力，必须交给第二条流程重分析，不代表最终通过。
2. 截面迭代与优化：网页调用 `/workflow/section-iteration/run-stream`（同步接口仍为 `/workflow/section-iteration/run`），运行下方所述有界迭代；不在此阶段生成工程文件。可从第一条流程导入逐构件初选截面。
3. 工程文件输出：网页调用 `/workflow/engineering-outputs/run-stream`，只接受第二条流程 `converged` 且每个验算记录都通过的结果，然后依次调用 `generate_calculation_book`、`generate_design_outputs`，生成计算书以及 Excel/Word/DXF 产物。未收敛结果会被拒绝。

### 截面迭代与优化细节

截面迭代工作流由 LCEL 协调以下有界循环：

1. 读取框架几何、线荷载、钢材、初始梁柱截面和梁/柱候选截面序列；
2. 调用 OpenSeesPy，按当前逐构件截面建立平面框架并重新分析；
3. 对 OpenSees 返回的每根梁柱调用 GB 50017 构件验算工具；
4. 首轮遍历候选截面，读取各验算项利用率，优先选择验算通过且最接近目标利用率（默认 0.85）的截面；更新全框架逐构件截面后重新运行 OpenSees；后续若重分析后出现不通过，只向更大截面调整，避免截面来回振荡；
5. 仅当“实际用于最终 OpenSees 分析的截面”逐构件验算均通过时标记 `converged`。候选耗尽、调用失败或迭代上限则返回 `needs_revision`、`failed` 或 `max_iterations`，并附轮次、截面变化、结果可视化与计算书（如工具可用）。

`candidate_sections.beam` 与 `.column` 必须按由轻到重排序，并分别包含初始截面；`target_utilization` 可设为 0.60–0.90，默认 0.85；`max_iterations` 为 1–20，默认 8。示例：

```json
{
  "geometry": {"bays": 1, "stories": 1, "bay_m": 6, "height_m": 3, "base_support": "fixed"},
  "loads": {"q_by_story_kN_per_m": [10], "lateral_by_story_kN": [5]},
  "material": {"steel_grade": "Q355"},
  "model_sections": {"beam_section": "HN400x200", "column_section": "HW250x250"},
  "candidate_sections": {
    "beam": ["HN300x150", "HN350x175", "HN400x200", "HM400x300"],
    "column": ["HW200x200", "HW250x250", "HM300x200", "HM350x250"]
  },
  "target_utilization": 0.85,
  "max_iterations": 8
}
```

这是以利用率目标为引导的离散截面候选筛选与结构重分析，不是包含全局质量目标、构件组约束和多工况包络的连续数学优化器。OpenSees 目前为二维线弹性、单静力工况，轴力取绝对值包络、弱轴弯矩取零、计算长度暂按构件几何长度；钢构件验算器中若干稳定/板件检查仍为筛查性实现。`converged` 只说明该模型输入和已实现检查项未报告失败，不能宣称完整符合规范或直接用于施工。

```powershell
$env:COZE_BUCKET_ENDPOINT_URL = 'https://你的对象存储端点'
$env:COZE_BUCKET_NAME = '你的bucket'
$env:COZE_BUCKET_ACCESS_KEY = '...'
$env:COZE_BUCKET_SECRET_KEY = '...'
$env:COZE_WORKLOAD_IDENTITY_TOKEN = '...'
```

不要把密钥写入源码或提交到 Git。若启用 Coze S3，网关检测到上述配置与 `boto3` 完整可用时才切换到 S3；否则使用本地文件存储。

## 从线上网页访问

线上 HTTPS 页面里的 `127.0.0.1` 指向访问者自己的电脑，不是网站服务器；浏览器也可能阻止 HTTPS 页面访问本地 HTTP 服务。需要在线上使用 Python 工具时，应部署受控的 HTTPS 网关，并将其 URL 填入页面。若跨域来源不同，使用 `STEEL_ALLOWED_ORIGINS` 设置逗号分隔的允许来源。不要把未鉴权的工具网关直接公开到公网。
