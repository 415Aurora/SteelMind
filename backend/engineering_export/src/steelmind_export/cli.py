"""Machine-readable stdout; diagnostics and nonzero exits are unambiguous."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .models import DesignBundle
from .pipeline import generate_calculation_book, generate_design_files, generate_package
from .results import BundleValidationError
from .validation import validate_bundle


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="steelmind-export", description="SteelMind 计算书与设计文件生成")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate", help="校核 DesignBundle JSON")
    validate.add_argument("input", type=Path)
    build = sub.add_parser("build", help="生成不可覆盖的独立成果目录")
    build.add_argument("input", type=Path)
    build.add_argument("--output", type=Path, default=Path("runs"))
    build.add_argument("--kind", choices=["package", "calculation-book", "design-files"], default="package")
    build.add_argument("--no-pdf", action="store_true")
    build.add_argument("--dwg", action="store_true")
    schema = sub.add_parser("schema", help="输出 JSON Schema")
    schema.add_argument("--output", type=Path)
    examples = sub.add_parser("example", help="输出内置示例 JSON")
    examples.add_argument("name", choices=["minimal", "demo", "analytic"])
    examples.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    def emit(value):
        text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
        if getattr(args, "output", None) and args.command in {"schema", "example"}:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
        else:
            print(text)

    try:
        if args.command == "schema":
            emit(DesignBundle.model_json_schema())
            return 0
        if args.command == "example":
            from .examples import minimal_bundle, demo_bundle, analytic_bundle

            emit({"minimal": minimal_bundle, "demo": demo_bundle, "analytic": analytic_bundle}[args.name]())
            return 0
        data = json.loads(args.input.read_text(encoding="utf-8"))
        if args.command == "validate":
            report = validate_bundle(data)
            emit(report.model_dump(mode="json"))
            return 0 if report.valid else 2
        handler = {"package": generate_package, "calculation-book": generate_calculation_book,
                   "design-files": generate_design_files}[args.kind]
        result = handler(data, {"include_pdf": not args.no_pdf, "include_dwg": args.dwg}, args.output)
        emit(result.model_dump(mode="json"))
        return 0 if result.generation_status == "success" else 3
    except BundleValidationError as exc:
        emit({"error": "INPUT_INVALID", "validation": exc.report.model_dump(mode="json")})
        return 2
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
