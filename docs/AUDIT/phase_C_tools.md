# Phase C Audit — Tools (74 total)

**Audit Date:** 2026-05-06

---

## Module summary table

| Metric | Value |
|--------|-------|
| Rust tools LOC | ~25,965 (`tools/*.rs` 20,023 + `subagent/` ~5,942) |
| Python tools LOC | 2,914 |
| Coverage ratio | ~11% (Python / Rust) |
| Rust complexity | High: PTY / sandbox / async / durable persistence across 38+ modules |
| Python status | Basic stub implementation; in-memory only; missing or stub for ~50/74 tools |

---

## Inventory table

| Tool Name | Rust File | Rust LOC | One-line Purpose | Python Status | Py File | Severity |
|-----------|-----------|----------|-----------------|---------------|---------|----------|
| read_file | file.rs | 800 | Read UTF-8 files with PDF extraction via pdftotext | Implemented | file_tools.py | P0 |
| write_file | file.rs | 800 | Write/create files within workspace boundary | Implemented | file_tools.py | P0 |
| edit_file | file.rs | 800 | Apply line-based edits with unified diff preview | Implemented | file_tools.py | P0 |
| list_dir | file.rs | 800 | Recursively list directory tree with metadata | Implemented | file_tools.py | P0 |
| grep_files | search.rs | 572 | Search file contents with regex patterns and context | Implemented | search_tools.py | P0 |
| file_search | file_search.rs | 325 | Fuzzy search filenames across workspace | Implemented | search_tools.py | P0 |
| exec_shell | shell.rs | 2298 | Execute shell commands with PTY/sandbox/timeout | Implemented (no PTY/sandbox) | shell_tools.py | P0 |
| exec_shell_wait | shell.rs | 2298 | Poll background shell job status/output | Implemented (in-memory) | shell_tools.py | P0 |
| exec_shell_interact | shell.rs | 2298 | Send stdin to running shell job | Implemented (in-memory) | shell_tools.py | P0 |
| shell_cancel | shell.rs | 2298 | Terminate background shell job | Implemented (in-memory) | shell_tools.py | P0 |
| exec_wait | shell.rs | 2298 | Alias for exec_shell_wait (legacy) | Implemented | shell_tools.py | P0 |
| exec_interact | shell.rs | 2298 | Alias for exec_shell_interact (legacy) | Implemented | shell_tools.py | P0 |
| apply_patch | apply_patch.rs | 1469 | Apply unified diff with fuzzy matching & conflict resolution | Implemented (naive) | utility_tools.py | P0 |
| git_status | git.rs | 432 | Show git status; porcelain format | Implemented | git_tools.py | P0 |
| git_diff | git.rs | 432 | Show git diff with context lines | Implemented | git_tools.py | P0 |
| git_log | git_history.rs | 627 | Show git commit log with filtering | Implemented | git_tools.py | P0 |
| git_show | git_history.rs | 627 | Show specific commit details | Implemented | git_tools.py | P0 |
| git_blame | git_history.rs | 627 | Show per-line git blame | Implemented | git_tools.py | P0 |
| github_issue_context | github.rs | 587 | Fetch GitHub issue body + comments | Stub (gh CLI shell-out) | github_tools.py | P1 |
| github_pr_context | github.rs | 587 | Fetch GitHub PR body + reviews | Stub (gh CLI shell-out) | github_tools.py | P1 |
| github_comment | github.rs | 587 | Post comment to GitHub issue/PR | Stub (gh CLI shell-out) | github_tools.py | P1 |
| github_close_issue | github.rs | 587 | Close GitHub issue with optional message | Stub (gh CLI shell-out) | github_tools.py | P1 |
| web_search | web_search.rs | 558 | Search the web with query string | Stub | web_tools.py | P1 |
| fetch_url | fetch_url.rs | 509 | Fetch URL content; follow redirects; extract text | Stub | web_tools.py | P1 |
| web_run | web_run.rs | 1763 | Browser automation: navigate, click, fill, screenshot | Missing | web_tools.py | P0 |
| finance | fetch_url.rs + web_search.rs | 1068 | Financial data lookup (stocks, crypto, market rates) | Missing | web_tools.py | P2 |
| task_create | tasks.rs | 1012 | Enqueue durable background task via TaskManager (SQLite) | In-memory stub | task_tools.py | P0 |
| task_list | tasks.rs | 1012 | List recent durable tasks with status | In-memory stub | task_tools.py | P0 |
| task_read | tasks.rs | 1012 | Read durable task detail, timeline, artifacts | In-memory stub | task_tools.py | P0 |
| task_cancel | tasks.rs | 1012 | Cancel queued/running task | In-memory stub | task_tools.py | P0 |
| task_gate_run | tasks.rs | 1012 | Run task gate with evidence submission | Missing | task_tools.py | P0 |
| task_shell_start | tasks.rs | 1012 | Start shell job within durable task context | Missing | task_tools.py | P0 |
| task_shell_wait | tasks.rs | 1012 | Poll task-linked shell job | Missing | task_tools.py | P0 |
| pr_attempt_record | tasks.rs | 1012 | Record PR attempt metadata + outcome | Missing | task_tools.py | P1 |
| pr_attempt_list | tasks.rs | 1012 | List recent PR attempts | In-memory stub | task_tools.py | P1 |
| pr_attempt_read | tasks.rs | 1012 | Read detailed PR attempt record | In-memory stub | task_tools.py | P1 |
| pr_attempt_preflight | tasks.rs | 1012 | Validate PR attempt preconditions | Missing | task_tools.py | P1 |
| pr_attempt_create | tasks.rs | 1012 | Create new PR attempt | In-memory stub | task_tools.py | P1 |
| pr_attempt_update | tasks.rs | 1012 | Update PR attempt fields | In-memory stub | task_tools.py | P1 |
| pr_attempt_complete | tasks.rs | 1012 | Mark attempt complete | In-memory stub | task_tools.py | P1 |
| pr_attempt_cancel | tasks.rs | 1012 | Cancel attempt | In-memory stub | task_tools.py | P1 |
| automation_create | automation.rs | 382 | Create cron-scheduled automation task | In-memory stub | automation_tools.py | P1 |
| automation_list | automation.rs | 382 | List active automations | In-memory stub | automation_tools.py | P1 |
| automation_read | automation.rs | 382 | Read automation detail + execution history | In-memory stub | automation_tools.py | P1 |
| automation_update | automation.rs | 382 | Update automation schedule/prompt | In-memory stub | automation_tools.py | P1 |
| automation_pause | automation.rs | 382 | Pause automation | In-memory stub | automation_tools.py | P1 |
| automation_resume | automation.rs | 382 | Resume paused automation | In-memory stub | automation_tools.py | P1 |
| automation_delete | automation.rs | 382 | Delete automation permanently | In-memory stub | automation_tools.py | P1 |
| automation_run | automation.rs | 382 | Trigger automation immediately | In-memory stub | automation_tools.py | P1 |
| agent_spawn | subagent/mod.rs | 1200+ | Spawn sub-agent with type/toolset/workspace | In-memory stub (no real loop) | subagent_tools.py | P0 |
| spawn_agent | subagent/mod.rs | 1200+ | Alias for agent_spawn | In-memory stub | subagent_tools.py | P0 |
| delegate_to_agent | subagent/mod.rs | 1200+ | Delegate work to sub-agent with blocking wait | Missing | subagent_tools.py | P0 |
| agent_result | subagent/mod.rs | 1200+ | Retrieve sub-agent result (non-blocking poll) | In-memory stub | subagent_tools.py | P0 |
| send_input | subagent/mod.rs | 1200+ | Send user input to sub-agent stdin | Missing | subagent_tools.py | P0 |
| agent_send_input | subagent/mod.rs | 1200+ | Alias for send_input | Missing | subagent_tools.py | P0 |
| agent_assign | subagent/mod.rs | 1200+ | Reassign sub-agent objective/role | In-memory stub | subagent_tools.py | P0 |
| assign_agent | subagent/mod.rs | 1200+ | Alias for agent_assign | Missing | subagent_tools.py | P0 |
| wait | subagent/mod.rs | 1200+ | Poll sub-agent status; returns snapshot | Missing | subagent_tools.py | P0 |
| agent_wait | subagent/mod.rs | 1200+ | Alias for wait | In-memory stub | subagent_tools.py | P0 |
| agent_resume | subagent/mod.rs | 1200+ | Resume paused/completed sub-agent | Missing | subagent_tools.py | P0 |
| agent_close | subagent/mod.rs | 1200+ | Terminate sub-agent and cleanup | Missing | subagent_tools.py | P0 |
| agent_cancel | subagent/mod.rs | 1200+ | Cancel sub-agent immediately | In-memory stub | subagent_tools.py | P0 |
| agent_list | subagent/mod.rs | 1200+ | List active/recent sub-agents | In-memory stub | subagent_tools.py | P0 |
| rlm_query | rlm.rs | 406 | Recursive LLM loop: process long input through full agent cycle | Missing | — | P1 |
| review | review.rs | 540 | Code review via LLM with structured output | Missing | — | P1 |
| remember | remember.rs | 138 | Append bullets to user memory file | Missing | — | P1 |
| skill_load | skill.rs | 365 | Load SKILL.md + companion files into context | Missing | utility_tools.py | P1 |
| spec | spec.rs | 674 | Tool specification framework (not a callable tool) | N/A | — | N/A |
| plan_update | plan.rs | 406 | Update session plan with structured sections | Missing | — | P1 |
| note | shell.rs (subset) | ~60 | Append note to notes file | Missing | — | P1 |
| recall_archive | recall_archive.rs | 723 | Search prior session archives for context | Missing | — | P1 |
| revert_turn | revert_turn.rs | 205 | Revert workspace to pre-turn state via snapshot | Missing | — | P1 |
| validate_data | validate_data.rs | 316 | Validate structured data (JSON schema, regex, etc.) | Missing | utility_tools.py | P1 |
| run_tests | test_runner.rs | 253 | Run cargo / pytest / npm tests; parse + report | Missing | — | P1 |
| truncate | truncate.rs | 613 | Truncate context window; drop oldest turns/messages | Missing | — | P1 |
| parallel | parallel.rs | 67 | Meta-tool for parallel execution (legacy) | N/A | — | N/A |
| request_user_input | user_input.rs | 260 | Prompt user for input (blocks on stdin) | Missing | — | P1 |
| diagnostics | diagnostics.rs | 251 | Collect workspace diagnostics (git, node, py, etc.) | Implemented | utility_tools.py | P0 |
| project_map | project.rs | 82 | Generate project topology graph (experimental) | Implemented | utility_tools.py | P0 |
| registry | registry.rs | 1157 | Tool registry & builder (framework; not callable) | Partial | registry.py / builder.py | P0 |
| approval_cache | approval_cache.rs | 280 | Approval fingerprinting & caching (framework) | Missing | — | P0 |
| checklist_write | todo.rs | 630 | Write/replace checklist (durable) | Missing | todo_tools.py | P1 |
| checklist_add | todo.rs | 630 | Add checklist item | Missing | todo_tools.py | P1 |
| checklist_update | todo.rs | 630 | Update checklist item status/text | Missing | todo_tools.py | P1 |
| checklist_list | todo.rs | 630 | List current checklist items | Missing | todo_tools.py | P1 |
| todo_write | todo.rs | 630 | Write todo list (alias for checklist_write) | Implemented | todo_tools.py | P1 |
| todo_add | todo.rs | 630 | Add todo item | Implemented | todo_tools.py | P1 |
| todo_update | todo.rs | 630 | Update todo item | Implemented | todo_tools.py | P1 |
| todo_list | todo.rs | 630 | List todos | Implemented | todo_tools.py | P1 |
| list_mcp_resources | (adapter) | — | List available MCP resources | Stub | mcp_tools.py | P2 |
| list_mcp_resource_templates | (adapter) | — | List MCP resource templates | Stub | mcp_tools.py | P2 |
| read_mcp_resource | (adapter) | — | Read MCP resource by name | Stub | mcp_tools.py | P2 |
| mcp_get_prompt | (adapter) | — | Fetch MCP prompt by identifier | Stub | mcp_tools.py | P2 |

**Tools identified: ~74** (some Rust tools register multiple aliases — see registry.rs).

---

## 1. File / Search / Shell / Apply_patch

### Rust complexity
- **file.rs (800 LOC):** 4 tools (read_file, write_file, edit_file, list_dir). Features: UTF-8 validation, PDF extraction via pdftotext (poppler), unified diff generation, path escape validation.
- **file_search.rs (325 LOC):** Fuzzy filename search via the `ignore` crate.
- **search.rs (572 LOC):** Regex-based grep with context lines, binary file detection, symlink handling.
- **shell.rs (2,298 LOC):** 6 tools. Features: PTY allocation (`portable_pty`), background process tracking (UUID-based job server), output truncation/summarization, sandbox integration (macOS Seatbelt), timeout enforcement (`wait_timeout`), streaming pipes for stdin/stdout/stderr, shell status tracking (Running / Completed / Failed / TimedOut), env scrubbing.
- **apply_patch.rs (1,469 LOC):** Unified diff application with fuzzy line matching (MAX_FUZZ=50), conflict detection, auto-resolve heuristics, context reconstruction.

### Python gaps
- `read_file`: implemented but **missing PDF extraction**.
- `write_file`, `edit_file`: implemented but **no diff preview / merge conflict markers**.
- `grep_files`, `file_search`: implemented but **no binary detection / advanced regex modes**.
- `exec_shell`: implemented but **missing PTY support, sandbox enforcement, env scrubbing**.
- `exec_shell_wait` / `exec_shell_interact` / `shell_cancel`: in-memory only — **no SQLite persistence**.
- `apply_patch`: implemented but **no fuzzy matching, no conflict heuristics**; requires exact line boundaries.

---

## 2. Git / GitHub / Web / Fetch_url

### Rust complexity
- **git.rs (432 LOC):** porcelain parsing, unified diff output.
- **git_history.rs (627 LOC):** commit filtering (author, date range), blame with original line mapping, pagination.
- **github.rs (587 LOC):** REST API v3 auth (token / SSH key), issue/PR body + comments assembly, approval-gated writes.
- **web_search.rs (558 LOC):** pagination, snippet extraction.
- **fetch_url.rs (509 LOC):** redirect following, content-type sniffing, text extraction (trafilatura/html2text).
- **web_run.rs (1,763 LOC):** headless browser (Chrome via puppeteer-rs / playwright bindings), screenshot, form fill, click/scroll/keyboard, tab management, cookies, network interception.

### Python gaps
- Git tools: implemented (good).
- GitHub tools: shell out to `gh` CLI — **missing direct REST API integration**, no token/auth handling.
- `web_search`: stub — no actual backend.
- `fetch_url`: stub — **missing trafilatura / html-to-text** conversion.
- `web_run`: missing entirely — **needs Playwright/Selenium** integration.

---

## 3. Task / PR_attempt / Automation / Subagent (durable execution chain)

This is the **largest architectural gap** in the rewrite.

### Rust complexity
- **tasks.rs (1,012 LOC):** 12 tools. Features: TaskManager + SQLite tables (`tasks`, `task_attempts`, `task_gates`), per-task shell job context, gate evidence collection, PR attempt metadata + outcome tracking, approval requirements.
- **automation.rs (382 LOC):** 8 tools + cron scheduling via tokio timers, execution history, pause/resume state machine.
- **subagent/mod.rs (1,200+ LOC) + agent crate (307 LOC):** 12+ tools. Features:
  - Sub-agent process spawning (tokio task per agent)
  - Mailbox-based message passing
  - Per-type tool filtering (General / Explore / Plan / Review / Implementer / Verifier / Custom)
  - Spawn depth tracking (default max = 3)
  - Cancellation token propagation
  - JSON state file persistence
  - Session boot id for prior-session filtering

### Python gaps
- **Task tools:** all in-memory; **no SQLite TaskManager**.
- **PR_attempt tools:** all in-memory.
- **Automation tools:** all in-memory; **no cron scheduler**.
- **Subagent tools:** in-memory metadata only; **the actual agent loop never runs** — `agent_spawn` returns a record but no LLM loop is started, so children never execute tools.

**Impact:** any workflow requiring restart-awareness, scheduled execution, PR state tracking, or sub-agent work silently fails or loses state on process restart.

---

## 4. RLM / Remember / Skill / Spec / Plan / Note

- **rlm.rs (406 LOC):** Recursive LLM loop. Long-input chunking, full agent cycle per chunk, output assembly. **Missing in Python.**
- **remember.rs (138 LOC):** Append to user memory file with structured bullets. **Missing in Python.**
- **skill.rs (365 LOC):** Load SKILL.md + companion files. Directory traversal, file discovery, cache. **Missing in Python.**
- **spec.rs (674 LOC):** ToolSpec trait + ToolCapability enum + ToolContext + ToolResult + ToolError. Python `tools/base.py` only partially mirrors this — **capability flags and full context are simplified**.
- **plan.rs (406 LOC):** Update structured plan sections (goal / approach / next), persistent state. **Missing in Python.**
- **note (in shell.rs):** Append to notes file. **Missing in Python.**

---

## 5. Diagnostics / Project / Recall_archive / Revert_turn / Validate_data / Test_runner / Truncate / Parallel / User_input

| Tool | Rust LOC | Python status |
|---|---:|---|
| diagnostics | 251 | Implemented (basic) |
| project_map | 82 | Implemented (basic) |
| recall_archive | 723 | **Missing**; no archive system |
| revert_turn | 205 | **Missing**; no snapshot mechanism |
| validate_data | 316 | **Missing**; no schema validation |
| run_tests | 253 | **Missing**; no test framework integration |
| truncate | 613 | **Missing**; no context-window management tool |
| parallel | 67 | N/A (legacy) |
| request_user_input | 260 | **Missing** |

---

## 6. Registry, capability flags, approval_cache, tool_parser, sandbox

- **registry.rs (1,157 LOC):** `ToolRegistry { HashMap<String, Arc<dyn ToolSpec>> }` with **alphabetical sorting for KV prefix cache stability** (issue #263), `OnceLock`-based `api_cache` memoization, `filter_by_capability()`, `approval_required_tools()`, `ToolRegistryBuilder` with 15+ `with_*` methods (`with_file_tools`, `with_shell_tools`, `with_agent_tools`, `with_full_agent_surface`, etc.).
- **approval_cache.rs (280 LOC):** Fingerprinting + approval state caching. Tool name + input hash, per-user approval decisions, expiration. Fingerprints `apply_patch` (file paths), `exec_shell` (first 3 tokens), `fetch_url` (hostname).
- **tool_parser** (in `core/tool_parser.rs`, 510 LOC): JSON schema input parsing, helper functions (`required_str`, `optional_str`, etc.), fragment reassembly across stream chunks.
- **sandbox** (`crates/tui/src/sandbox/`): SandboxManager + SandboxPolicy (Disabled/Restricted/Standard/Strict), SandboxType (Seatbelt on macOS, seccomp/landlock on Linux). Integrated with shell execution.

### Python gaps
- `registry.py`: basic dict-based store. **Missing alphabetical sorting** (breaks DeepSeek KV cache stability), no `OnceLock` cache, no `to_api_tools_with_cache()`, no `filter_by_capability()`, no `approval_required_tools()`.
- `builder.py` (~100 LOC): missing `with_full_agent_surface`, missing subagent builder methods, missing role models.
- `approval_cache`: **missing entirely**.
- `tool_parser`: implicit in `base.py`; no fingerprinting.
- `sandbox`: no Python sandbox integration; shell execution is direct.

---

## Phase C action items

### P0 (Critical — blocks "百分百复刻")
1. **Durable Task system** — SQLite schema (`tasks`, `task_attempts`, `task_gates`), `TaskManager`, 7 task tools (`task_create` / `task_list` / `task_read` / `task_cancel` / `task_gate_run` / `task_shell_start` / `task_shell_wait`).
2. **Sub-agent runtime** — async tasks per agent, mailbox message passing, tool registry per agent type, depth limit, cancellation tokens, 14 subagent tools.
3. **Browser automation (`web_run`)** — Playwright/Selenium integration, ~10 interaction methods.
4. **Snapshot / revert mechanism** — workspace snapshot repo, revert_turn integration, recall_archive search.
5. **Apply_patch fuzzy matching** — port the fuzzy line matcher (MAX_FUZZ=50) and conflict detection from `apply_patch.rs`.
6. **Shell PTY + sandbox** — replace direct subprocess with PTY (`ptyprocess` or `pexpect`) and integrate the macOS Seatbelt / Linux Landlock sandbox calls described in Phase B.
7. **Approval cache with fingerprinting** — port `approval_cache.rs` to Python, with the same fingerprint rules.
8. **Registry alphabetical sorting + cache** — fix `registry.py` so DeepSeek KV prefix cache stability is restored (breaks otherwise on every call).

### P1 (High — missing core workflows)
9. **GitHub REST API integration** — replace `gh` shell-out with proper REST client + token auth.
10. **Automation cron scheduler** — port `automation.rs` to Python with APScheduler / `croniter` and durable run history.
11. **RLM, Remember, Plan, Note** — recursive LLM loop, memory file, plan state, notes file.
12. **`run_tests` / `truncate` / `request_user_input`** — context management + user interaction.
13. **`skill_load`** — SKILL.md discovery and context injection (paired with `skills/` subsystem in Phase E).
14. **`validate_data`** — JSON schema, regex, type checking.
15. **PDF / HTML extractors** — wire up `pdftotext` (poppler) for `read_file`, trafilatura/html2text for `fetch_url`.

### P2 (Medium — nice-to-have)
16. **Finance tool** — stocks/crypto data lookups (requires third-party API keys).
17. **MCP tools full resource/template support** — currently stub adapters only.
18. **Recall_archive** — archive indexing and prior-session search.

### Technical debt
- Standardize `ToolError` codes and metadata across Python tools.
- Audit async/await patterns in Python; ensure timeout enforcement.
- `diff_format` / `shell_output` utility modules — Python has neither.
- `parallel.rs` is legacy (DeepSeek now has native parallel calls); document this.

---

## Summary

- **74 tools across 38+ Rust modules (25,965 LOC)** vs **Python 2,914 LOC**.
- ~24 Python tools are real implementations (file, search, git, shell basics, todo, diagnostics, apply_patch — the last with caveats).
- ~22 are in-memory stubs (task, automation, subagent, pr_attempt, mcp adapters).
- ~28+ are entirely missing (web_run, finance, rlm, remember, plan, note, skill_load, recall_archive, revert_turn, validate_data, run_tests, truncate, request_user_input, review, durable task gate / shell tools, github_* if you treat shell-out as missing, approval_cache, sandbox).
- Critical missing capabilities: **durable task chain**, **subagent loop**, **browser automation**, **snapshot/revert**, **fuzzy patching**, **PTY/sandbox shell**, **approval fingerprinting**, **registry alphabetical pinning** (DeepSeek prefix-cache requirement).
- **Estimated effort to reach 100% parity: 6–10 weeks full-time** for Phase C alone.
