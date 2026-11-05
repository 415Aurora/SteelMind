#!/bin/bash
# Project-only case runner: no package installation or global Python fallback.
set -euo pipefail
CASE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
unset PYTHONPATH PYTHONHOME VIRTUAL_ENV
CASE_PY="${STEELMIND_CASE_PYTHON:-}"
if [[ -z "$CASE_PY" ]]; then
  for candidate in "$CASE_ROOT/.venv/bin/python" "$CASE_ROOT/../runtime/venv/bin/python"; do
    if [[ -x "$candidate" ]]; then CASE_PY="$candidate"; break; fi
  done
fi
setup_help() {
  cat >&2 <<EOF
未找到可用的项目虚拟环境；本脚本不会安装依赖或使用全局Python。
首次安装请在项目目录执行（依赖仅写入.venv）：
  python3 -m venv .venv
  ./.venv/bin/python -m pip install -r backend/requirements.txt
  ./.venv/bin/python -m pip install ./backend/engineering_export
随后再次运行：bash scripts/run_longyan_case.sh
EOF
}
if [[ -z "$CASE_PY" || ! -x "$CASE_PY" ]]; then setup_help; exit 2; fi
if ! "$CASE_PY" -I -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) and sys.prefix != sys.base_prefix else 1)'; then
  setup_help; exit 2
fi
CASE_CORE_ONLY=0
for arg in "$@"; do if [[ "$arg" == '--verify-only' ]]; then CASE_CORE_ONLY=1; fi; done
if ! "$CASE_PY" -I -c 'import importlib,sys
names=["numpy","openseespy.opensees"]
if sys.argv[1]=="0": names += ["fastapi","docx","openpyxl","ezdxf","matplotlib","pydantic"]
missing=[]
for name in names:
 try: importlib.import_module(name)
 except ImportError: missing.append(name)
if missing: print("项目虚拟环境缺少依赖："+", ".join(missing),file=sys.stderr)
raise SystemExit(bool(missing))' "$CASE_CORE_ONLY"; then
  setup_help; exit 2
fi
CASE_RUNTIME="$CASE_ROOT/backend/artifacts/case-runtime"
export PYTHONNOUSERSITE=1
export XDG_CACHE_HOME="$CASE_RUNTIME/cache"
export MPLCONFIGDIR="$CASE_RUNTIME/cache/matplotlib"
export TMPDIR="$CASE_RUNTIME/tmp/"
mkdir -p "$MPLCONFIGDIR" "$TMPDIR"
printf '使用项目隔离环境运行办公楼完整荷载案例；不会启动网页或调用模型API。\n'
exec "$CASE_PY" -I "$CASE_ROOT/scripts/run_office_case.py" "$@"
