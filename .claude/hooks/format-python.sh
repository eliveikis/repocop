#!/usr/bin/env bash
# PostToolUse hook (Edit|Write|MultiEdit): format + autofix the touched Python file.
# Never blocks Claude: any failure here is swallowed; `make check` is the real gate.
set -uo pipefail

file="$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' 2>/dev/null)"

case "$file" in
  *.py) ;;
  *) exit 0 ;;
esac
[ -f "$file" ] || exit 0
command -v uv >/dev/null || exit 0

cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
uv run --quiet ruff format --quiet "$file" >/dev/null 2>&1 || true
uv run --quiet ruff check --fix --quiet "$file" >/dev/null 2>&1 || true
exit 0
