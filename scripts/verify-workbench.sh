#!/usr/bin/env bash
# Collective Workbench verification (contract + TS + optional smoke).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="${DEEPSEEK_PYTHON:-${ROOT}/.venv/bin/python}"
PORT="${DEEPSEEK_RUNTIME_PORT:-7878}"

echo "[verify] contract tests"
PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$PYTHON" -m pytest tests/contract -q

echo "[verify] workbench typecheck + vitest"
(
  cd "${ROOT}/packages/workbench"
  npm run typecheck
  npm run test
)

if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "[verify] smoke-workbench-chat (runtime already up)"
  DEEPSEEK_RUNTIME_PORT="${PORT}" "${ROOT}/scripts/smoke-workbench-chat.sh"
else
  echo "[verify] skip smoke-workbench-chat — no runtime on :${PORT}"
  echo "  start runtime then rerun: bash scripts/verify-workbench.sh"
fi

echo "[verify] all automated checks passed"
