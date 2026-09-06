#!/usr/bin/env bash
set -euo pipefail
EVAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$EVAL_ROOT"
export PYTHONPATH="$EVAL_ROOT/src:$EVAL_ROOT${PYTHONPATH:+:$PYTHONPATH}"
exec "$EVAL_ROOT/.venv/bin/python" -m evals serve --port "${EVAL_PORT:-7879}"
