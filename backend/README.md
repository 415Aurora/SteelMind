# SteelMind Python Tool Gateway

这个小型 FastAPI 服务把 `Downloads` 目录中的四个用户工具统一成 HTTP 接口，网页前端通过 `Tool Gateway URL` 调用它。

## 启动

```powershell
conda activate torch
$env:STEEL_TOOL_SOURCE = 'C:\Users\Administrator\Downloads'
python -m uvicorn app:app --app-dir 'C:\Users\Administrator\Desktop\小论文\AIwork\steel-agent\backend' --host 0.0.0.0 --port 8000
```

打开网站后，将工具服务地址设置为 `http://127.0.0.1:8000`，点击“检查工具服务”。

## 接口

- `GET /health`：查看工具加载状态与依赖错误。
- `GET /tools`：查看允许调用的工具列表。
- `POST /invoke/{tool_name}`：请求体为 `{ "payload": { ... } }`，工具内部仍接收 JSON 字符串。

工具网关只允许四个文件中声明的六个工具名。地区参数检索、计算书和设计文件工具还依赖 Coze SDK/S3 配置；若依赖未安装，服务会在 `/health` 中报告具体原因，不会静默伪造结果。
