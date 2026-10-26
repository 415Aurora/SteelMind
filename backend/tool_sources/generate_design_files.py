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
    """生成完整的钢结构结构计算书(Word)，并上传返回下载 URL。

    传入 JSON 字符串，字段：
    {
      "project_name": 项目名称,
      "chapters": [
        {"title": 章节标题, "body": 多行文本(含公式/表格说明)},
        ...
      ],
      "conclusion": 结论(可选)
    }
    输出覆盖设计依据、荷载组合、构件验算、有限元验证等章节的正式计算书。
    """
    ctx = request_context.get() or new_context(method="generate_calculation_book")
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except Exception as e:
        return f"JSON 解析失败: {e}"

    import docx
    from docx.shared import Pt

    doc = docx.Document()
    title = doc.add_heading(f"{data.get('project_name', '钢结构')}结构计算书", level=0)
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    for ch in data.get("chapters", []):
        doc.add_heading(ch.get("title", ""), level=1)
        body = (ch.get("body") or "").strip()
        for para in body.split("\n"):
            para = para.strip()
            if not para:
                continue
            if para.startswith("### "):
                doc.add_heading(para[4:].strip(), level=2)
            elif para.startswith("## "):
                doc.add_heading(para[3:].strip(), level=1)
            elif para.startswith("# "):
                doc.add_heading(para[2:].strip(), level=0)
            else:
                doc.add_paragraph(para)

    if data.get("conclusion"):
        doc.add_heading("结论", level=1)
        doc.add_paragraph(data["conclusion"])

    buf = io.BytesIO()
    doc.save(buf)
    try:
        storage = _get_storage()
        url = _upload_file(
            storage, buf.getvalue(), "structural_calculation_book.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        return f"结构计算书已生成并上传：{url}"
    except Exception as e:
        return f"上传结构计算书失败: {e}"


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

        return (
            "设计产物已生成并上传：\n"
            f"- 关键设计参数表: {excel_url}\n"
            f"- 方案说明书: {docx_url}\n"
            f"- 结构简图(DXF): {dxf_url}\n"
            "（DXF 请用 AutoCAD/中望CAD/浩辰CAD 打开编辑为正式图纸）"
        )
    except Exception as e:
        return f"生成/上传设计产物失败: {e}"
