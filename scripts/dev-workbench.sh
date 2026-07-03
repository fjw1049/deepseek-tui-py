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

electron_binary_ready() {
  local path_file="node_modules/electron/path.txt"
  [[ -f "$path_file" ]] || return 1
  local rel
  rel="$(tr -d '\n\r' < "$path_file")"
  [[ -n "$rel" && -x "node_modules/electron/dist/$rel" ]]
}

install_electron_binary() {
  if [[ ! -f node_modules/electron/install.js ]]; then
    echo "[workbench] electron package missing — run npm install in packages/workbench first" >&2
    exit 1
  fi
  echo "[workbench] downloading Electron binary (~150MB) via ELECTRON_MIRROR=${ELECTRON_MIRROR}"
  node node_modules/electron/install.js || true
  if electron_binary_ready; then
    return 0
  fi

  # extract-zip@2.0.1 (used by electron/install.js) can stop after the first
  # archive entry on newer Node — fall back to the system unzip.
  echo "[workbench] electron install.js incomplete — extracting with unzip..."
  local zip
  zip="$(node -e "
    const { downloadArtifact } = require('@electron/get');
    const { version } = require('./node_modules/electron/package');
    const platform = process.env.npm_config_platform || process.platform;
    let arch = process.env.npm_config_arch || process.arch;
    downloadArtifact({ version, artifactName: 'electron', platform, arch })
      .then((p) => { console.log(p); })
      .catch((err) => { console.error(err); process.exit(1); });
  ")"
  rm -rf node_modules/electron/dist
  mkdir -p node_modules/electron/dist
  unzip -q -o "$zip" -d node_modules/electron/dist
  node -e "
    const fs = require('fs');
    const os = require('os');
    const platform = process.env.npm_config_platform || os.platform();
    const rel = platform === 'win32'
      ? 'electron.exe'
      : (platform === 'darwin' ? 'Electron.app/Contents/MacOS/Electron' : 'electron');
    fs.writeFileSync('node_modules/electron/path.txt', rel);
  "
}

normalize_electron_path_txt() {
  node -e "
    const fs = require('fs');
    const p = 'node_modules/electron/path.txt';
    if (!fs.existsSync(p)) process.exit(0);
    fs.writeFileSync(p, fs.readFileSync(p, 'utf8').trim());
  "
}

esbuild_platform_binary_ready() {
  node -e "
    const fs = require('fs');
    const path = require('path');
    const bin = path.join(
      'node_modules',
      '@esbuild',
      process.platform + '-' + process.arch,
      'bin',
      'esbuild'
    );
    process.exit(fs.existsSync(bin) ? 0 : 1);
  "
}

ensure_node_modules() {
  if [[ -d node_modules \
    && -f node_modules/cac/dist/index.mjs \
    && -f node_modules/@larksuiteoapi/node-sdk/package.json \
    && -f node_modules/@larksuiteoapi/node-sdk/lib/index.js \
    && esbuild_platform_binary_ready ]]; then
    echo "[workbench] node_modules ready (skip npm install)"
    return 0
  fi
  if [[ -d node_modules ]]; then
    echo "[workbench] node_modules incomplete — running npm ci..."
  else
    echo "[workbench] npm ci (first run — downloads deps + Electron ~150MB)"
  fi
  echo "[workbench] using ELECTRON_MIRROR=${ELECTRON_MIRROR}"
  if ! npm ci; then
    echo "[workbench] npm ci failed — retrying with registry.npmjs.org (npmmirror may be down)" >&2
    npm ci --registry https://registry.npmjs.org
  fi
}

ensure_node_modules
install_electron_binary
normalize_electron_path_txt

echo "[workbench] starting Electron + Vite dev server (UI: http://127.0.0.1:5173)"
echo "[workbench] Python runtime API will auto-start on port ${DEEPSEEK_RUNTIME_PORT:-7878} when the GUI connects"
echo "[workbench] do NOT open the runtime port in a browser — use the Electron window"
echo "[workbench] smoke test (runtime must be up): ${ROOT}/scripts/smoke-workbench-chat.sh  # reads ~/.deepseek/runtime.token"
npm run dev
