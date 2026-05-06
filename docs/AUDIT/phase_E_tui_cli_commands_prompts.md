# Phase E Audit — TUI / CLI / Slash commands / Prompts / Sub-managers

**Audit Date:** 2026-05-06

---

## Module summary table

| Component | Rust LOC | Python LOC | Parity % | Status |
|---|---:|---:|---:|---|
| TUI widgets/screens (`crates/tui/src/tui/` 48 entries) | 47,753 | 481 | 1.0% | ❌ Severely incomplete |
| TUI top-level orchestration (`tui/src/main.rs`, `app.rs`, `ui.rs` 等顶层文件) | ~149,000 (含上面) | n/a | n/a | ❌ Mostly missing |
| CLI (`crates/cli/src/*.rs`) | 3,405 | 53 (`cli/`) + ~10 (`__main__.py`) | <2% | ❌ Stub only |
| Slash commands (`crates/tui/src/commands/*.rs`) | 7,699 | 0 | 0% | ❌ Not started |
| Prompts / skills / personalities (`tui/src/prompts/` + `skills/` + `assets/skills/`) | 17 templates + 2,070 LOC skills code | `engine/prompts.py` (8 LOC) | <5% | ❌ Almost nothing |
| Sub-managers (top-level `tui/src/*.rs`) | ~30,000 | 0 | 0% | ❌ Not started |
| **PHASE E TOTAL** | **~88,000** | **~544** | **<1%** | ❌ |

---

## 1. TUI screens & widgets

Original Rust uses **ratatui** (immediate-mode TUI). Python rewrite uses **Textual** (declarative, async). This is a fundamental architectural substitution — direct line-by-line porting impossible; widget logic must be re-architected. Whether the substitution is acceptable for "百分百复刻" is a decision the user must make (see Asks).

### Rust widget/screen inventory (`crates/tui/src/tui/` — 48 entries)

Per-file LOC for the 48 entries (sorted by size):

| Rust file | LOC | Purpose |
|---|---:|---|
| `tui/ui.rs` | 7,055 | Top-level UI orchestrator: layout, mode, key dispatch |
| `tui/history.rs` | 4,439 | Conversation transcript model + rendering |
| `tui/app.rs` | 4,140 | App-level event loop, mode transitions |
| `tui/ui/tests.rs` | 3,052 | UI integration test harness |
| `tui/widgets/mod.rs` | 2,552 | Widget catalog |
| `tui/views/mod.rs` | 2,006 | Multi-view container |
| `tui/approval.rs` | 1,688 | Approval gate UI (risk display, accept/reject flow) |
| `tui/widgets/footer.rs` | 1,254 | Status footer |
| `tui/command_palette.rs` | 1,103 | `Cmd-K` style palette |
| `tui/file_mention.rs` | 975 | `@file` autocomplete |
| `tui/tool_routing.rs` | 956 | Tool-output routing into transcript cells |
| `tui/transcript.rs` | 820 | Streaming transcript view |
| `tui/pager.rs` | 809 | Long-output pager |
| `tui/live_transcript.rs` | 798 | Live token stream rendering |
| `tui/sidebar.rs` | 770 | Session/thread sidebar |
| `tui/file_picker.rs` | 701 | File picker dialog |
| `tui/views/help.rs` | 672 | Help screen |
| `tui/widgets/agent_card.rs` | 671 | Sub-agent card |
| `tui/session_picker.rs` | 671 | Session picker |
| `tui/widgets/header.rs` | 631 | Header bar |
| `tui/streaming/mod.rs` | 559 | Streaming state machine |
| `tui/markdown_render.rs` | 559 | Markdown renderer |
| `tui/model_picker.rs` | 500 | Model picker |
| `tui/provider_picker.rs` | 481 | Provider picker |
| `tui/active_cell.rs` | 476 | Active cell tracker |
| `tui/context_inspector.rs` | 466 | Context inspector |
| `tui/widgets/pending_input_preview.rs` | 463 | Pending input preview |
| `tui/diff_render.rs` | 449 | Diff renderer |
| `tui/user_input.rs` | 443 | User input handling |
| `tui/scrolling.rs` | 436 | Scroll state |
| `tui/streaming/chunking.rs` | 423 | Stream chunking |
| `tui/backtrack.rs` | 386 | Backtrack/undo flow |
| `tui/file_tree.rs` | 369 | File tree |
| `tui/keybindings.rs` | 349 | Keybinding registry |
| `tui/notifications.rs` | 341 | Toast notifications |
| `tui/views/status_picker.rs` | 334 | Status picker |
| `tui/subagent_routing.rs` | 333 | Sub-agent output routing |
| `tui/paste_burst.rs` | 328 | Paste-burst detection |
| `tui/external_editor.rs` | 321 | External editor invocation ($EDITOR) |
| `tui/context_menu.rs` | 320 | Context menu |
| `tui/widgets/key_hint.rs` | 314 | Keybinding hint widget |
| `tui/plan_prompt.rs` | 291 | Plan-mode prompt |
| `tui/widgets/tool_card.rs` | 283 | Tool execution card |
| `tui/streaming/commit_tick.rs` | 266 | Stream commit cadence |
| `tui/clipboard.rs` | 246 | Clipboard integration |
| `tui/streaming/line_buffer.rs` | 223 | Line buffer |
| `tui/paste.rs` | 220 | Paste handling |
| `tui/transcript_cache.rs` | 219 | Transcript cache |
| `tui/persistence_actor.rs` | 202 | Persistence actor |
| `tui/frame_rate_limiter.rs` | 186 | Frame rate limiter |
| `tui/shell_job_routing.rs` | 182 | Shell job output routing |
| `tui/onboarding/mod.rs` | 167 | Onboarding screen |
| `tui/osc8.rs` | 165 | OSC-8 hyperlink support |
| `tui/mcp_routing.rs` | 161 | MCP output routing |

### Python widget surface (`src/deepseek_tui/tui/` — 14 files, 481 LOC total)

- `tui/app.py` — DeepSeekTUI app (Textual)
- `tui/screens/chat.py` — ChatScreen
- `tui/screens/config_ui.py` — ConfigScreen
- `tui/widgets/composer.py` — input composer
- `tui/widgets/transcript.py` — transcript view
- `tui/widgets/approval.py` — approval dialog
- `tui/widgets/status_bar.py` — status bar
- `tui/widgets/slash_menu.py` — slash menu
- `tui/widgets/tool_cell.py` — tool execution cell
- `tui/streaming.py` — streaming bridge
- `tui/history.py` — history model

### Gaps

| Gap | Severity |
|---|---|
| Top-level UI orchestrator (Rust `ui.rs` 7,055 LOC) | **P0** |
| App event loop / mode transitions (Rust `app.rs` 4,140 LOC) | **P0** |
| Approval gate UI (1,688 LOC) — Python has minimal `ApprovalDialog` | **P0** |
| Command palette (`Cmd-K`, 1,103 LOC) | **P0** |
| File mention autocomplete (`@file`, 975 LOC) | **P0** |
| Tool routing into transcript (956 LOC) | **P0** |
| Pager (long-output 809 LOC) | **P1** |
| Live transcript chunking (798 LOC, plus `streaming/{mod,chunking,commit_tick,line_buffer}` ≈ 1,471 LOC) | **P0** |
| Sidebar (sessions/threads, 770 LOC) | **P1** |
| File picker / file tree / file mention (~2,045 LOC combined) | **P1** |
| Help screen (672 LOC) | **P2** |
| Agent card / sub-agent routing / shell-job routing / MCP routing (~1,632 LOC) | **P0** |
| Header bar / footer / status picker / pending input preview (~3,084 LOC) | **P1** |
| Markdown renderer (559 LOC) | **P0** |
| Model picker / provider picker (~981 LOC) | **P1** |
| Context inspector / context menu / active cell (~1,262 LOC) | **P1** |
| Diff renderer (449 LOC) | **P0** |
| User input / keybindings / paste-burst / paste (~1,340 LOC) | **P1** |
| Backtrack & undo flow (386 LOC) | **P1** |
| Notifications / OSC-8 hyperlinks / clipboard (~752 LOC) | **P2** |
| Onboarding screen (167 LOC) | **P2** |
| External editor invocation (321 LOC, integrates `$EDITOR`) | **P1** |
| Plan-mode prompt UI (291 LOC) | **P1** |
| Frame rate limiter (186 LOC) | **P2** |
| Persistence actor (202 LOC) | **P1** |
| Transcript cache (219 LOC) | **P2** |
| **UI integration test harness** (3,052 LOC) | **P1** |

---

## 2. CLI surface

### Rust CLI (`crates/cli/src/{main,lib,update,metrics}.rs` ≈ 3,405 LOC)

`cli/src/main.rs` is just `deepseek_tui_cli::run_cli()`. The actual CLI lives in `cli/src/lib.rs`. From the dispatch in `lib.rs:392–453`, the top-level subcommand enum has **22 subcommands**:

| Subcommand | Purpose |
|---|---|
| `Run` | Delegate to TUI binary with extra args |
| `Doctor` | Environment / config diagnostics |
| `Models` | List available models |
| `Sessions` | List sessions |
| `Resume` | Resume a session |
| `Fork` | Fork a session |
| `Init` | Initialize project config / `.deepseek/` |
| `Setup` | Interactive setup (provider + key) |
| `Exec` | Non-interactive single-shot execution |
| `Review` | Code review |
| `Apply` | Apply a patch |
| `Eval` | Run eval harness |
| `Mcp` | MCP control |
| `Features` | Feature flag table |
| `Serve` | Start app server |
| `Completions` | Generate shell completions |
| `Login` | Provider login |
| `Logout` | Provider logout |
| `Auth` | Auth command group (status, set, get, clear, list, migrate) |
| `McpServer` | Run as MCP server |
| `Config` | Config get/set/unset/list/path |
| `Model` | Model list/resolve |
| `Thread` | Thread list/read/resume/fork/archive/unarchive/set-name |
| `Sandbox` | Sandbox check/explain |
| `AppServer` | App server control |
| `Completion` | (alt) shell completions |
| `Metrics` | Metrics snapshot |
| `Update` | Self-update |

Plus a large set of global flags handled in `tui/src/main.rs` (clap `#[derive(Parser)]`):

- mode flags: `--yolo`, `--agent`, `--plan`, `--skill <name>`
- runtime flags: `--model`, `--provider`, `--temperature`, `--top-p`, `--reasoning-effort`, `--mouse-capture`
- sandbox / approval flags: `--sandbox-mode`, `--approval-policy <auto|never|suggest>`, `--trust`
- session flags: `--resume`, `--fork`, `--session <id>`, `--continue`
- output flags: `--non-interactive`, `--json-events`, `--telemetry`
- system flags: `--config <path>`, `--workspace <path>`, `--profile <name>`, `--log <level>`
- MCP / app server flags: `--mcp <path>`, `--app-server`, `--responses-api`

### Python CLI (`src/deepseek_tui/cli/` — 53 LOC + `__main__.py`)

Only minimal entry point that launches Textual app. No subcommand routing, no `doctor`, no `setup`, no `eval`, no `serve`, no `auth`, no `thread` group, no `sandbox check`, no shell completions, no `update`.

### Gaps

- All 22 Rust subcommands missing from Python except the implicit "run TUI" path.
- All ~25 global flags missing.
- Auth subgroup (login / logout / status / set / get / clear / list / migrate) — entirely missing despite `secrets/manager.py` existing.
- `update` self-update path missing.
- Shell completions missing (no `clap_complete` equivalent generation).
- `metrics` subcommand missing (Rust has it via `cli/src/metrics.rs`).
- `eval` harness missing (`tui/src/eval.rs` 742 LOC also missing).

**Severity: P0** — without the subcommand surface the CLI is unusable beyond launching the TUI.

---

## 3. Slash commands

Python: zero slash command implementations. The TUI has a `slash_menu` widget but no command dispatcher. Rust registers **49 slash commands** in `crates/tui/src/commands/mod.rs`, with each command's logic split across the 24 sibling files.

### Rust command inventory

| Slash name | Aliases | Rust file | Rust LOC of file | One-line purpose | Python status |
|---|---|---|---:|---|---|
| `/help` | — | `commands/mod.rs` (registry) | (in `mod.rs` 1043) | Show help / command list | ❌ Missing |
| `/clear` | — | `commands/core.rs` | 566 | Clear transcript buffer | ❌ Missing |
| `/exit` | `/quit` | `commands/core.rs` | 566 | Exit TUI | ❌ Missing |
| `/model` | — | `commands/provider.rs` | 237 | Switch model | ❌ Missing |
| `/models` | — | `commands/provider.rs` | 237 | List models | ❌ Missing |
| `/provider` | — | `commands/provider.rs` | 237 | Switch provider | ❌ Missing |
| `/queue` | — | `commands/queue.rs` | 308 | Show queued ops | ❌ Missing |
| `/stash` | — | `commands/stash.rs` | 130 | Stash current input | ❌ Missing |
| `/hooks` | — | `commands/hooks.rs` | 333 | Manage hook config | ❌ Missing |
| `/subagents` | — | `commands/core.rs` | 566 | Sub-agent panel | ❌ Missing |
| `/links` | — | `commands/core.rs` | 566 | Show OSC-8 links | ❌ Missing |
| `/home` | — | `commands/core.rs` | 566 | Return to root view | ❌ Missing |
| `/note` | — | `commands/note.rs` | 131 | Save personal note | ❌ Missing |
| `/attach` | — | `commands/attachment.rs` | 128 | Attach a file as context | ❌ Missing |
| `/task` | — | `commands/task.rs` | 100 | Task tool surface | ❌ Missing |
| `/jobs` | — | `commands/jobs.rs` | 113 | Background jobs panel | ❌ Missing |
| `/mcp` | — | `commands/mcp.rs` | 119 | MCP server panel | ❌ Missing |
| `/save` | — | `commands/session.rs` | 531 | Save current session | ❌ Missing |
| `/sessions` | — | `commands/session.rs` | 531 | List sessions | ❌ Missing |
| `/load` | — | `commands/session.rs` | 531 | Load session | ❌ Missing |
| `/compact` | — | `commands/core.rs` | 566 | Compact conversation | ❌ Missing |
| `/context` | — | `commands/core.rs` | 566 | Show context window state | ❌ Missing |
| `/cycles` | — | `commands/cycle.rs` | 225 | List cycles | ❌ Missing |
| `/cycle` | — | `commands/cycle.rs` | 225 | Cycle controls | ❌ Missing |
| `/recall` | — | `commands/core.rs` | 566 | Recall from cycle archive | ❌ Missing |
| `/export` | — | `commands/share.rs` | 224 | Export transcript | ❌ Missing |
| `/config` | — | `commands/config.rs` | 1,111 | Edit config interactively | ❌ Missing |
| `/yolo` | — | `commands/core.rs` | 566 | Switch to YOLO mode | ❌ Missing |
| `/agent` | — | `commands/core.rs` | 566 | Switch to agent mode | ❌ Missing |
| `/plan` | — | `commands/core.rs` | 566 | Switch to plan mode | ❌ Missing |
| `/trust` | — | `commands/core.rs` | 566 | Workspace trust controls | ❌ Missing |
| `/logout` | — | `commands/core.rs` | 566 | Sign out (clear keyring) | ❌ Missing |
| `/tokens` | — | `commands/debug.rs` | 856 | Show token usage | ❌ Missing |
| `/system` | — | `commands/debug.rs` | 856 | Show system prompt | ❌ Missing |
| `/edit` | — | `commands/core.rs` | 566 | Open external editor | ❌ Missing |
| `/diff` | — | `commands/debug.rs` | 856 | Show diff against base | ❌ Missing |
| `/undo` | — | `commands/core.rs` | 566 | Undo last turn | ❌ Missing |
| `/retry` | — | `commands/core.rs` | 566 | Retry last turn | ❌ Missing |
| `/init` | — | `commands/init.rs` | 277 | Project init | ❌ Missing |
| `/lsp` | — | `commands/debug.rs` | 856 | LSP panel | ❌ Missing |
| `/share` | — | `commands/share.rs` | 224 | Share transcript | ❌ Missing |
| `/goal` | — | `commands/goal.rs` | 166 | Show / edit goal | ❌ Missing |
| `/settings` | — | `commands/config.rs` | 1,111 | Settings UI | ❌ Missing |
| `/statusline` | — | `commands/config.rs` | 1,111 | Statusline customization | ❌ Missing |
| `/skills` | — | `commands/skills.rs` | 477 | Skill management | ❌ Missing |
| `/skill` | — | `commands/skills.rs` | 477 | Run skill | ❌ Missing |
| `/review` | — | `commands/review.rs` | 138 | Review workflow | ❌ Missing |
| `/restore` | — | `commands/restore.rs` | 261 | Restore from snapshot | ❌ Missing |
| `/rlm` | — | `commands/core.rs` | 566 | Recursive LLM tool | ❌ Missing |
| `/cost` | — | `commands/debug.rs` | 856 | Show cost summary | ❌ Missing |
| `/profile` | — | `commands/core.rs` | 566 | Switch profile | ❌ Missing |
| `/cache` | — | `commands/debug.rs` | 856 | Cache controls | ❌ Missing |
| `/memory` | — | `commands/memory.rs` | 62 | Memory recall | ❌ Missing |

(Total: **49 slash commands**.)

### Gaps

- 0/49 slash commands implemented in Python.
- No slash command dispatcher in `engine/` or `tui/`.
- The `slash_menu` widget exists but has no underlying command registry.

**Severity: All P0/P1.** P0: `/help`, `/clear`, `/exit`, `/model`, `/sessions`, `/save`, `/load`, `/compact`, `/yolo`/`/agent`/`/plan` mode-switch family, `/init`, `/config`, `/skills`, `/mcp`, `/trust`. P1 / P2: the rest.

---

## 4. Prompts / Skills / Personalities / Modes / Approvals

### Rust prompt assets (`crates/tui/src/prompts/`)

- `base.md` (210 lines) — main system prompt (markdown)
- `base.txt` (46 lines) — plain-text base prompt
- `normal.txt` (6 lines) — normal-mode addendum
- `agent.txt` (15 lines) — agent-mode addendum
- `plan.txt` (8 lines) — plan-mode addendum
- `yolo.txt` (8 lines) — YOLO-mode addendum
- `compact.md` (26 lines) — compact-summary prompt
- `cycle_handoff.md` (76 lines) — cycle handoff prompt
- `subagent_output_format.md` (80 lines) — sub-agent output spec
- `modes/agent.md`, `modes/plan.md`, `modes/yolo.md` — mode-specific instructions
- `personalities/calm.md`, `personalities/playful.md` — personality variants
- `approvals/auto.md`, `approvals/never.md`, `approvals/suggest.md` — approval-policy explainers

### Rust skill subsystem

- `crates/tui/src/skills/install.rs` (1,190 LOC) — skill install/update/remove
- `crates/tui/src/skills/mod.rs` (693 LOC) — skill catalog, parsing, runtime
- `crates/tui/src/skills/system.rs` (187 LOC) — system skill registry
- `crates/tui/assets/skills/skill-creator/` — bundled skill assets

### Python state

- `engine/prompts.py` (8 LOC, stub `build_system_prompt()`).
- No prompt template files in repo.
- No `skills/` module.
- No personality / mode / approval text variants.

### Gaps

| Gap | Severity |
|---|---|
| 17 prompt template files not ported | **P0** |
| 3 mode prompts (agent/plan/yolo) | **P0** |
| 2 personality prompts (calm/playful) | **P1** |
| 3 approval-policy explainers (auto/never/suggest) | **P1** |
| Compact-summary + cycle-handoff + subagent-output-format prompts | **P0** |
| Skill subsystem (install / catalog / runtime ≈ 2,070 LOC + assets) | **P0** |

---

## 5. Major sub-managers missing in Python

These are top-level `crates/tui/src/*.rs` files that have no Python equivalent.

| Rust file | LOC | One-line purpose | Python status |
|---|---:|---|---|
| `task_manager.rs` | ~1,800 (66KB) | Durable task queue + worker (SQLite tables `tasks`, `task_attempts`, `task_gates`) | ❌ Missing |
| `automation_manager.rs` | ~900 (32KB) | Cron / heartbeat scheduler + run history | ❌ Missing |
| `cycle_manager.rs` | ~1,071 (37KB) | Cycle boundaries, briefing, archival | ❌ Missing |
| `compaction.rs` | ~2,008 (69KB) | Long-conversation summarization, working-set dedup | ❌ Missing |
| `seam_manager.rs` | ~700 (24KB) | Backtrack / divergence recovery | ❌ Missing |
| `session_manager.rs` | ~1,339 (48KB) | Multi-session persistence and recovery | ❌ Missing |
| `working_set.rs` | ~1,198 (40KB) | Active-context dedup (12-op window, 24 max paths) | ❌ Missing |
| `runtime_api.rs` | ~2,729 (88KB) | Runtime state HTTP API | ❌ Missing |
| `runtime_threads.rs` | ~4,413 (166KB) | Background coordination, cancellation tokens | ❌ Missing |
| `snapshot/repo.rs` | 664 | Workspace snapshot repo | ❌ Missing |
| `snapshot/{paths,prune,mod}.rs` | 272 | Snapshot retention + paths | ❌ Missing |
| `repl/runtime.rs` | 877 | REPL runtime | ❌ Missing |
| `repl/sandbox.rs` | 80 | REPL sandbox glue | ❌ Missing |
| `network_policy.rs` | ~700 (23KB) | Network access policy + audit log | ❌ Missing |
| `command_safety.rs` | ~1,200 (38KB) | Command arity dict + dangerous-pattern detection | ❌ Missing |
| `workspace_trust.rs` | ~286 (10KB) | Per-workspace trust persistence | ❌ Missing |
| `error_taxonomy.rs` | 477 | Error classification + retry hints | ❌ Missing |
| `audit.rs` | 45 | Audit log | ❌ Missing |
| `eval.rs` | 742 | Eval harness | ❌ Missing |
| `pricing.rs` | 177 | V4 pricing + cache-hit accounting | ⚠️ Partial (`client/pricing.py` 44 LOC) |
| `retry_status.rs` | 201 | Retry-After parsing | ❌ Missing |
| `memory.rs` | 197 | Memory store | ❌ Missing |
| `models.rs` | 515 | Provider/model catalogue | ⚠️ Partial (`config/provider_registry.py`) |
| `palette.rs` | 434 | Color palette | ❌ Missing |
| `project_context.rs` | 472 | Project-context loader | ❌ Missing |
| `project_doc.rs` | 133 | Project-doc loader | ❌ Missing |
| `schema_migration.rs` | 371 | DB schema migration | ⚠️ Partial (`state/migrations`) |
| `settings.rs` | 597 | Settings store | ❌ Missing |
| `utils.rs` | 707 | Shared utils | ❌ Missing |
| `localization.rs` | 1,863 | i18n strings | ❌ Missing |
| `logging.rs` | 72 | Logging setup | ❌ Missing |
| `mcp_server.rs` | 625 | MCP server-side process | ❌ Missing |
| `composer_history.rs` | 175 | Composer input history | ❌ Missing |
| `composer_stash.rs` | 304 | Composer input stash | ❌ Missing |
| `deepseek_theme.rs` | 176 | Default theme | ❌ Missing |
| `responses_api_proxy/{mod,read_api_key}.rs` | ~50 | Responses-API proxy | ❌ Missing |
| `rlm/turn.rs` + bridge / prompt | 1,550 | Recursive-LLM tool runtime | ❌ Missing |
| `commands/*.rs` | 7,699 | Slash commands (see §3) | ❌ Missing |
| `features.rs` | 244 | Feature flag table | ❌ Missing |

### Gaps

- ~30,000 LOC of top-level Rust managers are **unported**.
- Most are either P0 or P1 — without `task_manager`, `automation_manager`, `compaction`, `session_manager`, `working_set`, `cycle_manager`, `seam_manager`, the agent cannot run real long-running workflows.
- `runtime_threads.rs` (4,413 LOC) is the central async coordinator. Without it, no real concurrency.
- `runtime_api.rs` (2,729 LOC) is the HTTP/RPC façade — gates `app_server`.

---

## Phase E action items

### P0 — Block release ("百分百复刻" can't claim parity without these)

1. **CLI subcommand surface** — port all 22 subcommands + ~25 global flags. Use `argparse` or `click` to mirror clap structure. (~1,500 LOC)
2. **Slash-command dispatcher + the 15 P0 commands** (`/help`, `/clear`, `/exit`, `/model`, `/sessions`, `/save`, `/load`, `/compact`, `/yolo`, `/agent`, `/plan`, `/init`, `/config`, `/skills`, `/mcp`). (~2,500 LOC)
3. **Top-level UI orchestration** — port the `ui.rs` (7,055 LOC) and `app.rs` (4,140 LOC) state machines into Textual screens. (~3,000 LOC after architectural mapping)
4. **Streaming/transcript pipeline** — `streaming/{mod,chunking,commit_tick,line_buffer}` + `live_transcript` + `transcript` + `tool_routing` + `subagent_routing` + `shell_job_routing` + `mcp_routing`. (~3,000 LOC)
5. **Markdown + diff renderers**. (~1,000 LOC)
6. **Approval-gate UI** (1,688 LOC equivalent in Textual). (~600 LOC)
7. **Skill subsystem** (`skills/{install,mod,system}.rs` 2,070 LOC). (~1,200 LOC)
8. **Prompt template files** — port all 17 markdown/text templates verbatim, then load via `engine/prompts.py`. (~no logic, but data parity).
9. **Sub-managers** — `task_manager`, `automation_manager`, `compaction`, `session_manager`, `working_set`, `cycle_manager`, `seam_manager`, `runtime_threads`, `runtime_api`, `snapshot/*`, `command_safety`, `network_policy`, `workspace_trust`, `error_taxonomy`. (~25,000 LOC equivalent — biggest gap in the project).
10. **REPL runtime** (`repl/runtime.rs` 877 LOC) for scripting / non-interactive use.

### P1 — Core functionality

- Command palette + file mention + file picker / file tree.
- External editor invocation, paste / paste-burst handling.
- Sidebar (sessions/threads), header / footer / status picker / pending input preview.
- Keybinding registry, scrolling, pager, persistence actor.
- Eval harness (`eval.rs` 742 LOC).
- `models.rs` full provider/model catalogue.
- `settings.rs` settings store (597 LOC).
- `project_context.rs` + `project_doc.rs` (605 LOC).
- `composer_history.rs` + `composer_stash.rs` (479 LOC).
- Backtrack / undo flow.
- Context inspector / context menu / active cell.
- Notifications, OSC-8 hyperlinks, clipboard.

### P2 — Polish / parity

- Onboarding screen, frame-rate limiter, transcript cache.
- Help screen, model picker / provider picker (UI panels — there are CLI equivalents).
- `localization.rs` 1,863 LOC — port all i18n strings.
- Theme (`deepseek_theme.rs`).
- Personalities (calm/playful) + approval policy explainer prompts.
- UI integration test harness (3,052 LOC) — port to Textual snapshot-test framework.

---

## Summary

- **Phase E parity: <1%** (~544 / ~88,000 LOC).
- 49 slash commands → 0 implemented.
- 22 CLI subcommands → 0 implemented (only TUI-launch path).
- 48 widget files → ~9 widgets ported; UI orchestrator (`ui.rs` 7K LOC) absent.
- 17 prompt templates → 1 stub function.
- 30+ top-level sub-managers → 0 ported.
- **Estimated effort to reach parity: 4–6 months full-time** (largest single block of work in the project).
