#!/usr/bin/env bash
# Start the DeepSeek TUI.
#
# Usage:
#   bash scripts/start-service.sh             # day-to-day: sync deps, launch TUI
#   bash scripts/start-service.sh --fresh     # nuke .venv then re-create
#   bash scripts/start-service.sh --help      # any flags after this point are
#                                             # forwarded to deepseek-tui itself
#
# Notes:
#   - ``uv sync --inexact`` preserves any extras (dev deps, etc.) already
#     installed in .venv so running this script doesn't strip out pytest
#     / ruff / mypy mid-session.
#   - ``uv run --no-sync`` keeps the implicit pre-run sync from undoing
#     that, otherwise it would re-prune the venv before launching.
#   - ``cd`` to the repo root so the script works from any cwd
#     (``bash scripts/start-service.sh`` or an absolute path both fine).
#   - On macOS, files under ``.venv`` can carry the UF_HIDDEN flag; Python 3.12+
#     skips such ``*.pth`` files, so PEP 660 editable installs may not add
#     ``src`` to ``sys.path``. Prepending ``PYTHONPATH`` avoids a broken import.

set -euo pipefail

cd "$(dirname "$0")/.."
export PYTHONPATH="${PWD}/src${PYTHONPATH:+:${PYTHONPATH}}"

if [[ "${1-}" == "--fresh" ]]; then
  rm -rf .venv
  shift
fi

uv sync --quiet --inexact
exec uv run --no-sync deepseek-tui "$@"