# DeepSeek Workbench

Electron GUI for the Python `deepseek-tui` runtime (HTTP/SSE on port **7878**).

Development branch: **`build_gui_master`**.

## Prerequisites

| Component | Version | Notes |
|-----------|---------|--------|
| **Python** | ≥ 3.10 (recommended **3.11–3.12**) | Runtime API needs `fastapi`, `uvicorn` from repo `pyproject.toml` |
| **Node.js** | **20 LTS** (20.x) | Electron 34 bundles Node 20.19.1; Node 25 may work but is not the primary target |
| **npm** | ships with Node | Use **`npm ci`** in this directory — do not run `npm update` casually |
| **API key** | — | `<repo>/.deepseek/config.toml` (monorepo dev; GUI passes `--config` automatically) |

### Locked GUI stack (`package-lock.json`)

These versions are what `npm ci` installs — **do not upgrade ad hoc**:

| Package | Locked version |
|---------|----------------|
| `electron` | 34.5.8 |
| `electron-vite` | 3.1.0 |
| `vite` | 6.x |
| `zod` | 4.4.3 |
| `node-pty` | 1.1.0 |

First install downloads the Electron binary (~150 MB). In China, `scripts/dev-workbench.sh` defaults to:

```bash
ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/
```

After install, this path must exist:

```text
packages/workbench/node_modules/electron/dist/
```

`postinstall.cjs` uses bundled `node-pty` prebuilds on macOS when possible (skips slow `electron-rebuild`).

## Quick start (from repo root)

```bash
git checkout build_gui_master
git pull

# Python (once per venv / machine)
pip install -e ".[dev]"          # or: uv pip install -e ".[dev]"

# GUI deps (once per machine, or after lockfile changes)
cd packages/workbench && npm ci && cd ../..

# Ensure <repo>/.deepseek/config.toml has your API key

unset ELECTRON_RUN_AS_NODE       # see Troubleshooting if GUI crashes on start
./scripts/dev-workbench.sh
```

- **UI**: Electron window (Vite dev server at `http://127.0.0.1:5173` — internal, not the main entry)
- **7878**: Python Runtime API only — **do not open in a browser** expecting the UI

Subsequent runs skip `npm ci` when `node_modules/electron/dist` already exists.

## Scripts (repo root)

| Script | Purpose |
|--------|---------|
| `./scripts/dev-workbench.sh` | Electron + Vite dev (GUI auto-starts Python runtime) |
| `./scripts/smoke-workbench-chat.sh` | SSE chat smoke (runtime must be on 7878) |
| `./scripts/contract-check.sh` | `pytest tests/contract` |

## Configuration

Monorepo dev uses **`.deepseek/config.toml`** at the repository root (not only `~/.deepseek`).

The GUI spawns:

```bash
python3 -m deepseek_tui serve --http --host 127.0.0.1 --port 7878 \
  --config <repo>/.deepseek/config.toml --insecure
```

| Variable | Default | Purpose |
|----------|---------|---------|
| `DEEPSEEK_PYTHON` | `python3` | Python executable for runtime spawn |
| `DEEPSEEK_RUNTIME_PORT` | `7878` | Runtime API port |
| `DEEPSEEK_REPO_ROOT` | set by dev script | Monorepo root for config / spawn |
| `ELECTRON_MIRROR` | npmmirror (if unset) | Faster Electron download in China |

## Verify setup

```bash
pytest tests/contract -q
./scripts/smoke-workbench-chat.sh   # after GUI is up
```

## Troubleshooting

### `Cannot read properties of undefined (reading 'exports')` on Electron start

**Cause**: `ELECTRON_RUN_AS_NODE=1` in the environment (common in Cursor/CI). Electron runs as plain Node — no GUI, broken module loading.

**Fix**:

```bash
unset ELECTRON_RUN_AS_NODE
./scripts/dev-workbench.sh
```

(`dev-workbench.sh` already unsets this; run manually if your shell re-exports it.)

### Browser shows JSON / 404 on port 7878

7878 is the **Runtime API**, not the UI. Use the **Electron window** from `./scripts/dev-workbench.sh`.

### First start very slow (~3–6 min)

Normal on first `npm ci` while downloading Electron. Later starts are ~10–20 s.

### Clean reinstall of GUI deps

```bash
cd packages/workbench
rm -rf node_modules
npm ci
```

### `npm ci` vs `npm install`

Prefer **`npm ci`** — installs exactly what `package-lock.json` pins. Avoid `npm update` unless you intend to refresh the lockfile and re-test the GUI.

## API contract

Runtime routes: `contracts/runtime-api.openapi.yaml` (repo root).

Implementation: `src/deepseek_tui/app_server/runtime_api/`.
