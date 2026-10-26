"""Host dependencies, without silent substitution or a shared office profile."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from threading import RLock
from xml.sax.saxutils import escape

# Matplotlib's global font/figure state is not thread-safe; office conversion
# remains concurrent, with a private profile per call.
RENDER_LOCK = RLock()


class ConversionError(RuntimeError):
    """Office conversion did not produce a verified PDF."""


def resolve_font() -> tuple[Path, str]:
    """Resolve a Chinese font; callers record the actual file and family."""
    explicit = os.environ.get("STEELMIND_FONT")
    candidates = [Path(explicit)] if explicit else [
        Path(__file__).parent / "assets/fonts/NotoSansCJKsc-Regular.otf",
        Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
        Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc",
        Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/simsun.ttc",
    ]
    for path in candidates:
        if path.is_file():
            from matplotlib.font_manager import FontProperties

            family = os.environ.get("STEELMIND_FONT_FAMILY") or FontProperties(fname=str(path)).get_name()
            return path.resolve(), family
    raise FileNotFoundError("未找到中文字体。安装 Noto Sans CJK SC 或设置 STEELMIND_FONT（字体文件绝对路径）。")


def find_soffice(explicit: str | None = None) -> str:
    configured = explicit or os.environ.get("STEELMIND_SOFFICE")
    if configured:
        found = shutil.which(configured)
        if found:
            return found
        raise ConversionError("LibreOffice 路径无效；请设置 STEELMIND_SOFFICE 为 soffice 可执行文件。")
    for candidate in [
        shutil.which("soffice"), shutil.which("libreoffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        str(Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "LibreOffice/program/soffice.exe"),
    ]:
        if candidate and Path(candidate).is_file():
            return candidate
    raise ConversionError("未找到 LibreOffice；安装 LibreOffice Writer 或使用提供的 Docker 镜像。")


def convert_docx_to_pdf(
    docx_path: Path, output_dir: Path, *, soffice_path: str | None = None, timeout: int = 120
) -> Path:
    """Convert once, reject old/missing/malformed output, and isolate concurrent runs."""
    docx_path, output_dir = Path(docx_path).resolve(), Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf = output_dir / (docx_path.stem + ".pdf")
    if pdf.exists():
        raise ConversionError("目标 PDF 已存在；为避免返回旧成果，请使用新的运行目录。")
    exe = find_soffice(soffice_path)
    with tempfile.TemporaryDirectory(prefix="steelmind-office-") as profile:
        args = [exe, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless",
                "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(output_dir), str(docx_path)]
        env = os.environ.copy()
        if os.name != "nt":
            font_path, _ = resolve_font()
            # Headless macOS builds use fontconfig rather than CoreText. Give
            # this process a private font configuration instead of modifying
            # system font folders or relying on unavailable fallback fonts.
            config = Path(profile) / "fonts.conf"
            inherited = env.get("FONTCONFIG_FILE")
            if not inherited and Path("/etc/fonts/fonts.conf").is_file():
                inherited = "/etc/fonts/fonts.conf"
            include = f'<include ignore_missing="yes">{escape(inherited)}</include>' if inherited else ""
            config.write_text(
                '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
                + include + f'<dir>{escape(str(font_path.parent))}</dir>'
                + f'<cachedir>{escape(profile)}/font-cache</cachedir></fontconfig>', encoding="utf-8")
            env["FONTCONFIG_FILE"] = str(config)
        try:
            completed = subprocess.run(args, capture_output=True, timeout=timeout, check=False, env=env)
        except subprocess.TimeoutExpired as exc:
            pdf.unlink(missing_ok=True)
            raise ConversionError(f"LibreOffice 转换超时（{timeout} 秒）；DOCX 已保留。") from exc
        except OSError as exc:
            pdf.unlink(missing_ok=True)
            raise ConversionError(f"无法启动 LibreOffice：{exc}") from exc
    if completed.returncode != 0 or not pdf.is_file():
        pdf.unlink(missing_ok=True)
        detail = (completed.stderr or completed.stdout).decode("utf-8", errors="replace")[-600:]
        raise ConversionError(f"LibreOffice 未生成有效 PDF：{detail}")
    try:
        from pypdf import PdfReader

        reader = PdfReader(pdf)
        if not pdf.read_bytes().startswith(b"%PDF-") or not reader.pages:
            raise ValueError("empty PDF")
        # Reject invisible/mis-encoded CJK instead of returning a false success.
        from zipfile import ZipFile
        from xml.etree import ElementTree as ET

        with ZipFile(docx_path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
        authored = "".join(root.itertext())
        expected = {ch for ch in authored if '\u4e00' <= ch <= '\u9fff'}
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        if expected - set(extracted):
            raise ValueError("Chinese glyphs missing from converted PDF")
    except Exception as exc:
        pdf.unlink(missing_ok=True)
        raise ConversionError("LibreOffice 输出 PDF 损坏、为空或中文缺字；请检查中文字体及转换器字体配置。") from exc
    return pdf
