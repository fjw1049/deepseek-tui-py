---
name: python-runtime
description: >
  Python runtime / engine work for DeepSeek-TUI. Use when editing engine,
  tools, MCP client/manager, FastAPI server routes, CLI, TUI backend logic,
  config models, or pytest under tests/.
---

# python-runtime

## Layout

| Concern | Path |
|---|---|
| Orchestrator | `src/deepseek_tui/engine/orchestrator/` |
| Tool runtime | `src/deepseek_tui/tools/runtime.py` |
| Approval | `src/deepseek_tui/tools/approval.py` |
| MCP | `src/deepseek_tui/mcp/` |
| HTTP API | `src/deepseek_tui/server/routes.py` |
| Config | `src/deepseek_tui/config/models.py` |
| Feature flags | `Config.features.*` (e.g. `features.plugins`) |

## Conventions

- Use the project venv: `uv run` / `.venv/bin/python` (system `deepseek-tui` may be an older Rust binary without `plugin`).
- Prefer narrow pytest targets over full suite while iterating.
- Do not break Engine construction if a plugin is malformed — discovery already degrades with warnings.
- MCP stdio framing: one JSON-RPC object per line (see `hello-probe` / this plugin's `repo_server.py`).
- Match existing typing and logging style; avoid new abstractions for one call site.

## Useful commands

```bash
uv pip install -e .
uv run deepseek-tui plugin list
uv run pytest tests/test_plugins.py -q
uv run pytest tests/contract/test_plugins_api.py -q
```

## Verify

- Unit/contract tests for the touched module.
- For server routes: contract tests under `tests/contract/`.
- For agent-visible behavior: new session + observable skill/tool/hook effect.
