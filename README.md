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
