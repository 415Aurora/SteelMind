"""Optional LangChain adapter; the deterministic core has no LangChain dependency."""

from pathlib import Path

from .pipeline import generate_calculation_book, generate_design_files
from .results import public_result


def make_langchain_tools(output_dir: str | Path):
    """Create two StructuredTools for the workflow owner's existing LCEL chain."""
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:
        raise ImportError("安装可选依赖：pip install 'steelmind-export[langchain]'") from exc
    root = Path(output_dir)

    def calculation_book_generate(bundle: dict, options: dict | None = None) -> dict:
        """依据已提供的结构模型与计算结果生成可追溯计算书和结果表。"""
        return public_result(generate_calculation_book(bundle, options, root))

    def design_files_generate(bundle: dict, options: dict | None = None) -> dict:
        """依据已提供的二维钢框架几何生成方案级DXF和图纸PDF。"""
        return public_result(generate_design_files(bundle, options, root))

    return [StructuredTool.from_function(calculation_book_generate), StructuredTool.from_function(design_files_generate)]
