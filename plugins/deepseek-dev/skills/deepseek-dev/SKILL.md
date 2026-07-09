---
name: deepseek-dev
description: >
  Default DeepSeek-TUI / Workbench development skill. Use when the user is
  working in this repo (deepseek-tui-py), asking to implement features, fix
  bugs, add tests, touch plugins/skills/MCP/Workbench GUI, or says they want
  to "use deepseek-dev" / "带着插件做开发". Routes work to the right subsystem
  and keeps changes surgical.
---

# deepseek-dev

You are developing **DeepSeek-TUI (Python)** and its **Workbench (Electron/React)** GUI in this workspace.

## Before coding

1. State assumptions; if the request is ambiguous, ask once.
2. Prefer the smallest change that solves the request — no speculative refactors.
3. Match existing style in the files you touch.
4. Every changed line should trace to the user's request.

## Repo map (start here)

| Area | Path |
|---|---|
| Engine / agent loop | `src/deepseek_tui/engine/` |
| Plugin system | `src/deepseek_tui/integrations/plugins.py` |
| Skills | `src/deepseek_tui/integrations/skills.py` |
| Hooks | `src/deepseek_tui/integrations/hooks.py` |
| MCP | `src/deepseek_tui/mcp/` |
| HTTP runtime (GUI backend) | `src/deepseek_tui/server/` |
| CLI | `src/deepseek_tui/cli/app.py` |
| TUI | `src/deepseek_tui/tui/` |
| Workbench UI | `packages/workbench/src/renderer/` |
| Plugin docs | `docs/PLUGIN_SYSTEM.md` |
| Example / business plugins | `plugins/` |
| Tests | `tests/` |

## Skill routing (load the focused skill when needed)

Call `load_skill` for the matching pack when the task is specialized:

| Task | Skill |
|---|---|
| Workbench React/TSX, Extensions, composer, sidebar | `workbench-ui` |
| Plugin manifest, trust, contributions, marketplace | `plugin-system` |
| Engine, tools, MCP runtime, FastAPI routes, pytest | `python-runtime` |

If the task spans areas, keep this skill as the umbrella and load the others as needed.

## Plugin MCP helpers

This plugin ships a lazy MCP server `deepseek-dev-repo` with read-only tools:

- `repo_context` — branch, dirty summary, key paths
- `locate_files` — glob find under the workspace
- `suggest_tests` — guess pytest targets for a source path

Prefer these for orientation before large searches. Tool names appear as `mcp_deepseek_dev_repo_*`.

## Verification habit

Turn the request into checks, then run them:

```
1. [change] → verify: [command or observable behavior]
```

Common checks:

- Python: `uv run pytest tests/test_plugins.py -q` (or the narrowest relevant file)
- Workbench typecheck/lint if the package scripts exist; otherwise keep TS edits consistent with neighbors
- Plugin changes: new session required; confirm with `/skills` or Extensions → Plugins

## Composer usage (tell the user when relevant)

In Workbench, focus this skill with `/deepseek-dev` (or pick it from the skills panel) then state the task. Changes to plugins apply on the **next** session.
