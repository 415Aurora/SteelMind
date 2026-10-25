# SteelMind Python Tool Gateway

FastAPI 网关会从 `STEEL_TOOL_SOURCE` 加载 Downloads 中的结构工具。`/health` 报告总体连通性，`/tools` 逐项报告依赖是否满足，`/invoke/{tool_name}` 执行单个工具。网页将设计拆为三条 LCEL 工作流：`/workflow/information-selection/run-stream` 信息获取与截面初选、`/workflow/section-iteration/run-stream` 截面迭代与优化、`/workflow/engineering-outputs/run-stream` 工程文件输出；各接口以 SSE 推送实际工具输入/输出。规范 RAG 直接读取项目 `Knowledge/07_机器可读规范库/standards.db`，无需另起 8765 HTTP 服务。

## 启动

在安装了 Python 依赖的 Anaconda Prompt / PowerShell 中运行：

```powershell
conda activate torch
python -m pip install -r "C:\Users\Administrator\Desktop\小论文\AIwork\steel-agent\backend\requirements.txt"
$env:STEEL_TOOL_SOURCE = 'C:\Users\Administrator\Downloads'
python -m uvicorn app:app --app-dir 'C:\Users\Administrator\Desktop\小论文\AIwork\steel-agent\backend' --host 127.0.0.1 --port 8000
```

服务启动后先在浏览器打开 `http://127.0.0.1:8000/health`，再回到 SteelMind 点“检查工具服务”。本机服务绑定 loopback，避免默认暴露到局域网。

## 工具要求与输出

- 参数校验、荷载组合、钢构件验算、OpenSeesPy 分析和成果生成：使用 LangChain 工具接口；工作流通过 LCEL 编排，分析后自动遍历 OpenSees 返回的物理构件列表。
- 旧版网架筛选：`/invoke/optimize_steel_truss_members` 暂保留为兼容接口，仅供 ANSYS 后处理导出的钢网架杆件 JSON 使用；不读取 `.rst/.db`。新项目钢框架不要调用此单项网架工具，使用下述“截面迭代与优化”工作流。
- OpenSeesPy 框架验证：需要当前启动网关的 Python 环境已安装 `openseespy`。
- 规范 RAG：`/knowledge/bases` 返回 07 索引的目录与规范清单；网页可多选来源目录，`source_dirs` 会贯通 `/knowledge/search`、单项工具和 LCEL 地区查询，并与可选的 `standard_ids` 进一步取交集。`/invoke/search_steel_standards` 和 `query_region_params` 可由网页及工作流调用。地区查询返回候选原文片段，不自动将其解释为地区参数值；版本、表号、重现期、场地和地方适用条件须人工核对。`Knowledge/` 为本地知识库目录，已加入 Git 忽略规则，网页部署包不会包含规范原文和数据库。
- 计算书、设计文件：默认生成文件保存在 `backend/artifacts/`，返回 `/files/...` 下载链接；如需 Coze S3，请完整配置下面的 S3/identity 变量。`STEEL_TOOL_PUBLIC_URL` 应设置为浏览器能访问到的网关根地址（本机默认 `http://127.0.0.1:8000`）。

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

重要边界：当前分析是二维、线弹性、单次静力工况；弱轴弯矩在平面模型中取 0，轴力按绝对值包络保守传递，计算长度暂按构件几何长度。层间位移角被输出但因未输入项目限值，不自动判定合格。挠度限值使用工具缺省值，须按用途和适用规范核对。截面属性依赖验算工具内置型钢表。此原型不等同多荷载组合包络、完整 GB 50017 设计验算或工程审查，不能据此作安全结论。

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
