#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

PYTHON="${DEEPSEEK_PYTHON:-python3}"

echo "[contract-check] pytest tests/contract"
"$PYTHON" -m pytest tests/contract -q "$@"

echo "[contract-check] workbench vitest"
(
  cd "$ROOT/packages/workbench"
  npm run test --silent
)

echo "[contract-check] ok"
