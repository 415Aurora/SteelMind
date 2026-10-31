from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "SteelMind设计说明书.md"
OUTPUT = ROOT / "SteelMind设计说明书.docx"


def set_font(run, name="宋体", size=10.5, color="263445", bold=None):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    run.font.size = Pt(size)
    run.font.color.rgb = RGBColor.from_string(color)
    if bold is not None:
        run.bold = bold


def shade(cell, fill):
    props = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    props.append(shd)


def build():
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(2.0)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.25)
    section.right_margin = Cm(2.25)

    normal = doc.styles["Normal"]
    normal.font.name = "宋体"
    normal._element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
    normal.font.size = Pt(10.5)
    normal.font.color.rgb = RGBColor(38, 52, 69)
    normal.paragraph_format.space_after = Pt(5)
    normal.paragraph_format.line_spacing = 1.18
    for style_name, size, color in [("Heading 1", 16, "0C746F"), ("Heading 2", 13, "163B59"), ("Heading 3", 11.5, "0C746F")]:
        style = doc.styles[style_name]
        style.font.name = "黑体"
        style._element.rPr.rFonts.set(qn("w:eastAsia"), "黑体")
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.space_before = Pt(11 if style_name != "Heading 3" else 7)
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.keep_with_next = True
    title_ppr = doc.styles["Title"]._element.get_or_add_pPr()
    title_border = title_ppr.find(qn("w:pBdr"))
    if title_border is not None:
        title_ppr.remove(title_border)

    i = 0
    title_seen = False
    while i < len(lines):
        raw = lines[i]
        line = raw.strip()
        if not line:
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [x.strip() for x in lines[i].strip().strip("|").split("|")]
                if not all(set(c.replace(":", "").replace("-", "")) == set() for c in cells):
                    rows.append(cells)
                i += 1
            if rows:
                cols = max(map(len, rows))
                table = doc.add_table(rows=0, cols=cols)
                table.style = "Table Grid"
                table.autofit = True
                for row_index, row in enumerate(rows):
                    table_row = table.add_row()
                    tr_pr = table_row._tr.get_or_add_trPr()
                    cant_split = OxmlElement("w:cantSplit")
                    tr_pr.append(cant_split)
                    if row_index == 0:
                        repeat_header = OxmlElement("w:tblHeader")
                        repeat_header.set(qn("w:val"), "true")
                        tr_pr.append(repeat_header)
                    cells = table_row.cells
                    for j, cell in enumerate(cells):
                        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                        value = row[j] if j < len(row) else ""
                        p = cell.paragraphs[0]
                        p.paragraph_format.space_after = Pt(2)
                        if row_index == 0:
                            p.paragraph_format.keep_with_next = True
                        run = p.add_run(value)
                        set_font(run, "微软雅黑" if row_index == 0 else "宋体", 9.2, "FFFFFF" if row_index == 0 else "263445", row_index == 0)
                        if row_index == 0:
                            shade(cell, "163B59")
                doc.add_paragraph().paragraph_format.space_after = Pt(1)
            continue
        if line.startswith("# "):
            text = line[2:].strip()
            if not title_seen:
                p = doc.add_paragraph(style="Title")
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p.add_run(text)
                set_font(run, "黑体", 22, "163B59", True)
                title_seen = True
            else:
                doc.add_heading(text, level=1)
            i += 1
            continue
        if line.startswith("## "):
            doc.add_heading(line[3:].strip(), level=1)
        elif line.startswith("### "):
            doc.add_heading(line[4:].strip(), level=2)
        elif line.startswith("- "):
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_after = Pt(3)
            p.add_run(line[2:].replace("**", ""))
        elif len(line) > 2 and line[0].isdigit() and line[1:3] == ". ":
            p = doc.add_paragraph()
            p.paragraph_format.space_after = Pt(3)
            p.paragraph_format.left_indent = Cm(0.5)
            p.paragraph_format.first_line_indent = Cm(-0.5)
            p.add_run(line[:3] + line[3:].replace("**", ""))
        elif line.startswith("**") and "**" in line[2:]:
            p = doc.add_paragraph()
            for part in line.split("  "):
                if part.startswith("**") and "**" in part[2:]:
                    key, val = part.split("**", 2)[1], part.split("**", 2)[2].strip()
                    r = p.add_run(key)
                    set_font(r, "黑体", 10, "163B59", True)
                    r = p.add_run(val)
                    set_font(r)
                    if part != line.split("  ")[-1]:
                        p.add_run("    ")
                else:
                    p.add_run(part.replace("**", ""))
        else:
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Cm(0.74)
            p.add_run(line.replace("**", "").replace("`", ""))
        i += 1

    # Add a restrained footer with page numbering.
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = footer.add_run("SteelMind 钢结构智能设计助手  |  设计说明书  |  ")
    set_font(r, "宋体", 8, "718096")
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    footer._p.append(fld)

    doc.core_properties.title = "SteelMind 钢结构智能设计助手设计说明书"
    doc.core_properties.subject = "项目背景、设计思路、模块说明与使用流程"
    doc.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    build()
