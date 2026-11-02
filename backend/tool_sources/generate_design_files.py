"""钢结构框架设计产物生成工具。

生成并上传三个产物：
1. 关键设计参数表 (Excel .xlsx)
2. 方案说明书 (Word .docx)
3. 结构简图 (DXF, 可被 AutoCAD/中望CAD 打开)
产物统一通过对象存储托管，返回签名下载 URL。
"""

from __future__ import annotations

import io
import json
import os
from typing import Dict, Any

from langchain.tools import tool

from coze_coding_utils.log.write_log import request_context
from coze_coding_utils.runtime_ctx.context import new_context
from coze_coding_dev_sdk.s3 import S3SyncStorage

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side


def _get_storage():
    return S3SyncStorage(
        endpoint_url=os.getenv("COZE_BUCKET_ENDPOINT_URL"),
        access_key="",
        secret_key="",
        bucket_name=os.getenv("COZE_BUCKET_NAME"),
        region="cn-beijing",
    )


def _upload_file(storage, data: bytes, name: str, content_type: str) -> str:
    key = storage.upload_file(file_content=data, file_name=name, content_type=content_type)
    url = storage.generate_presigned_url(key=key, expire_time=86400)
    return url


def _build_excel(data: Dict[str, Any]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "关键设计参数"
    title_font = Font(bold=True, size=14, color="FFFFFF")
    title_fill = PatternFill("solid", fgColor="1F4E79")
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="4472C4")
    thin = Side(style="thin", color="999999")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # 标题
    ws.cell(1, 1, f"钢结构框架关键设计参数表 - {data.get('project_name', '结构设计')}")
    for c in range(1, 7):
        cell = ws.cell(1, c)
        cell.font = title_font
        cell.fill = title_fill
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)

    sections = data.get("sections", [])
    row = 3
    for sec in sections:
        title = sec.get("title", "")
        ws.cell(row, 1, title)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        ws.cell(row, 1).font = Font(bold=True, size=12)
        row += 1
        items = sec.get("items", [])
        # 表头
        for j, h in enumerate(["参数", "符号/单位", "取值", "依据规范/说明"], start=1):
            cell = ws.cell(row, j, h)
            cell.font = head_font
            cell.fill = head_fill
            cell.border = border
        row += 1
        for it in items:
            ws.cell(row, 1, it.get("name", "")).border = border
            ws.cell(row, 2, it.get("symbol", "")).border = border
            ws.cell(row, 3, str(it.get("value", ""))).border = border
            ws.cell(row, 4, it.get("note", "")).border = border
            row += 1
        row += 1

    widths = [28, 16, 16, 48]
    for j, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(j)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _build_docx(data: Dict[str, Any]) -> bytes:
    import docx
    from docx.shared import Pt
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    doc = docx.Document()
    title = doc.add_heading(f"{data.get('project_name', '钢结构框架')}结构方案说明书", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for sec in data.get("sections", []):
        doc.add_heading(sec.get("title", ""), level=1)
        for it in sec.get("items", []):
            p = doc.add_paragraph()
            r = p.add_run(f"{it.get('name', '')}（{it.get('symbol', '')}）：")
            r.bold = True
            p.add_run(f"{it.get('value', '')}")
            p.add_run(f"  — {it.get('note', '')}")

    if data.get("conclusion"):
        doc.add_heading("结论与建议", level=1)
        doc.add_paragraph(data["conclusion"])

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _build_dxf(data: Dict[str, Any]) -> bytes:
    """生成门式/多层钢框架立面简图的 DXF (AutoCAD R12 ASCII)。"""
    bays = int(data.get("bays", 2))
    height_m = float(data.get("height_m", 6))
    bay_m = float(data.get("bay_m", 6))
    origin_x, origin_y = 0.0, -2.0  # 基础底标高原点
    scale = 60  # m -> mm 到绘图单位的缩放(图面比例)

    lines = []
    entities = []
    entity_count = 0

    # 柱
    for i in range(bays + 1):
        x = origin_x + i * bay_m
        entities.append(
            f"  0\nLINE\n  8\nGJXHI\n 10\n{x*scale:.1f}\n 20\n{origin_y*scale:.1f}\n 30\n0\n"
            f" 11\n{x*scale:.1f}\n 21\n{height_m*scale:.1f}\n 31\n0\n")
        entity_count += 1
    # 梁（各层）
    for layer in range(1, int(height_m / 3) + 1 if height_m > 3 else 1):
        y = origin_y + layer * 3.0 if height_m > 3 else height_m
        if y > height_m + origin_y:
            y = height_m + origin_y
        entities.append(
            f"  0\nLINE\n  8\nGJXHI\n 10\n{origin_x*scale:.1f}\n 20\n{y*scale:.1f}\n 30\n0\n"
            f" 11\n{(origin_x+bays*bay_m)*scale:.1f}\n 21\n{y*scale:.1f}\n 31\n0\n")
        entity_count += 1
    # 顶部横梁
    entities.append(
        f"  0\nLINE\n  8\nGJXHI\n 10\n{origin_x*scale:.1f}\n 20\n{height_m*scale:.1f}\n 30\n0\n"
        f" 11\n{(origin_x+bays*bay_m)*scale:.1f}\n 21\n{height_m*scale:.1f}\n 31\n0\n")
    entity_count += 1
    # 基础示意
    for i in range(bays + 1):
        x = origin_x + i * bay_m
        entities.append(
            f"  0\nLINE\n  8\nJC\n 10\n{(x-0.6)*scale:.1f}\n 20\n{origin_y*scale:.1f}\n 30\n0\n"
            f" 11\n{(x+0.6)*scale:.1f}\n 21\n{origin_y*scale:.1f}\n 31\n0\n")
        entity_count += 1

    header = (
        "0\nSECTION\n  2\nHEADER\n  9\n$ACADVER\n  1\nAC1009\n  0\nENDSEC\n"
        "0\nSECTION\n  2\nTABLES\n  0\nTABLE\n  2\nLTYPE\n  0\nENDTAB\n"
        "  0\nTABLE\n  2\nLAYER\n"
        "  0\nLAYER\n  2\nGJXHI\n 70\n0\n 62\n7\n  6\nCONTINUOUS\n"
        "  0\nLAYER\n  2\nJC\n 70\n0\n 62\n1\n  6\nCONTINUOUS\n"
        "  0\nENDTAB\n  0\nTABLE\n  2\nSTYLE\n  0\nENDTAB\n  0\nENDTAB\n  0\nENDSEC\n"
    )
    block = (
        "0\nSECTION\n  2\nBLOCKS\n  0\nENDSEC\n"
        "0\nSECTION\n  2\nENTITIES\n"
    )
    footer = "  0\nENDSEC\n  0\nEOF\n"

    content = header + block + "".join(entities) + footer
    return content.encode("ascii")


@tool
def generate_calculation_book(payload: str) -> str:
    """将已获得的工程输入、荷载、OpenSees 结果和逐构件验算写入 DOCX 并返回下载链接。

    传入 JSON 字符串，字段：
    {
      "project_name": 项目名称,
      "chapters": [
        {"title": 章节标题, "body": 多行文本(含公式/表格说明)},
        ...
      ],
      "conclusion": 结论(可选)
    }
    输出为可编辑的结果归档。只整理输入和工具返回值，不补算缺失结果，也不代表正式审查结论。
    """
    ctx = request_context.get() or new_context(method="generate_calculation_book")
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except Exception as e:
        return json.dumps({"ok": False, "error": f"JSON 解析失败: {e}"}, ensure_ascii=False)

    import docx
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    doc = docx.Document()
    title = doc.add_heading(f"{data.get('project_name', '钢结构')}结构计算书", level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph("运行结果归档 · 可编辑 DOCX · 需专业工程师复核")

    def scalar_text(value):
        if value is None or value == "" or value == [] or value == {}:
            return "待补充"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, allow_nan=False)
        return str(value)

    def add_value(label, value, depth=2):
        level = min(max(depth, 2), 3)
        if isinstance(value, dict):
            doc.add_heading(str(label), level=level)
            if not value:
                doc.add_paragraph("待补充")
            for key, item in value.items():
                add_value(str(key), item, depth + 1)
            return
        if isinstance(value, list):
            doc.add_heading(f"{label}（{len(value)} 项）", level=level)
            if value and all(isinstance(item, dict) for item in value):
                headers = list(dict.fromkeys(key for item in value for key in item))
                table = doc.add_table(rows=1, cols=max(1, len(headers)))
                table.style = "Table Grid"
                for cell, key in zip(table.rows[0].cells, headers):
                    cell.text = str(key)
                for item in value:
                    cells = table.add_row().cells
                    for cell, key in zip(cells, headers):
                        cell.text = scalar_text(item.get(key))
            elif value:
                for item in value:
                    doc.add_paragraph(scalar_text(item), style="List Bullet")
            else:
                doc.add_paragraph("待补充")
            return
        paragraph = doc.add_paragraph()
        run = paragraph.add_run(f"{label}：")
        run.bold = True
        paragraph.add_run(scalar_text(value))

    def parse_structured(value):
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value

    chapters = data.get("chapters") or []
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        doc.add_heading(str(chapter.get("title") or "计算结果"), level=1)
        body = chapter.get("body")
        structured = parse_structured(body)
        if isinstance(structured, (dict, list)):
            add_value("数据记录", structured)
        else:
            for line in str(body or "待补充").splitlines():
                line = line.strip()
                if line.startswith("### "):
                    doc.add_heading(line[4:], level=2)
                elif line.startswith("## "):
                    doc.add_heading(line[3:], level=1)
                elif line:
                    doc.add_paragraph(line)

    # Include numeric outputs as native tables, rather than leaving them only
    # in the chat transcript or flattening the report to chapter placeholders.
    for key, label in (("model_parameters", "模型与输入参数"), ("load_results", "荷载组合结果"),
                       ("analysis_results", "OpenSees 分析结果"), ("member_checks", "逐构件验算结果"),
                       ("iteration_history", "截面迭代记录")):
        value = data.get(key)
        if value not in (None, "", [], {}):
            doc.add_heading(label, level=1)
            add_value(label, parse_structured(value), depth=2)

    if data.get("conclusion"):
        doc.add_heading("结论与适用边界", level=1)
        doc.add_paragraph(str(data["conclusion"]))
    for section in doc.sections:
        section.left_margin = section.right_margin = docx.shared.Cm(2.0)
    normal = doc.styles["Normal"]
    normal.font.name = "Microsoft YaHei"
    normal.font.size = Pt(10)
    normal._element.rPr.rFonts.set(docx.oxml.ns.qn("w:eastAsia"), "Microsoft YaHei")

    buf = io.BytesIO()
    doc.save(buf)
    content = buf.getvalue()
    try:
        storage = _get_storage()
        filename = f"{data.get('project_name', '钢结构')}_计算书.docx"
        url = _upload_file(
            storage, content, filename,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        return json.dumps({"ok": True, "summary": f"已将运行输入与计算结果写入 DOCX（{len(chapters)} 个章节）。",
                           "artifacts": [{"kind": "calculation_book", "name": filename,
                                          "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                          "url": url}],
                           "included": [key for key in ("model_parameters", "load_results", "analysis_results", "member_checks", "iteration_history") if data.get(key) not in (None, "", [], {})]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"上传结构计算书失败: {e}"}, ensure_ascii=False)


@tool
def generate_design_outputs(payload: str) -> str:
    """根据结构设计结果生成关键设计参数表(Excel)、方案说明书(Word)、结构简图(DXF)并上传，返回下载 URL。

    传入 JSON 字符串，字段：
    {
      "project_name": 项目名称,
      "bays": 跨数,
      "bay_m": 柱距(米),
      "height_m": 檐口/总高(米),
      "sections": [
         {"title": 标题, "items": [{"name","symbol","value","note"}]},
         ...
      ],
      "conclusion": 结论说明(可选)
    }
    """
    ctx = request_context.get() or new_context(method="generate_design_outputs")
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except Exception as e:
        return f"JSON 解析失败: {e}"

    try:
        storage = _get_storage()
        excel_url = _upload_file(
            storage, _build_excel(data), "design_parameters.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        docx_url = _upload_file(
            storage, _build_docx(data), "design_description.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        dxf_data = _build_dxf(data)
        dxf_url = _upload_file(storage, dxf_data, "structural_layout.dxf", "application/dxf")

        return json.dumps({"ok": True, "summary": "设计文件已生成。DXF 为可下载 CAD 文件，不在对话中展开源码。",
                           "artifacts": [
                               {"kind": "design_parameters", "name": "design_parameters.xlsx",
                                "media_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "url": excel_url},
                               {"kind": "design_description", "name": "design_description.docx",
                                "media_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "url": docx_url},
                               {"kind": "drawing", "name": "structural_layout.dxf",
                                "media_type": "application/dxf", "url": dxf_url},
                           ]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"生成/上传设计产物失败: {e}"}, ensure_ascii=False)
