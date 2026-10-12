# SteelMind Python Tool Gateway

这个小型 FastAPI 服务把 `Downloads` 目录中的四个用户工具统一成 HTTP 接口，网页前端通过 `Tool Gateway URL` 调用它。

其中 `s3_storage.py` 提供 Coze 兼容的 S3 存储实现。文件生成工具会把 Excel、Word、DXF 上传后返回签名下载地址。

## 启动

```powershell
conda activate torch
$env:STEEL_TOOL_SOURCE = 'C:\Users\Administrator\Downloads'
# 如需启用文件上传，按 backend/.env.example 设置以下变量
$env:COZE_BUCKET_ENDPOINT_URL = 'https://...'
$env:COZE_BUCKET_NAME = '...'
$env:COZE_BUCKET_ACCESS_KEY = '...'
$env:COZE_BUCKET_SECRET_KEY = '...'
$env:COZE_WORKLOAD_IDENTITY_TOKEN = '...'
python -m uvicorn app:app --app-dir 'C:\Users\Administrator\Desktop\小论文\AIwork\steel-agent\backend' --host 0.0.0.0 --port 8000
```

打开网站后，将工具服务地址设置为 `http://127.0.0.1:8000`，点击“检查工具服务”。

## 接口

- `GET /health`：查看工具加载状态与依赖错误。
- `GET /tools`：查看允许调用的工具列表。
- `POST /invoke/{tool_name}`：请求体为 `{ "payload": { ... } }`，工具内部仍接收 JSON 字符串。

工具网关只允许四个文件中声明的六个工具名。地区参数检索还需要 Coze SearchClient；计算书和设计文件工具需要 `boto3` 以及上述 S3/identity 配置。若配置未完成，服务会在 `/health` 中报告具体原因，不会静默伪造结果。
