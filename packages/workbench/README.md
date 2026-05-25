# DeepSeek Workbench

Electron GUI for the Python `deepseek-tui` runtime (HTTP/SSE on port **7878**).

## Prerequisites

- Python 3.11+ with this repo’s `src/` on `PYTHONPATH`
- Node.js 20+ and npm
- DeepSeek API key in `<repo>/.deepseek/config.toml` (used automatically in monorepo dev)

## Quick start

From the repository root:

```bash
./scripts/dev-workbench.sh
```

This runs **Electron + Vite** (`http://127.0.0.1:5173`). The Python runtime API (`http://127.0.0.1:7878`) is started automatically by the GUI — **do not open 7878 in a browser** expecting the UI.

## Scripts (repo root)

| Script | Purpose |
|--------|---------|
| `./scripts/dev-workbench.sh` | Runtime + Electron dev |
| `./scripts/smoke-workbench-chat.sh` | SSE chat path smoke (runtime must be up) |
| `./scripts/contract-check.sh` | `pytest tests/contract` |

## Configuration

In monorepo dev, config is **`.deepseek/config.toml`** at the repo root (not only `~/.deepseek`).

The GUI spawns:

```bash
python3 -m deepseek_tui serve --http --host 127.0.0.1 --port 7878 --config <repo>/.deepseek/config.toml --insecure
```

Override Python with `DEEPSEEK_PYTHON`, port with `DEEPSEEK_RUNTIME_PORT`.

## API contract

Runtime routes are defined in `contracts/runtime-api.openapi.yaml` at the repo root.
Implementation lives in `src/deepseek_tui/app_server/runtime_api/`.
