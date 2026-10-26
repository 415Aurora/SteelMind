#!/usr/bin/env sh
set -eu
exec python -m uvicorn steelmind_export.api:app --host 127.0.0.1 --port "${PORT:-8000}"
