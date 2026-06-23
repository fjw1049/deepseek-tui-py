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
# Venvs copied from another machine often break (symlinks to another user's Python).
ensure_python_venv() {
  local py="$ROOT/.venv/bin/python"
  if [[ -x "$py" ]] && "$py" -c "import typing_extensions, pydantic" 2>/dev/null; then
    return 0
  fi
  if ! command -v uv >/dev/null 2>&1; then
    echo "[workbench] ERROR: Python venv missing/broken and 'uv' is not installed." >&2
    echo "[workbench] Install uv (https://docs.astral.sh/uv/) then run:" >&2
    echo "  cd \"$ROOT\" && uv venv .venv --python 3.12 --clear && uv sync --extra dev" >&2
    exit 1
  fi
  echo "[workbench] Python venv missing or broken — recreating with uv..."
  uv venv "$ROOT/.venv" --python 3.12 --clear
  (cd "$ROOT" && uv sync --extra dev)
}

if [[ -z "${DEEPSEEK_PYTHON:-}" ]]; then
  ensure_python_venv
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
