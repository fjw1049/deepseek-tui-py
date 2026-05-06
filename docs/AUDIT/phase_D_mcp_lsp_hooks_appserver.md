# Phase D Audit — MCP / LSP / Hooks / App Server

**Audit Date:** 2026-05-06

---

## Module Summary Table

| Component | Rust File(s) | Rust LOC | Python File(s) | Python LOC | Parity % | Status |
|-----------|--------------|----------|-----------------|-----------|---------|--------|
| **MCP** | `crates/mcp/src/lib.rs`, `crates/tui/src/mcp.rs`, `crates/tui/src/mcp_server.rs` | 893 + 1983 + 625 = 3501 | `src/deepseek_tui/mcp/` (6 files) | 430 | 28% | **CRITICAL GAP** |
| **LSP** | `crates/tui/src/lsp/{client,diagnostics,mod,registry}.rs` | 485 + 216 + 535 + 146 = 1382 | `src/deepseek_tui/lsp/` (5 files) | 483 | 35% | **CRITICAL GAP** |
| **Hooks** | `crates/hooks/src/lib.rs`, `crates/tui/src/hooks.rs` | 170 + 914 = 1084 | `src/deepseek_tui/hooks/` (4 files) | 267 | 25% | **CRITICAL GAP** |
| **App Server / Runtime API** | `crates/app-server/src/lib.rs`, `crates/tui/src/runtime_api.rs`, `crates/tui/src/runtime_threads.rs` | 783 + 2729 + 4413 = 7925 | `src/deepseek_tui/app_server/` (4 files) | 252 | 3% | **SEVERE SHORTFALL** |
| **Total Phase D** | — | **13,892** | — | **1,432** | **10%** | **❌ INCOMPLETE** |

---

## 1. MCP (Model Context Protocol)

### Rust Surface (3,501 LOC)

**File:** `crates/mcp/src/lib.rs` (893 lines)
- **Stdio JSON-RPC handshake**: `run_stdio_server()` (line 437) with full lifecycle state machine.
- **Configuration**: `McpServerConfig`, `McpServerDefinition`, `ToolFilter` with allow/deny lists (lines 10–35).
- **Manager**: `McpManager` with tool filtering, qualified name generation (lines 147–303).
- **Tool qualification**: `qualify_tool_name()` with hash truncation (lines 332–347).
- **Startup events**: `McpStartupStatus` (Starting/Ready/Failed/Cancelled), `McpStartupUpdateEvent`, `McpStartupCompleteEvent` (lines 37–63).
- **Resource/prompt support**: `list_resources()`, `read_resource()`, `update_sandbox_state()` (lines 267–302).
- **RPC methods**: `initialize`, `healthz`, `capabilities`, `tools/list`, `tools/call`, `resources/list`, `resources/read`, `server/{list,register,start,stop,unregister}`, `shutdown` (lines 579–831).

**Files:** `crates/tui/src/mcp.rs` (1,983 lines) + `mcp_server.rs` (625 lines)
- **HTTP transport**: `HttpMcpClient` for URL-based MCP servers with URL masking & credential redaction (lines 31–84).
- **Connection pooling**: `McpClient` per server with async I/O, request/response correlation via `id`.
- **Timeouts**: Global & per-server configurable (connect, execute, read) (lines 98–127).
- **Error handling**: Bounded body excerpt preview, token masking (lines 71–84).
- **Tool discovery**: `list_tools()`, `call_tool()` with typed results.
- **MCP server lifecycle**: Startup events emitted via callbacks, server configuration from TOML.

### Python Surface (430 LOC)

**Files:** `src/deepseek_tui/mcp/` (6 files)
- **config.py** (35 LOC): `McpServerConfig` dataclass with basic fields (command, args, env, enabled).
- **client.py** (164 LOC): `McpClient` with stdio JSON-RPC, `list_tools()`, `call_tool()`, `list_resources()`, `read_resource()`, `get_prompt()`.
- **manager.py** (124 LOC): `McpManager` for multi-server dispatch, `discover_tools()`, `call_tool()`, tool filtering via `tool_filter.accepts()`.
- **encoding.py** (26 LOC): `qualify_tool_name()`, `parse_qualified_tool_name()` (simplified; no hash truncation).
- **loader.py** (64 LOC): Config loading stub.
- **__init__.py** (17 LOC): Module exports.

### Gaps

1. **HTTP MCP transport**: ❌ Rust has full HTTP client with `reqwest`, URL/auth masking, bounded preview. Python: `raise NotImplementedError("HTTP MCP transport is not implemented yet")` in `client.py:38`.
2. **Tool qualification hash truncation**: ❌ Rust truncates long names to 48 chars + 12-char hash (`qualify_tool_name()` line 338–345). Python uses simple prefix without truncation (line 7, encoding.py).
3. **Startup event emission & lifecycle**: ⚠️ Rust has full `McpStartupUpdateEvent`, `McpStartupCompleteEvent` with ready/failed/cancelled tracking. Python stub in manager (no event emission).
4. **Stdio JSON-RPC server**: ❌ Rust runs full server (`run_stdio_server()`) with all 13 methods. Python has no equivalent stdio server implementation.
5. **Resource templates**: ⚠️ Rust supports `resources/templates/list`. Python stub in `list_resource_templates()` (manager.py:78–82) with no actual support.
6. **Sandbox state updates**: ❌ Rust's `update_sandbox_state()` (line 289) unimplemented in Python.
7. **TOML config parsing**: ⚠️ Rust loads `mcp.json` with full schema. Python loader.py minimal.

**Parity: 28%**

---

## 2. LSP (Language Server Protocol)

### Rust Surface (1,382 LOC)

**File:** `crates/tui/src/lsp/mod.rs` (535 lines)
- **Configuration**: `LspConfig` with enabled flag, poll timeout, max diagnostics, warning filter, server overrides (lines 53–82).
- **Manager**: `LspManager` with lazy per-language client spawning (lines 101–247).
- **Lifecycle**: `diagnostics_for()` sends `didOpen`/`didChange`, waits `poll_after_edit_ms`, collects results (lines 104–139).
- **Missing server warning guard**: `_warned_missing` set prevents spam (lines 91–93).
- **Post-edit timeout enforcement**: Configurable delay before diagnostics poll (line 58).

**File:** `crates/tui/src/lsp/client.rs` (485 lines)
- **Transport layer**: `LspTransport` trait for pluggable backends.
- **Stdio transport**: Full LSP protocol with Content-Length headers, JSON message framing.
- **Lifecycle**: `initialize()`, `didOpen()`, `didChange()`, message correlation via `id`.
- **Diagnostics collection**: `PublishDiagnostics` notification handler with per-file storage.

**File:** `crates/tui/src/lsp/diagnostics.rs` (216 lines)
- **Diagnostic types**: `Severity` (Error=1, Warning=2), `Diagnostic` struct (line, column, message, code).
- **Rendering**: `render_blocks()` for terminal display.

**File:** `crates/tui/src/lsp/registry.rs` (146 lines)
- **Language detection**: `Language` enum (Rust, Go, Python, TypeScript, JavaScript, C, Cpp, Other).
- **File extension mapping**: `detect_language()` from path extension (lines 65–79).
- **Server registry**: `server_for()` returns hard-coded (command, args) for each language (lines 86–97):
  - Rust: `rust-analyzer`
  - Go: `gopls serve`
  - Python: `pyright-langserver --stdio`
  - TypeScript/JavaScript: `typescript-language-server --stdio`
  - C/Cpp: `clangd`

### Python Surface (483 LOC)

**Files:** `src/deepseek_tui/lsp/` (5 files)
- **manager.py** (111 LOC): `LspManager` with lazy spawning, per-language client reuse, `_warned_missing` guard.
- **client.py** (225 LOC): `StdioLspTransport` with Content-Length framing, `did_open()`, `did_change()`, diagnostics storage.
- **diagnostics.py** (55 LOC): `Diagnostic`, `Severity`, `DiagnosticBlock` types.
- **registry.py** (71 LOC): Language detection and server registry (identical to Rust mapping).
- **__init__.py** (21 LOC): Exports.

### Gaps

1. **Post-edit timeout enforcement**: ⚠️ Rust enforces via `poll_after_edit_ms` with `asyncio.sleep()` (mod.rs:58). Python sleeps but config integration unclear.
2. **Missing server warning guard**: ✓ Both have `_warned_missing` set to prevent spam.
3. **Server pool reuse**: ✓ Both reuse clients per language.
4. **Hook integration**: ❌ Rust LSP integration with hooks system (core/engine/lsp_hooks.rs mentioned but not fully audited). Python has no hooks integration visible.
5. **Diagnostic filtering**: ✓ Both filter by severity; Python identical logic.
6. **Language detection completeness**: ✓ Parity on extension mapping and registry.

**Parity: 35%**

---

## 3. Hooks

### Rust Surface (1,084 LOC)

**File:** `crates/hooks/src/lib.rs` (170 lines)
- **HookEvent types** (Response lifecycle):
  - `ResponseStart { response_id }`
  - `ResponseDelta { response_id, delta }`
  - `ResponseEnd { response_id }`
  - `ToolLifecycle { response_id, tool_name, phase, payload }`
  - `JobLifecycle { job_id, phase, progress, detail }`
  - `ApprovalLifecycle { approval_id, phase, reason }`
  - `GenericEventFrame { frame }`
- **Sinks** (async trait):
  - `StdoutHookSink`: Print to stdout
  - `JsonlHookSink`: Append to JSONL log file with timestamp
  - `WebhookHookSink`: POST to URL with **3-retry exponential backoff** (200ms × retry count)
- **Dispatcher**: `HookDispatcher` broadcasts events to all sinks.

**File:** `crates/tui/src/hooks.rs` (914 lines)
- **Session lifecycle events**:
  - `SessionStart`
  - `SessionEnd`
- **Message events**:
  - `MessageSubmit`
- **Tool events**:
  - `ToolCallBefore`
  - `ToolCallAfter`
- **Mode events**:
  - `ModeChange`
- **Error events**:
  - `OnError`
- **Hook conditions** (lines 64–92):
  - `Always` (default)
  - `ToolName { name }`
  - `ToolCategory { category }`
  - `Mode { mode }`
  - `ExitCode { code }` (for ToolCallAfter)
  - `All { conditions }` (AND)
  - `Any { conditions }` (OR)
- **Hook definition** (lines 95–122):
  - `event: HookEvent`
  - `command: String` (shell command, platform-agnostic: `sh -c` Unix, `cmd /C` Windows)
  - `condition: Option<HookCondition>`
  - `timeout_secs: u64` (default 30)
  - `background: bool`
  - `continue_on_error: bool` (default true)
  - `name: Option<String>`
- **HookContext** (lines 216–246):
  - tool_name, tool_args, tool_result, tool_exit_code, tool_success
  - mode, previous_mode
  - session_id, message
  - error_message
  - workspace, model, total_tokens, session_cost
  - Builder methods for all fields.

### Python Surface (267 LOC)

**Files:** `src/deepseek_tui/hooks/` (4 files)
- **events.py** (116 LOC): Dataclasses for response lifecycle
  - `ResponseStartEvent`, `ResponseDeltaEvent`, `ResponseEndEvent`
  - `ToolLifecycleEvent`, `JobLifecycleEvent`, `ApprovalLifecycleEvent`
  - `GenericEventFrameEvent`
  - Union type `HookEvent` and `event_to_dict()` converter
- **sinks.py** (96 LOC): Abstract sink interface and implementations
  - `HookSink` ABC with `emit(event) -> Awaitable`
  - `StdoutHookSink`, `JsonlHookSink`, `WebhookHookSink` (no retry logic visible)
- **dispatcher.py** (25 LOC): `HookDispatcher` broadcasts to sinks.
- **__init__.py** (30 LOC): Exports.

### Gaps

1. **Session/Message/Tool/Mode/Error events**: ❌ Python hooks.py has only response/tool/job/approval lifecycle events. Missing:
   - SessionStart / SessionEnd
   - MessageSubmit
   - ToolCallBefore / ToolCallAfter (only ToolLifecycle present)
   - ModeChange
   - OnError
2. **Hook conditions**: ❌ No Python equivalent of `HookCondition` enum (ToolName, ToolCategory, Mode, ExitCode, All, Any).
3. **Webhook retries & backoff**: ❌ Rust has explicit 3-retry loop with exponential backoff (`200 * retries` ms). Python stub has no retry logic.
4. **Hook configuration**: ❌ No `HooksConfig` struct, `hooks_for_event()`, `has_hooks()` in Python.
5. **HookContext**: ❌ No context object mapping tool/mode/session/error state to environment variables.
6. **Shell execution**: ❌ Rust runs arbitrary shell commands with timeouts, background flag, continue-on-error. Python has no execution logic.

**Parity: 25%**

---

## 4. App Server / Runtime API / Runtime Threads / Responses API Proxy

### Rust Surface (7,925 LOC)

#### `crates/app-server/src/lib.rs` (783 lines)
- **Stdio JSON-RPC server**: Equivalent to MCP stdio server but for app-level commands.
- **Configuration**: `AppServerOptions` with host, port, config path.
- **Lifecycle**: `run()` (HTTP) and `run_stdio()` (stdio JSON-RPC).

#### `crates/tui/src/runtime_api.rs` (2,729 lines)

**HTTP Routes (28 endpoints):**

| Route | Methods | Purpose |
|-------|---------|---------|
| `/health` | GET | Health check |
| `/v1/sessions` | GET | List sessions |
| `/v1/sessions/{id}` | GET, DELETE | Get/delete session |
| `/v1/sessions/{id}/...` | (multipart) | Session details |
| `/v1/workspace/status` | GET | Workspace status |
| `/v1/stream` | POST | SSE stream turn (backward compat) |
| `/v1/threads` | GET, POST | List/create threads |
| `/v1/threads/summary` | GET | Thread summaries |
| `/v1/threads/{id}` | GET, PATCH | Get/update thread |
| `/v1/threads/{id}/resume` | POST | Resume thread |
| `/v1/threads/{id}/fork` | POST | Fork thread |
| `/v1/threads/{id}/turns` | POST | Start new turn |
| `/v1/threads/{id}/turns/{turn_seq}` | GET, PATCH | Get/update turn |
| `/v1/threads/{id}/steer` | POST | Steer turn (Approve/Reject/Retry) |
| `/v1/threads/{id}/interrupt` | POST | Interrupt turn |
| `/v1/threads/{id}/compact` | POST | Compact thread |
| `/v1/threads/{id}/events` | GET | **SSE stream thread events** |
| `/v1/tasks` | GET, POST | List/create tasks |
| `/v1/tasks/{id}` | GET | Get task |
| `/v1/tasks/{id}/cancel` | POST | Cancel task |
| `/v1/skills` | GET | List skills |
| `/v1/apps/mcp/servers` | GET | List MCP servers |
| `/v1/apps/mcp/tools` | GET | List MCP tools |
| `/v1/apps/mcp/tools/introspect` | GET | Introspect MCP tools |
| `/v1/automations` | GET, POST | List/create automations |
| `/v1/automations/{id}` | GET, PATCH, DELETE | Get/update/delete automation |
| `/v1/automations/{id}/run` | POST | Run automation |
| `/v1/automations/{id}/pause` | POST | Pause automation |
| `/v1/automations/{id}/resume` | POST | Resume automation |
| `/v1/automations/{id}/runs` | GET | List automation runs |

**SSE Stream Types:**

1. **`stream_turn`** (POST `/v1/stream`) — backward compatible event stream:
   - `turn.started`
   - `message.delta` (LLM streaming response)
   - `tool.progress` (tool execution output)
   - `tool.completed` (tool result summary)
   - `approval.required` (when approval sink triggered)
   - `sandbox.denied` (execution policy rejection)
   - `turn.completed` (with usage stats)
   - `error`
   - `done`

2. **`stream_thread_events`** (GET `/v1/threads/{id}/events`) — thread-level event stream with `since` cursor.

#### `crates/tui/src/runtime_threads.rs` (4,413 lines)

**Core Data Structures:**

- **`ThreadRecord`** (~87 lines): Immutable thread snapshot
  - thread_id, created_at, model, sandbox_mode, cwd, workspace
  - turns (vector of TurnRecord)
  - event_history

- **`TurnRecord`** (~114 lines): Represents one full turn (request → response)
  - turn_seq, created_at, phase, approved_at
  - request_prompt, system_message
  - messages (conversation history)
  - items (turn item records)
  - status (RuntimeTurnStatus)

- **`RuntimeTurnStatus`** enum (lines 53–76):
  - Pending, Running, Suspended (awaiting approval), Approved, Rejected, Retried, Completed, Failed, Canceled

- **`TurnItemRecord`** (~139 lines): Individual items within a turn
  - item_seq, type (message, tool_call, tool_result, error)
  - created_at, completed_at
  - tool_name, arguments, result, error_message

- **`RuntimeEventRecord`** (~160 lines): Event log entry
  - timestamp, event_name, payload
  - Used for SSE broadcast and turn steering

- **`RuntimeThreadManager`** (~594 lines): Main state machine
  - Thread lifecycle: create, resume, fork, start_turn, steer_turn (Approve/Reject/Retry)
  - Turn steering enum (`SteerTurnRequest` with action Approve/Reject/Retry)

### Python Surface (252 LOC)

**Files:** `src/deepseek_tui/app_server/` (4 files)
- **server.py** (125 LOC): Stdio JSON-RPC server stub with basic dispatch (`exit`, `healthz`, `thread`, `app`, `prompt`, `tool`, `jobs`, `mcp/startup`).
- **routes.py** (55 LOC): HTTP route handlers (all stubs returning `not_implemented`).
- **sse.py** (31 LOC): SSE event formatting stub.
- **__init__.py** (41 LOC): Module init.

### Gaps (SEVERE)

1. **HTTP server implementation**: ❌ Rust runs full Axum server. Python: `raise NotImplementedError("HTTP server requires aiohttp dependency")` (server.py:27).
2. **All 28 HTTP routes**: ❌ Python has stubs returning `{"status": "not_implemented"}`. No actual route implementation.
3. **SSE streaming**: ❌ Rust implements full SSE with event types (turn.started, message.delta, tool.progress, etc.). Python sse.py is a stub with no streaming logic.
4. **Thread state machine**: ❌ Rust has full `RuntimeThreadManager` with thread creation, turn lifecycle (Pending → Running → Suspended → Approved/Rejected → Completed), fork/resume operations. Python has no equivalent.
5. **Turn steering**: ❌ Rust supports Approve/Reject/Retry actions via `SteerTurnRequest`. Python unimplemented.
6. **Event broadcast**: ❌ Rust maintains `RuntimeEventRecord` for all events. Python has no event system.
7. **Thread/turn/task persistence**: ❌ Rust stores all state in memory with snapshots. Python has no storage.
8. **Automation lifecycle**: ❌ Rust has full automation CRUD and run execution. Python stub.
9. **Workspace status**: ❌ Rust exposes workspace metadata. Python stub.
10. **MCP introspection**: ❌ Rust introspects MCP tools for the `/v1/apps/mcp/tools/introspect` endpoint. Python stub.

**Parity: 3%** (essentially no implementation beyond stubs)

---

## Phase D Action Items

### P0 (Blocking)

1. **Implement HTTP App Server** — replace Python stub with aiohttp/FastAPI server routing all 28 endpoints. Rust ref: `crates/tui/src/runtime_api.rs:295–341` (build_router). Effort: 3–5 days. Depends on RuntimeThreadManager.
2. **Implement RuntimeThreadManager State Machine** — Rust ref: `crates/tui/src/runtime_threads.rs:594–2571`. Translate thread creation, turn spawning, steering (Approve/Reject/Retry), fork/resume, event broadcasting. Effort: 5–7 days. Unblocks app server routes, SSE streaming, automation.
3. **Implement SSE Event Streaming** — Rust ref: `crates/tui/src/runtime_api.rs:987–1261`. Python SSE event generator with proper Content-Type, event framing, turn.started/message.delta/tool.progress/approval.required/turn.completed events. Effort: 2–3 days. Depends on RuntimeThreadManager.
4. **Implement Hooks Event System** — Rust ref: `crates/tui/src/hooks.rs:27–42` (all 7 HookEvent variants), `crates/hooks/src/lib.rs:54–169`. Add SessionStart/End, MessageSubmit, ToolCallBefore/After, ModeChange, OnError; webhook retries with exponential backoff. Effort: 3–4 days.

### P1 (Core Functionality)

5. **HTTP MCP Transport** — Rust ref: `crates/tui/src/mcp.rs:68–84`. URL-based MCP client with credential masking, error redaction, connection pooling. Effort: 2–3 days.
6. **Tool Qualification with Hash Truncation** — Rust ref: `crates/mcp/src/lib.rs:332–347`. Update Python `encoding.py` to hash truncate long qualified names. Effort: 1 day.
7. **MCP Stdio Server** — Rust ref: `crates/mcp/src/lib.rs:437–502`. Full async stdio server with all 13 methods. Effort: 4–5 days.
8. **LSP Hook Integration** — Rust ref: `crates/tui/src/core/engine/lsp_hooks.rs`. Trigger LSP diagnostics after tool-call-before/after, emit via hook sinks. Effort: 2–3 days.
9. **Automation CRUD & Execution** — Rust ref: `crates/tui/src/runtime_api.rs:330–341`. State machine, schedule/pause/resume, run execution. Effort: 3–4 days.

### P2 (Polish / Robustness)

10. **Hook Conditions & Shell Execution** — `HookCondition` enum + shell timeout/background/continue-on-error. Effort: 2 days.
11. **Webhook Retry with Exponential Backoff** — Rust ref: `crates/hooks/src/lib.rs:124–152`. Effort: 1 day.
12. **Resource Templates & Sandbox State Updates** — `update_sandbox_state`, resource templates. Effort: 1–2 days.
13. **MCP Startup Event Emission** — Rust ref: `crates/mcp/src/lib.rs:163–208`. Track server startup phases, emit events. Effort: 1 day.
14. **Comprehensive Error Handling & Logging** — structured logging, error recovery, timeouts. Effort: 2–3 days.
15. **Unit & Integration Tests** — parity tests for all routes, SSE streams, state machine transitions, hook conditions. Effort: 3–4 days.

---

## Summary

**Phase D Completion Status: 10% (1,432 / 13,892 LOC)**

### Critical Blockers
- **App Server HTTP**: 0% implemented (28 routes all stubs)
- **Runtime Thread Manager**: 0% implemented (no state machine, no turn steering)
- **SSE Streaming**: 0% implemented (no event generation)
- **Hooks Event System**: 25% (response lifecycle only; missing session/message/tool/mode/error events, conditions, shell execution)

### Suggested Sequencing
1. **Weeks 1–2:** Implement RuntimeThreadManager + HTTP server routes (unlocks all app-level functionality)
2. **Week 3:** Implement SSE streaming + automation CRUD
3. **Week 4:** Implement hooks event system + MCP stdio server
4. **Week 5:** Polish, testing, error handling

**Estimated total effort: 6–8 weeks** to reach feature parity with Rust.
