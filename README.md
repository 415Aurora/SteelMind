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

Token 由使用者在页面中输入，只存储在当前浏览器会话的 `sessionStorage`，不会写入源代码。生产环境建议下一步增加后端代理，把 Token 放进站点的运行时密钥，而不是让浏览器直连模型服务。

## 后续扩展路线

- Python/FastAPI 工具服务：截面库、荷载组合、构件验算、OpenSeesPy 分析。
- 文档/规范检索：上传项目资料，建立版本化知识库和引用链。
- 任务编排：把“需求澄清—建模—分析—验算—报告”拆成可追踪节点。
- 权限与项目存储：用户、项目、计算文件、日志和报告的持久化。
