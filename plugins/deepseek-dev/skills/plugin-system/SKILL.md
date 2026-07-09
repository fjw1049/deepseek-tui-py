---
name: plugin-system
description: >
  DeepSeek plugin system work. Use when editing integrations/plugins.py,
  plugin manifests, trust/enable lockfiles, contributions (skills/hooks/MCP),
  Claude Code interop, marketplace registry, CLI `plugin` commands, TUI
  `/plugins`, or Workbench PluginsView.
---

# plugin-system

## Mental model

A **plugin** is a packaging unit over existing extension points:

- `skills` — always loaded when plugin enabled
- `hooks` / `mcpServers` — only when **trusted**
- Scopes: project (`.deepseek/plugins`) > user (`~/.deepseek/plugins`) > Claude read-only

Docs: `docs/PLUGIN_SYSTEM.md`. Core: `src/deepseek_tui/integrations/plugins.py`.

## Manifest

Lookup order:

1. `.deepseek-plugin/plugin.json`
2. `.claude-plugin/plugin.json`
3. `plugin.json`

`skills` should point at a **directory of skill folders** (`./skills` with `skills/<name>/SKILL.md`), not a single skill directory (Claude sometimes points at one skill path; our discover expects children).

`${PLUGIN_DIR}` expands in hook commands and MCP command/args/env.

## Engine wiring

`Engine.create()` → `discover_plugins` → `collect_contributions` → merge skills / hooks / `extra_mcp_servers`.  
Plugin MCP defaults to **lazy**. Permission strings map to ToolCapability for approval UX.

## Tests to run

```bash
uv run pytest tests/test_plugins.py tests/contract/test_plugins_api.py -q
```

## Shipping a plugin in this repo

1. Author under `plugins/<name>/` (tracked in git).
2. Install: `uv run deepseek-tui plugin install <abs-path> --trust` (user) or `--project --trust`.
3. **New session** in TUI/Workbench.
4. Confirm skills via `/v1/skills` or composer skills panel; hooks via plugin log; MCP via tool call.

## Safety

Never auto-trust third-party plugins with hooks/MCP. Skills-only plugins are safer defaults.
