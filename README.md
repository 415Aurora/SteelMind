# SteelMind 钢结构智能设计助手

这是一个可通过网页访问的初版智能体前端。当前版本采用静态 HTML/JavaScript，支持 OpenAI-compatible `POST /chat/completions` 接口。

## 本地运行

在 `dist` 目录启动静态服务器：

```powershell
cd .\steel-agent
python -m http.server 8080 --directory dist
```

然后打开 `http://localhost:8080`。

## Token 与安全

DeepSeek API Key 由使用者在页面中输入，只留在当前页面内存，不写入 `sessionStorage` 或源代码。聊天使用 OpenAI-compatible SSE 流式输出，生成中可点击“停止回答”中止当前请求。

Python 工具由独立 FastAPI 网关提供，参阅 `backend/README.md`。线上网页填写的 `127.0.0.1` 指向访问者自己的电脑；公网使用需部署可访问的 HTTPS 网关，并配置来源白名单与服务端依赖。

## 后续扩展路线

- Python/FastAPI 工具服务：截面库、荷载组合、构件验算、OpenSeesPy 分析。
- 文档/规范检索：上传项目资料，建立版本化知识库和引用链。
- 任务编排：把“需求澄清—建模—分析—验算—报告”拆成可追踪节点。
- 权限与项目存储：用户、项目、计算文件、日志和报告的持久化。
