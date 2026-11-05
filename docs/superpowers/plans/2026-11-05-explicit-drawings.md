# 龙岩显式模型出图链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task.

**Goal:** 从案例真实XYZ杆系生成可下载、可预览、可审查的方案图册并接入工作流2/3。

**Architecture:** 新建explicit_cad.py，沿用现有ezdxf A3/DIMENSION/PDF工具。按原Z竖向直接提取XY层平面、XZ/YZ立面，不把整座三维模型压扁；平面柱符号取该标高下侧真实构件。PDF只从保存后重读的DXF布局渲染。

**Tech Stack:** 已安装ezdxf、matplotlib、pypdf、中文字体；不新增全局依赖。

**Spec:** 本会话已确认的仅框架自重案例和docs/龙岩显式模型修复.md。

- [x] 添加失败测试：平面/立面覆盖248构件、真实尺寸、H/BOX形状、单位/比例和2.5mm纸面文字。
- [x] 实现二维切片、支座/释放、构件表、截面图、PDF合册及出图质量JSON；原XYZ DXF保留。
- [x] 接入显式成果包，给二维DXF正确preview_mode；PDF/出图失败须标partial并保留已生成成果。
- [x] 修复网页从工作流2/3预览二维DXF及聊天优先返回二维图。
- [x] 实际API/下载/浏览器解析/逐页PDF检查，并更新案例包与交接说明。

约束：几何与权威截面属性不得静默替换；图纸均标方案草稿/非施工图和INCOMPLETE，不推定连接、楼板、偏心或刚域；保留现有尚未提交修改。

验收：216项回归通过；真实36项下载哈希通过；17张二维DXF通过浏览器解析，覆盖248原编号，Safari实测层平面载入成功。25页PDF逐页渲染检查。复核提出的一般旋转柱外轮廓问题已通过模型局部轴绘制并增加45度回归。
