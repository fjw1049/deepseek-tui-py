#!/usr/bin/env bash
# Launch DeepSeek Workbench (Electron + Vite). The Python runtime is started by the GUI.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export DEEPSEEK_REPO_ROOT="$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export DEEPSEEK_SKIP_KEYRING=1
# User state stays under ~/.deepseek (config, mcp, skills, runtime.token, …).
# Repo-local .deepseek/config.toml is merged as a project override by ConfigLoader.

# Prefer repo venv so Electron does not fall back to system python3 (often 3.9 without deps).
if [[ -z "${DEEPSEEK_PYTHON:-}" && -x "$ROOT/.venv/bin/python" ]]; then
  export DEEPSEEK_PYTHON="$ROOT/.venv/bin/python"
fi

cd "$ROOT/packages/workbench"

# Cursor/CI sometimes sets this — Electron then runs as plain Node (no GUI, broken imports).
unset ELECTRON_RUN_AS_NODE

# Electron binary download from GitHub is slow without a mirror (common on first install).
if [[ -z "${ELECTRON_MIRROR:-}" ]]; then
  export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
fi

if [[ ! -d node_modules/electron/dist ]]; then
  echo "[workbench] npm install (first run — downloads Electron ~150MB, then compiles node-pty)"
  echo "[workbench] using ELECTRON_MIRROR=${ELECTRON_MIRROR}"
  npm install
else
  echo "[workbench] node_modules ready (skip npm install)"
fi

echo "[workbench] starting Electron + Vite dev server (UI: http://127.0.0.1:5173)"
echo "[workbench] Python runtime API will auto-start on port ${DEEPSEEK_RUNTIME_PORT:-7878} when the GUI connects"
echo "[workbench] do NOT open the runtime port in a browser — use the Electron window"
echo "[workbench] smoke test (runtime must be up): ${ROOT}/scripts/smoke-workbench-chat.sh  # reads ~/.deepseek/runtime.token"
npm run dev
