# SteelMind Python Tool Gateway

FastAPI 网关会从 `STEEL_TOOL_SOURCE` 加载 Downloads 中的结构工具。`/health` 报告总体连通性，`/tools` 逐项报告依赖是否满足，`/invoke/{tool_name}` 执行单个工具。`/workflow/run-stream` 以 SSE 推送 LangChain 工作流的实时阶段与工具输入输出，`/workflow/run` 保留同步调用。规范 RAG 直接读取项目 `Knowledge/07_机器可读规范库/standards.db`，无需另起 8765 HTTP 服务。

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

- 荷载组合、钢构件验算、OpenSeesPy 分析和成果生成：使用 LangChain 工具接口；整体流程通过 LangChain LCEL 的 `RunnableSequence` 串联，分析后自动遍历 OpenSees 返回的物理构件列表。
- 钢网架 ANSYS 结果截面筛选：`/invoke/optimize_steel_truss_members` 接受 ANSYS 后处理导出的杆件 JSON（不读取 `.rst/.db`），按显式单位制与轴力符号约定逐杆筛查，并从用户给定的候选截面中选取通过项里面积最小者。每根构件需给 `member_id`、`N/Mx/My_weak/Vy/Vz`、`length`、`l0x/l0y`、`candidate_sections`；顶层给 `unit_system`（`N_mm` 或 `kN_m`）、`axial_sign`（`compression_positive` 或 `tension_positive`）和钢材牌号。截面曲线类别、βmx/βb、侧向支承、荷载组合与连接条件须根据真实模型填写；暂不支持复杂双向压弯完整稳定验算，不能将筛查输出作为工程签审结论。
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

`opensees_frame_verify` 将每根梁/柱离散为 8 段，返回稳定的构件编号（例如 `B-S1-G1`、`C-S1-G1`）、截面、钢材、几何长度、暂定计算长度、分段端部局部力、轴力/弯矩/剪力包络及构件弦线相对横向变形。工作流将这些值交给 `check_steel_member` 逐根验算，并在结果中提供机器可读 `passed`、验算项明细和计算文字；再将未通过构件编号传给 `opensees_frame_visualize`，图中以红色标出。完整流程会生成含逐构件验算和汇总的 Word 计算书。若有构件未通过，报告仍生成，流程状态为 `needs_revision`，并跳过定稿设计文件。

重要边界：当前分析是二维、线弹性、单次静力工况；弱轴弯矩在平面模型中取 0，轴力按绝对值包络保守传递，计算长度暂按构件几何长度。层间位移角被输出但因未输入项目限值，不自动判定合格。挠度限值使用工具缺省值，须按用途和适用规范核对。截面属性依赖验算工具内置型钢表。此原型不等同多荷载组合包络、完整 GB 50017 设计验算或工程审查，不能据此作安全结论。

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
