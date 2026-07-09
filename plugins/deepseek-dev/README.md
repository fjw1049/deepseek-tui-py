# deepseek-dev

Business plugin for developing **DeepSeek-TUI + Workbench** in this repository.

Bundles:

| Component | What |
|---|---|
| Skills | `deepseek-dev`, `workbench-ui`, `plugin-system`, `python-runtime` |
| Hook | `session_start` → writes `.runtime/session_context.md` |
| MCP | `deepseek-dev-repo` — `repo_context` / `locate_files` / `suggest_tests` (read-only, lazy) |

## Install (once)

From the repo root:

```bash
uv pip install -e .
uv run deepseek-tui plugin install "$(pwd)/plugins/deepseek-dev" --trust
uv run deepseek-tui plugin list
```

Use `--project --trust` instead if you only want this checkout.

**New Workbench / TUI session required** after install or trust changes.

## Use in the Workbench composer

1. Open a **new** chat in this workspace.
2. Focus a skill (either works):
   - Type `/deepseek-dev` then your task, or
   - Open the skills panel → pick `deepseek-dev` / `workbench-ui` / …
3. Example prompts:
   - `/deepseek-dev 给 Plugins 页加一个显示组件 chip 的小改动`
   - `/workbench-ui 检查 Sidebar 应用拓展展开逻辑`
   - `/plugin-system 修 skills 直指单目录时发现不到的问题`
   - `先用 repo_context 看一下仓库状态，再建议我怎么改 plugin trust UX`

## Verify the three pipes

- **Skill**: skills panel lists the four names; `/deepseek-dev` chip appears on send.
- **Hook**: after a new session, read  
  `~/.deepseek/plugins/deepseek-dev/.runtime/session_context.md`  
  (or the install path’s `.runtime/`).
- **MCP**: ask the model to call `repo_context`; expect branch + key paths.
