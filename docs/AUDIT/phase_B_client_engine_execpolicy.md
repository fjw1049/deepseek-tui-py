# Phase B Audit — Client / Engine / Execpolicy + Sandbox

**Audit Date:** 2026-05-06
**Coverage:** Rust→Python Rewrite Inventory
**Status:** Phase B (LLM client, engine/core, execpolicy+sandbox)

---

## Module summary table

| Module | Rust LOC | Python LOC | Parity % |
|--------|----------|-----------|----------|
| **LLM Client** | **6,353** | **531** | **8.4%** |
| **Engine / Core** | **20,512** | **189** | **0.9%** |
| **Execpolicy + Sandbox** | **5,803** | **256** | **4.4%** |
| **PHASE B TOTAL** | **32,668** | **976** | **3.0%** |

---

## 1. LLM client

### Rust Inventory (6,353 LOC)

- `crates/tui/src/client.rs` (~2,320 LOC): HTTP orchestrator, tool name codec (`to_api_tool_name` / `from_api_tool_name`, lines 25–86, bare hex escape decoder), SSE backpressure watermark (8 events), buffer pool, health check probe.
- `crates/tui/src/client/chat.rs` (1,543 LOC): Chat completions builder, SSE parser, stream idle timeout (300s configurable via `DEEPSEEK_STREAM_IDLE_TIMEOUT_SECS`), tool choice mapping.
- `crates/tui/src/llm_client/mod.rs` (1,079 LOC): `LlmClient` trait, `LlmError` enum (`RateLimited` with `retry_after: Option<Duration>`, `ServerError`, `AuthError`, `InvalidRequest`, `NetworkError`, `StreamClosed`, `Timeout`), `RetryConfig` (exponential backoff with jitter), `extract_retry_after()` parser, `with_retry()` combinator.
- `crates/tui/src/llm_client/mock.rs` (627 LOC): `MockLlmClient` for integration tests.
- `crates/tui/src/pricing.rs` (177 LOC): V4-pro discount ($0.55/M input = 25% discount), cache-hit accounting (`cache_read_input_tokens`).
- `crates/tui/src/retry_status.rs` (201 LOC): Retry-After parsing (delta-seconds or HTTP-date), exponential backoff calculation.
- `crates/tui/src/client/responses.rs` (406 LOC): Responses API path.

### Python Inventory (531 LOC)

- `client/base.py` (63 LOC): `LLMClient` ABC, `stream_with_retry()` (transparent retries before content max 2, error retries after content max 5).
- `client/deepseek.py` (86 LOC): `DeepSeekClient`, `stream_chat_completion()`, `_build_payload()` (model, messages, stream, tools, tool_choice, max_tokens, temperature, top_p, reasoning_effort, extra_body, stream_options).
- `client/streaming.py` (130 LOC): `OpenAIStreamParser` (tool call fragmentation via `_ToolCallBuilder`, `finish_reason`: "tool_calls" → `StreamToolCallComplete`, "stop" → `StreamDone`).
- `client/retry.py` (18 LOC): `RetryConfig` (max_transparent_retries=2, max_error_retries=5, base_delay=0.2, max_delay=10.0).
- `client/pricing.py` (44 LOC): `ModelPricing`, `PricingTable` (deepseek-chat, deepseek-reasoner only).
- `client/chat_messages.py` (153 LOC): `build_chat_messages()`.
- `client/openai_compat.py` (37 LOC): OpenAI compatibility wrapper.

### Gaps in Client

| Gap | Rust LOC | Severity |
|-----|----------|----------|
| Tool name codec (`to`/`from_api_tool_name`, bare hex escape) | 62 | **P0** |
| SSE backpressure watermark (8 events) + buffer pool | 40 | **P1** |
| Health check probe | 30 | **P1** |
| `Retry-After` header parsing (delta-seconds + HTTP-date) | 50 | **P1** |
| Connection pool reuse | 100+ | **P1** |
| V4-pro discount + cache-hit accounting | 50 | **P1** |
| Stream idle timeout (`DEEPSEEK_STREAM_IDLE_TIMEOUT_SECS`, 300s) | 15 | **P2** |
| `LlmError` granular categorization | 100+ | **P2** |
| Mock harness for integration tests | 627 | **P2** |
| Responses API path (`client/responses.rs`) | 406 | **P2** |

---

## 2. Engine / Core

### Rust Inventory (20,512 LOC)

**Core modules:**
- `crates/tui/src/core/engine.rs` (1,797 LOC): Event loop, op channel, session history, turn cycle manager.
- `crates/tui/src/core/capacity.rs` (784 LOC): Token / step / cost / subagent budgets, risk bands, `GuardrailAction`.
- `crates/tui/src/core/capacity_memory.rs` (323 LOC): Canonical state persistence, replay info.
- `crates/tui/src/core/coherence.rs` (149 LOC): State machine (Intro→Depth→Consolidation).
- `crates/tui/src/core/events.rs` (278 LOC): `TurnOutcomeStatus` events.
- `crates/tui/src/core/ops.rs` (113 LOC): `SendMessageOp`, `CancelRequestOp`.
- `crates/tui/src/core/session.rs` (151 LOC): Session holder.
- `crates/tui/src/core/tool_parser.rs` (510 LOC): Tool call JSON parsing.
- `crates/tui/src/core/turn.rs` (197 LOC): Turn context, snapshots.

**Engine submodules:**
- `crates/tui/src/core/engine/turn_loop.rs` (1,597 LOC): Main event loop (streaming consumption, tool polling, approval gate, capacity checkpoints).
- `crates/tui/src/core/engine/capacity_flow.rs` (975 LOC): Checkpoint implementations (pre-request, post-tool, error escalation).
- `crates/tui/src/core/engine/context.rs` (382 LOC): Token accounting, context window lookup.
- `crates/tui/src/core/engine/dispatch.rs` (354 LOC): Tool routing.
- `crates/tui/src/core/engine/tool_catalog.rs` (475 LOC): Tool registry catalogue.
- `crates/tui/src/core/engine/tool_execution.rs` (298 LOC): Execution gate.
- `crates/tui/src/core/engine/tool_setup.rs` (60 LOC): Tool init.
- `crates/tui/src/core/engine/streaming.rs` (137 LOC): SSE helpers.
- `crates/tui/src/core/engine/approval.rs` (127 LOC): Approval gate with session cache.
- `crates/tui/src/core/engine/lsp_hooks.rs` (128 LOC): LSP telemetry.
- `crates/tui/src/core/engine/tests.rs` (1,477 LOC): Integration harness.

**Long-conversation managers (in `crates/tui/src/`):**
- `compaction.rs` (~2,008 LOC): Message summarization, working set dedup (24 max paths), cache-breakpoint headers, config (`token_threshold=50k`, `message_threshold=50`).
- `cycle_manager.rs` (~1,071 LOC): Cycle boundaries, briefing generation, archival.
- `seam_manager.rs` (~700 LOC): Context backtrack recovery from divergence.
- `working_set.rs` (~1,198 LOC): Active context dedup (12-op window, 24 max paths).
- `session_manager.rs` (~1,339 LOC): Multi-session persistence, state recovery.
- `runtime_threads.rs` (~4,413 LOC): Background task coordination, cancellation tokens.
- `runtime_api.rs` (~2,729 LOC): Runtime state API.

### Python Inventory (189 LOC of "real" engine, 543 LOC total)

- `engine/engine.py`: `Engine` class (handle, client, model, tool_registry, exec_policy, max_tool_round_trips=3).
- `engine/turn_loop.py`: `TurnLoop.run()` consuming stream events, emitting `TextDeltaEvent` / `ThinkingDeltaEvent` / `ToolCallEvent` / `ErrorEvent`.
- `engine/streaming.py`: `AssistantResponseBuffer` collects text/thinking/tool_calls.
- `engine/approval.py`: `ApprovalHandler` ABC.
- `engine/events.py`: Event types.
- `engine/handle.py`: `EngineHandle`.
- `engine/ops.py`: Op stubs.
- `engine/prompts.py`: `build_system_prompt()` stub.

### Gaps in Engine / Core

| Gap | Rust LOC | Severity |
|-----|----------|----------|
| Capacity guardrails (token / step / cost / subagent budgets, risk bands) | 784 | **P0** |
| Capacity flow checkpoints (pre-request, post-tool, error escalation) | 975 | **P0** |
| Turn loop streaming loop (full implementation) | 1,597 | **P0** |
| Context window management & token accounting | 382 | **P0** |
| Tool dispatch & execution gates | 652 | **P0** |
| Compaction (summarization + dedup) | 2,008 | **P0** |
| Session persistence (multi-session, state recovery) | 1,339 | **P0** |
| Tool catalog | 475 | **P0** |
| Tool parser (tool call JSON parsing) | 510 | **P0** |
| Cycle manager (boundary, briefing, archive) | 1,071 | **P1** |
| Working set dedup (12-op window, 24 max paths) | 1,198 | **P1** |
| Seam manager (backtrack recovery) | 700 | **P1** |
| Runtime threads (background coordination, cancel tokens) | 4,413 | **P1** |
| Runtime API surface | 2,729 | **P1** |
| Capacity memory (canonical state persistence) | 323 | **P2** |
| Coherence state machine | 149 | **P2** |
| LSP hooks integration | 128 | **P2** |
| Approval gate with session cache | 127 | **P2** |
| Engine integration test harness | 1,477 | **P2** |

---

## 3. Execpolicy + Sandbox + Command Safety + Network Policy + Workspace Trust

### Rust Inventory (5,803 LOC)

**Execpolicy:**
- `crates/tui/src/execpolicy/amend.rs` (225 LOC): Policy amendment, `blocking_append_allow_prefix_rule()`.
- `crates/tui/src/execpolicy/matcher.rs` (198 LOC): Glob/regex/exact rule matching.
- `crates/tui/src/execpolicy/parser.rs` (269 LOC): TOML/HCL policy parsing.
- `crates/tui/src/execpolicy/policy.rs` (145 LOC): Policy evaluation logic.
- `crates/tui/src/execpolicy/rule.rs` (160 LOC): Rule definition.
- `crates/tui/src/execpolicy/rules.rs` (123 LOC): Standard rules, `load_default_policy()`.
- `crates/tui/src/execpolicy/decision.rs` (27 LOC): `Decision` enum.
- `crates/tui/src/execpolicy/error.rs` (28 LOC): Error types.
- `crates/tui/src/execpolicy/execpolicycheck.rs` (83 LOC): Entry point.
- `crates/execpolicy/src/lib.rs` (191 LOC): Standalone library.

**Sandbox:**
- `crates/tui/src/sandbox/mod.rs` (644 LOC): `CommandSpec` orchestrator.
- `crates/tui/src/sandbox/policy.rs` (322 LOC): Read/write/exec allowlists.
- `crates/tui/src/sandbox/seatbelt.rs` (398 LOC): macOS Seatbelt XML profile generation.
- `crates/tui/src/sandbox/landlock.rs` (344 LOC): Linux Landlock FD setup (kernel 5.13+).
- `crates/tui/src/sandbox/windows.rs` (79 LOC): Windows AppContainer stub.

**Command Safety + Network Policy + Workspace Trust:**
- `crates/tui/src/command_safety.rs` (~1,200 LOC): Command arity dict (~163 commands: git, npm, pip, cargo, docker, terraform, aws-cli, kubectl), `classify_command()`, dangerous pattern detection (`rm -rf`, `dd`, `format`).
- `crates/tui/src/network_policy.rs` (~701 LOC): `Decision` enum (Allow/Deny/Prompt; deny wins), host matching (exact / subdomain), `NetworkAuditor` (RFC3339 audit log), `NetworkSessionCache`.
- `crates/tui/src/workspace_trust.rs` (~286 LOC): Per-workspace trust persistence (`~/.deepseek/workspace-trust.json`), canonical path matching.

### Python Inventory (256 LOC)

- `execpolicy/engine.py` (107 LOC): `ExecPolicyEngine` (`evaluate()`, `record_decision()`, policy modes: "auto"/"never-ask"/"on-request"/"never", risk levels: LOW/MEDIUM/HIGH).
- `execpolicy/models.py` (41 LOC): `PolicyRule`, `ApprovalRequest`, `ApprovalDecision`, `ToolCategory`, `RiskLevel`.
- `execpolicy/sandbox.py` (56 LOC): `SandboxPolicy` stub (no real platform isolation).

### Gaps in Execpolicy / Sandbox

| Gap | Rust LOC | Severity |
|-----|----------|----------|
| Rule parser (TOML, glob, regex) | 269 | **P0** |
| Matcher | 198 | **P0** |
| Policy evaluation logic | 145 | **P0** |
| Standard rules / defaults | 123 | **P0** |
| Command arity dict + dangerous patterns (`rm -rf`, `dd`, `format`) | 1,200 | **P0** |
| Seatbelt (macOS XML profile) | 398 | **P0** |
| Landlock (Linux FD setup, kernel 5.13+) | 344 | **P0** |
| `CommandSpec` orchestrator | 644 | **P0** |
| Sandbox policy (read/write/exec allowlists) | 322 | **P0** |
| Standalone execpolicy library | 191 | **P0** |
| Policy amendment (`blocking_append_allow_prefix_rule`) | 225 | **P1** |
| Network policy + audit log + session cache | 701 | **P1** |
| Workspace trust persistence | 286 | **P1** |
| Windows AppContainer | 79 | **P2** |
| Decision enum granularity | 27 | **P2** |
| Error types granularity | 28 | **P2** |

---

## Phase B Action Items

### P0 (Critical — Block release)
1. LLM tool name codec (`to_api_tool_name` / `from_api_tool_name`, ~62 LOC) — without this DeepSeek tool calls fail on non-ASCII names.
2. Engine capacity guardrails (~784 LOC) — token / step / cost / subagent budgets.
3. Engine turn loop full implementation (~1,597 LOC) — current ~83-line `turn_loop.py` cannot drive multi-turn tool work.
4. Capacity flow checkpoints (~975 LOC).
5. Compaction (~2,008 LOC) — long conversations OOM without it.
6. Session persistence (~1,339 LOC).
7. Tool parser (~510 LOC) and tool catalog (~475 LOC).
8. Execpolicy rule parser, matcher, policy evaluation (~735 LOC).
9. Command safety arity dict + dangerous pattern detection (~1,200 LOC).
10. Sandbox platforms: macOS Seatbelt + Linux Landlock (~821 LOC) + `CommandSpec` orchestrator (~644 LOC) + sandbox policy (~322 LOC).

### P1 (High)
- `Retry-After` parsing (~50 LOC), SSE backpressure watermark (~40 LOC), connection pool reuse (~100 LOC), V4-pro discount + cache accounting (~50 LOC), context window management (~382 LOC), tool dispatch + execution (~652 LOC), cycle manager (~1,071 LOC), working set dedup (~1,198 LOC), seam manager (~700 LOC), runtime threads (~4,413 LOC), runtime API (~2,729 LOC), policy amendment (~225 LOC), network policy + auditor (~701 LOC), workspace trust (~286 LOC).

### P2 (Medium)
- Health check probe (~30 LOC), connection pool details (~100+ LOC), stream idle timeout configurability (~15 LOC), `LlmError` categorization (~100+ LOC), mock client harness (~627 LOC), Responses API path (~406 LOC), capacity memory (~323 LOC), coherence (~149 LOC), LSP hook integration (~128 LOC), approval session cache (~127 LOC), engine integration test harness (~1,477 LOC), Windows AppContainer (~79 LOC), policy decision/error enum granularity (~55 LOC).

---

## Summary Statistics

- **Rust Phase B:** 32,668 LOC (Client 19%, Engine 63%, Execpolicy+Sandbox 18%).
- **Python Phase B:** 976 LOC → **3.0% parity**.
- **P0 Gaps:** 10 modules, ~10,200 LOC to implement for "百分百复刻".
- **P1 Gaps:** 14 modules, ~13,000 LOC to implement.
- **P2 Gaps:** 13 modules, ~3,800 LOC to implement.
- **Total gap to close:** ~27,000 LOC of net new Python implementation just to reach Phase B parity.
