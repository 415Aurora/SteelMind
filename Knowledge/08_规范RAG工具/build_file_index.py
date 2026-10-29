from __future__ import annotations

import csv
import hashlib
import html
import os
from datetime import date
from pathlib import Path
from urllib.parse import quote


PROJECT = Path(__file__).resolve().parents[1]
INDEX_DIR = PROJECT / "01_规范与基础数据" / "05_原始文件"
INDEX_DIR.mkdir(parents=True, exist_ok=True)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def size_text(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.2f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


def main() -> None:
    records = []
    roots = [
        PROJECT / "01_规范与基础数据",
        PROJECT / "07_机器可读规范库",
        PROJECT / "08_规范RAG工具",
    ]
    for base in roots:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            if path.name in {"资料文件索引.html", "文件校验清单.csv"}:
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.name.endswith(".inspect.ndjson"):
                continue
            relative = path.relative_to(PROJECT)
            category = relative.parts[0]
            if category == "01_规范与基础数据" and len(relative.parts) > 2:
                category = f"{category} / {relative.parts[1]}"
            records.append(
                {
                    "path": str(relative),
                    "name": path.name,
                    "category": category,
                    "type": path.suffix.lower().lstrip(".").upper(),
                    "size": path.stat().st_size,
                    "sha256": digest(path),
                }
            )

    root_readme = PROJECT / "README_资料与AI工具入口.md"
    if root_readme.exists():
        records.append(
            {
                "path": root_readme.name,
                "name": root_readme.name,
                "category": "项目说明",
                "type": "MD",
                "size": root_readme.stat().st_size,
                "sha256": digest(root_readme),
            }
        )

    with (INDEX_DIR / "文件校验清单.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["path", "name", "category", "type", "size", "sha256"],
        )
        writer.writeheader()
        writer.writerows(records)

    rows = []
    for record in records:
        relative_href = os.path.relpath(PROJECT / record["path"], INDEX_DIR)
        rows.append(
            "<tr>"
            f"<td>{html.escape(record['category'])}</td>"
            f'<td><a href="{quote(Path(relative_href).as_posix())}">{html.escape(record["name"])}</a></td>'
            f"<td>{record['type']}</td><td>{size_text(record['size'])}</td>"
            f"<td>{record['sha256']}</td></tr>"
        )

    page = f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SteelMind 资料与工具索引</title>
<style>
body{{margin:0;background:#f3f5f6;color:#183247;font-family:"Microsoft YaHei",Arial,sans-serif;line-height:1.65}}
main{{max-width:1280px;margin:28px auto 60px;padding:0 24px}}h1{{font-size:28px;margin:0 0 4px}}
p{{margin:0 0 20px;color:#607286}}table{{width:100%;border-collapse:collapse;background:#fff;font-size:14px}}
th,td{{padding:9px 10px;border-bottom:1px solid #dce3e7;text-align:left;vertical-align:top}}
th{{position:sticky;top:0;background:#123d4a;color:#fff}}a{{color:#126d73;text-decoration:none}}
td:nth-child(5){{font-family:Consolas,monospace;font-size:11px;color:#607286;word-break:break-all}}
</style></head><body><main>
<h1>SteelMind 资料与工具索引</h1><p>生成日期：{date.today().isoformat()} · 文件数：{len(records)} · 点击文件名直接打开</p>
<table><thead><tr><th>分类</th><th>文件</th><th>格式</th><th>大小</th><th>SHA-256</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></main></body></html>"""
    (INDEX_DIR / "资料文件索引.html").write_text(page, encoding="utf-8")
    print(f"indexed={len(records)}")


if __name__ == "__main__":
    main()
