#!/bin/bash
CASE_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "$CASE_ROOT/scripts/run_office_case.sh" "$@"
CASE_STATUS=$?
if [[ -t 0 ]]; then read -r -p '按回车关闭窗口…' _case_finish; fi
exit "$CASE_STATUS"
