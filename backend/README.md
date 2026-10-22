# SteelMind Python Tool Gateway

FastAPI 网关会从 `STEEL_TOOL_SOURCE` 加载 Downloads 中的结构工具。`/health` 报告总体连通性，`/tools` 逐项报告依赖是否满足，`/invoke/{tool_name}` 执行单个工具。`/workflow/run-stream` 以 SSE 推送 LangChain 工作流的实时阶段与工具输入输出，`/workflow/run` 保留同步调用。

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

- 荷载组合、钢构件验算、OpenSeesPy 分析和成果生成：使用 LangChain 工具接口；整体流程通过 LangChain LCEL 的 `RunnableSequence` 串联，并以 `RunnableLambda` 实现受限的候选截面迭代。
- OpenSeesPy 框架验证：需要当前启动网关的 Python 环境已安装 `openseespy`。
- 地区参数查询：`region_params.py` 只读取 `C:\Users\Administrator\Downloads\region_params_kb.json`（或 `STEEL_REGION_KB_PATH` 指定的本地 JSON），不依赖 Coze SearchClient，也不进行联网查询。每个返回值必须有规范、条款/表号和核验日期；未录入、来源不完整或安全等级等非地区信息会明确标为待补充/需项目判断。字段定义、维护流程和空模板见 Downloads 目录下的 `region_params_kb_README.md` 与 `region_params_kb.json`。
- 计算书、设计文件：默认生成文件保存在 `backend/artifacts/`，返回 `/files/...` 下载链接；如需 Coze S3，请完整配置下面的 S3/identity 变量。`STEEL_TOOL_PUBLIC_URL` 应设置为浏览器能访问到的网关根地址（本机默认 `http://127.0.0.1:8000`）。

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
