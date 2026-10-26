# SteelMind 计算书与设计文件生成模块

把组员提供的二维钢框架模型、分析结果和验算记录，生成可追溯的计算书、结果表和方案图。无需大模型 API Key。

本模块负责成果生成与数据一致性校核。荷载组合规则、结构分析、构件验算及工程复核由上游负责。**文件生成成功不代表结构验算通过。**

## 快速运行

需要 Python 3.11+ 和 LibreOffice Writer。推荐 Python 3.12。随包提供 Noto 中文字体及 OFL 授权；Linux/macOS 无界面转换自动配置该字体，Windows 请先安装随包字体，或指定系统已安装的中文字体。在 Word/CAD 中编辑时也建议安装该字体。

```sh
python -m venv .venv
# macOS / Linux
. .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
steelmind-export validate examples/demo.json
steelmind-export build examples/demo.json --output runs
```

每次生成创建一个新的运行子目录，控制台返回 JSON，其中 `output_dir` 为实际成果目录。`--no-pdf` 可在未安装 LibreOffice 时生成 DOCX、XLSX、DXF；`--dwg` 显式请求 ODA 转换。

三层两跨演示数据包含一项故意设置的 FAIL，结果保留此结论。`examples/analytic.json` 是简支梁解析基准，`examples/minimal.json` 是仅几何输入；它们都不构成完整钢框架规范验算。

## 服务运行

```sh
python -m uvicorn steelmind_export.api:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/docs` 查看交互接口；`/openapi.json` 为实时接口定义，`/healthz` 用于检查进程。服务默认不配置跨域；由小组网关代理同源请求，或由网关明确设置允许的前端来源。

```sh
docker compose up --build
```

Docker 镜像包含 LibreOffice 与 Noto 中文字体，数据保存在命名卷。默认端口只映射到本机。公网接入所需的身份验证及访问策略由部署网关负责。

## Python 调用

```python
import json
from steelmind_export import validate_bundle, generate_package

bundle = json.load(open("examples/demo.json", encoding="utf-8"))
report = validate_bundle(bundle)
if not report.valid:
    raise ValueError(report.model_dump())
result = generate_package(bundle, options={"include_pdf": True}, output_dir="runs")
print(result.generation_status, result.upstream_check_summary, result.output_dir)
```

同时提供 `generate_calculation_book`、`generate_design_files`，两者与 `generate_package` 使用相同的参数和返回类型。参数 `output_dir` 是运行目录的父目录。

## 文件与状态

- 计算书：可编辑 DOCX，以及从该 DOCX 转换的 PDF。
- 结果表：XLSX，保留模型、荷载、组合、分析及验算记录。
- 方案图：可编辑 DXF、从其纸空间布局渲染的 PDF，以及可选 DWG。
- 追溯：输入、规范化输入、校核记录、追溯数据、生成日志及文件清单。
- ZIP：本次成果与清单。清单和 ZIP 不包含自己的哈希，外层 `result.json`/API 返回二者哈希，避免循环依赖。

| 字段 | 含义 |
|---|---|
| `generation_status` | `success` 所请求文件均生成；`partial` 部分失败但有成果；`failed` 未生成主要成果 |
| `data_validation_status` | 输入结构、引用和可校核数值是否有效 |
| `upstream_check_summary` | 已提供验算项的 `PASS` / `FAIL` / `INCOMPLETE` 汇总，不是独立工程验证 |
| `draft` / `draft_reasons` | 演示数据、覆盖缺项或依据不足等草稿原因 |

校核失败时不创建运行目录。缺少 PDF/DWG 转换依赖时保留已有文件并返回明确错误。验算 FAIL 不会使导出失败，也不会被导出过程改成 PASS。

## 环境配置

| 环境变量 | 用途 |
|---|---|
| `STEELMIND_OUTPUT_ROOT` | HTTP 服务的成果根目录，默认当前目录下 `runs` |
| `STEELMIND_FONT` | 中文 TTF/TTC 字体绝对路径 |
| `STEELMIND_FONT_FAMILY` | 与字体相符的 Word 字体名；未设置时读取字体名称 |
| `STEELMIND_SOFFICE` | LibreOffice `soffice` 可执行文件路径 |
| `STEELMIND_ODA` / `ODA_FILE_CONVERTER` | 可选 ODA File Converter 路径 |
| `MPLCONFIGDIR` | 服务器上可写的 Matplotlib 缓存目录 |

默认字体位于 `src/steelmind_export/assets/fonts/`。LibreOffice 转换使用独立的字体配置，不修改系统字体目录。也可指定其他中文字体。若指定了不存在的字体，本次导出将明确报错，不悄悄替换。字体跨机器移交时需保留授权和安装说明。

## 接入与验证

阅读 [接口交接说明](docs/HANDOFF.md)、[单位与正负号](docs/CONVENTIONS.md) 和 [验收记录](docs/ACCEPTANCE.md)。`docs/design-bundle.schema.json` 与 `docs/openapi.json` 从实际代码导出。

```sh
python -m pytest
steelmind-export schema --output docs/design-bundle.schema.json
```

项目首版只支持节点轴线相交的等截面二维直杆及 H/I 截面。偏心、刚域、端部偏移、变截面、连接节点和三维模型应由其他模块处理，不能隐含简化后宣称已覆盖。

工作流组如需复现已验证的 LangChain 环境，可安装 `requirements-langchain.lock`；其他组员无需安装该可选依赖。
