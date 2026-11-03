# Spatial export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 工作流2真实三维最终结果能通过工作流3生成可下载、可追溯的计算书和方案图。
**Architecture:** 独立三维适配器和生成模块，现有工具内按模型维度路由；二维模型与函数保持兼容。统一规范化数据供报告/CAD/清单消费。
**Tech Stack:** 已安装 Python、python-docx、openpyxl、ezdxf、LibreOffice、FastAPI；不安装全局依赖。
**Spec:** docs/superpowers/specs/2026-11-03-spatial-export-design.md

## Global Constraints

- Y 为竖向；局部轴及作用力保持 OpenSees 上游约定。
- 不补造公式/规范；三维方案始终保留草稿/INCOMPLETE。
- 二维 DesignBundle v1.0 不改变；每次生成独立目录。

## Review Focus

- 校验重复编号、非有限数据、节点引用及截面结果不一致。
- 无Z方向丢失；全部三维构件能在图纸索引追溯。
- 缺少转换器、已失败验算不得返回虚假成功。
- 前端加载没有扩展名的下载地址、配套二维图与三维原始图的正确入口。
- 多层多跨、长表、中文排版和尺寸块完整保留。

### Task 1 契约及预检
Files: tool_sources/spatial_export.py, tests/test_spatial_export.py, tool_sources/engineering_drawings.py
- [x] RED：真实三维报告预检应有效，畸形数据应被拒绝。
- [x] 实现 is_spatial_report、normalize_spatial_report、inspect_spatial_report；增加路由。
- [x] GREEN：覆盖几何、引用、有限值、逐构件截面和验算一致性。

### Task 2 成果生成
Files: tool_sources/spatial_reports.py, tool_sources/spatial_cad.py, tool_sources/spatial_export.py
- [x] RED：XYZ、杆端力和利用率跨DOCX/XLSX/DXF/JSON一致，审查DXF实体及mm尺寸。
- [x] 生成报告、真实三维与分面图、PDF、审计清单及ZIP；转换异常返回partial。
- [x] GREEN：真实多层多跨案例生成、逐页渲染检查。

### Task 3 工作流与网页
Files: workflow.py, tool_sources/engineering_drawings.py, dist/index.html, verify.py, tests/test-cad-artifacts.cjs
- [x] RED：三维工作流3能下载有效DXF和DOCX，预览入口保留文件名元数据。
- [x] 接入原工具，自动生成与聊天入口复用；复杂DXF原样下载。
- [x] GREEN：端到端输入、分析、迭代、成果生成、下载哈希及前端回归。

### Task 4 交接
- [x] 更新运行验证、字段及三维限制说明，导出示例成果和源码压缩包。
- [x] 完成最终审查，记录测试证据和未实现项。

本项目是ZIP隔离副本，无Git元数据。先备份project和verify.py，再原地实施；不伪造commit/push。
