# Capability Module Refactor Remaining Work

Last updated: 2026-06-11

This document is the handoff checklist for continuing the capability-module
refactor after the current large working tree. It is written against
`docs/CAPABILITY_MODULE_REFACTOR_PLAN.md` and the current implementation tracked
in `docs/CAPABILITY_MODULE_REFACTOR_PROGRESS.md`.

## Current Status

The capability-module refactor is **complete** for all planned phases (Priorities
1–11). Remaining items below are explicitly deferred separate projects, not
blockers for this refactor.

What is already in place:

- Public construction entry points now pass through `host.assembler`:
  `Engine.create(...)`, `create_tool_runtime(...)`, `build_default_registry(...)`.
- `ToolContext.services` and `ServiceRegistry` exist.
- `host` now has foundational contracts:
  - `services.py`
  - `module.py`
  - `catalog.py`
  - `assembler.py`
  - `toolpacks.py`
  - `prompts.py`
  - `lifecycle.py`
  - `surfaces.py`
  - `contributions.py`
- First-party capability adapters exist under `src/deepseek_tui/capabilities/`.
- Tool registration is mostly moved behind ToolPacks.
- Prompt generation is moved behind ordered prompt contributors.
- Many runtime managers and helper glue have moved out of `Engine`,
  `ToolRuntime`, `builder.py`, route files, and tool files.
- The assembler can collect enabled built-in module `Contributions` without
  changing runtime materialization.
- Memory before-turn recall and PostTurn/Evolution main-tool notification now
  dispatch through `Engine.lifecycle_registry` under the existing legacy Engine
  path.

Latest verification before this handoff:

```bash
PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/workflow tests/engine/test_turn_evidence_sync.py tests/test_rlm_subagent_task_parity.py tests/test_rlm_subagent_task_integration.py tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/contract/test_goal_status_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py tests/test_mcp_engine_integration.py tests/test_mcp_preload.py -q
# 385 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with ruff --index-url https://pypi.tuna.tsinghua.edu.cn/simple ruff check src/deepseek_tui/capabilities src/deepseek_tui/host src/deepseek_tui/engine/engine.py src/deepseek_tui/engine/prompts.py src/deepseek_tui/app_server/thread_manager.py src/deepseek_tui/app_server/routes.py src/deepseek_tui/app_server/runtime_api/routes/mcp.py src/deepseek_tui/app_server/runtime_api/routes/evolution.py src/deepseek_tui/tools/workflow_tool.py src/deepseek_tui/tools/rlm/tool.py src/deepseek_tui/tools/memory_curate_tool.py src/deepseek_tui/tools/skill_manage_tool.py tests/host tests/workflow tests/evolution/test_main_tool_evidence.py tests/engine/test_turn_evidence_sync.py tests/test_rlm_subagent_task_parity.py tests/test_rlm_subagent_task_integration.py tests/test_mcp_preload.py
# All checks passed
```

Known verification caveats:

- Use `--index-url https://pypi.tuna.tsinghua.edu.cn/simple` for temporary
  `uv run --with ...` installs.
- `PyYAML` is still not declared in `pyproject.toml`; tests currently use
  `--with pyyaml`.
- Some existing files have pre-existing ruff issues, especially
  `src/deepseek_tui/tools/knowledge_tools.py` and some contract/integration
  test files. Keep scoped ruff checks focused unless deliberately fixing those
  separately.

## Definition Of Done (met)

- `assemble_engine()`, `assemble_tool_runtime()`, and `assemble_registry_only()`
  materialize from `AssembledContributions` via the default builtin catalog.
- The assembler collects concrete capability contributions through
  `Contributions` and `collect_builtin_contributions()`.
- Dynamic lifecycle observers register once through
  `host/engine_lifecycle.register_engine_lifecycle_observers()` during
  `attach_engine_capabilities()`; catalog lifecycle merges via
  `merge_lifecycle_registries()`.
- Runtime API surfaces mount through `mount_surface_routes()` from catalog
  contributions.
- `Engine.__init__` is a shell; goal, hooks, memory, cycle, evolution,
  post-turn, and subagent wiring run through `attach_engine_capabilities()` and
  per-capability `attach_engine_*()` helpers.
- Long-lived services use `ToolContext.services`; per-tool workflow/RLM bindings
  use `ToolContext.tool_execution`.
- `ToolRuntime.shutdown()` is documented as the host shutdown coordinator.

## Priority 1: Wire Contributions Into The Assembler

Status: completed for the safe collection step. The assembler now has
`collect_builtin_contributions(...)` and tests for no-op collection, dependency
order, duplicate ToolPack rejection, duplicate prompt contributor rejection, and
duplicate route rejection. Runtime materialization still intentionally delegates
to legacy bodies.

Why this matters:

`host/contributions.py`, `host/lifecycle.py`, and `host/surfaces.py` now exist,
and the assembler can collect module contributions. The next contribution step
is to start registering real first-party modules in the built-in catalog without
changing runtime behavior.

Target:

Make the host assembler own a single lifecycle/surface/contribution collection
for each assembled runtime while preserving legacy public APIs.

Suggested files:

- `src/deepseek_tui/host/assembler.py`
- `src/deepseek_tui/host/contributions.py`
- `src/deepseek_tui/host/catalog.py`
- `src/deepseek_tui/host/module.py`
- `src/deepseek_tui/engine/engine.py`
- `tests/host/test_contributions.py`
- `tests/host/test_registry_assembly.py`

Implementation steps:

1. Add an assembled container type in `host/assembler.py`, for example
   `AssembledContributions`, containing:
   - `services`
   - `lifecycle`
   - `surfaces`
   - `tool_packs`
   - `prompt_contributors`
   - `post_turn_pipelines`
2. Add a helper such as `collect_builtin_contributions(config)` that:
   - gets modules from `BuiltinModuleCatalog`
   - creates `Contributions`
   - calls `module.contribute(contributions)` in resolved order
   - returns the populated container
3. Keep `EMPTY_BUILTIN_CATALOG` behavior unchanged at first.
4. Add tests for:
   - duplicate tool pack contribution rejection
   - duplicate prompt contributor rejection
   - lifecycle ordering
   - surface route conflict rejection
   - empty catalog no-op assembly
5. Do not yet switch all runtime construction to this path. First prove the
   collection mechanism works without changing behavior.

Acceptance:

- Existing comprehensive regression still passes.
- New tests prove contribution collection order and conflict behavior.
- No user-visible route/tool/prompt/event changes.

Risk:

- Import cycles. Keep type-only imports guarded by `TYPE_CHECKING`.

## Priority 2: Replace Local Lifecycle Registries With Engine-Owned Registry

Status: completed. `Engine` now owns `lifecycle_registry`; Memory before-turn
and PostTurn after-tool observers are registered once with provider-backed
observers and dispatched through that registry.

Why this matters:

Memory and PostTurn now use `LifecycleRegistry` through an Engine-owned registry
instead of local per-call registries. Keep this section as historical context
for the next lifecycle observer migrations.

Target:

`Engine` should hold one lifecycle registry for the engine/session, populated
during `Engine._materialize()` or by the assembler compatibility adapter.

Suggested files:

- `src/deepseek_tui/engine/engine.py`
- `src/deepseek_tui/capabilities/memory.py`
- `src/deepseek_tui/capabilities/post_turn.py`
- `src/deepseek_tui/host/lifecycle.py`
- `tests/host/test_engine_wiring_capabilities.py`
- `tests/host/test_memory_capability.py`

Implementation steps:

1. Add `self.lifecycle = LifecycleRegistry()` in `Engine.__init__()` or a
   capability attachment helper.
2. Register Memory before-turn observer once after memory runtime is attached:
   - owner: `memory`
   - id: `memory.before_turn`
   - order: choose stable value, currently `100`
3. Register PostTurn after-tool observer once after `self.post_turn` is assigned:
   - owner: `post_turn`
   - id: `post_turn.after_tool`
   - order: choose stable value, currently `100`
4. In `_run_turn()`, replace local Memory registry construction with:
   - create `BeforeUserTurnContext`
   - `await self.lifecycle.before_user_turn(context)`
   - read `MEMORY_TURN_CONTEXT_DECORATION`
5. In `_notify_after_tool_lifecycle()`, replace local registry construction
   with:
   - `await self.lifecycle.after_tool(context)`
6. Make registration idempotent or ensure registration happens once per Engine.

Acceptance:

- Memory before-turn behavior unchanged.
- PostTurn/Evolution `memory_curate` / `skill_manage` scheduler reset unchanged.
- Add test proving `Engine.lifecycle.registrations()` contains expected IDs
  when memory/evolution/post_turn are enabled.

Risk:

- `self.post_turn` may be assigned after `Engine.__init__()`, so registering
  PostTurn observer too early can capture `None`. Prefer registering after
  post-turn assembly or use an observer that reads a callable/provider.

## Priority 3: Goal Lifecycle Observer

Status: completed. Goal turn start, complete, and failure accounting now
dispatch through `Engine.lifecycle_registry` using `GoalLifecycleObserver`.
Follow-up and steer results are carried back through lifecycle context
decorations so Engine keeps the existing dispatch behavior.

Why this matters:

Plan Phase 8 requires Goal lifecycle observer ownership. Current state:

- Goal helper functions live in `capabilities/goal.py`.
- `Engine` still directly calls:
  - `start_goal_turn(...)`
  - `fail_goal_turn(...)`
  - `finish_goal_turn(...)`
  - `should_dispatch_goal_follow_up(...)`
- `RuntimeThreadManager` still reaches `getattr(state.engine, "goal_controller")`.

Target:

Move Goal start/complete/failure accounting through lifecycle observers while
preserving current hidden follow-up behavior and SSE payloads.

Suggested files:

- `src/deepseek_tui/capabilities/goal.py`
- `src/deepseek_tui/engine/engine.py`
- `src/deepseek_tui/app_server/thread_manager.py`
- `tests/host/test_goal_capability.py`
- `tests/goal/test_goal_engine.py`
- `tests/goal/test_goal_thread_manager.py`
- `tests/contract/test_goal_status_sse.py`

Implementation steps:

1. Add `GoalLifecycleObserver` to `capabilities/goal.py`.
2. Observer methods:
   - `before_user_turn`: call `controller.on_turn_start()`
   - `on_turn_failed`: call `controller.on_turn_failed(reason, usage)`
   - `on_turn_completed`: call `controller.on_turn_complete(usage)` and store
     follow-up/steer result in lifecycle context decorations.
3. Extend lifecycle contexts if needed with `decorations`, similar to
   `BeforeUserTurnContext`.
4. Register observer once in Engine lifecycle registry.
5. Replace direct `start_goal_turn`, `fail_goal_turn`, `finish_goal_turn` calls
   in `Engine` with lifecycle dispatch.
6. Keep `should_dispatch_goal_follow_up(...)` and
   `build_goal_follow_up_start_payload(...)` response behavior unchanged.
7. Do not change `goal.status` SSE payload.

Acceptance:

- `tests/goal` pass.
- `tests/contract/test_goal_status_sse.py` passes.
- Existing comprehensive regression passes.
- Hidden follow-up persistence and stale rejection unchanged.

Risk:

- Cancellation and failed-turn paths currently return early. Make sure lifecycle
  failure observer runs in exactly the same places direct `fail_goal_turn(...)`
  ran before.

## Priority 4: RuntimeThreadManager Goal Service Adapter

Status: completed. `RuntimeThreadManager` now uses
`goal_controller_from_engine(...)`, which prefers `ToolContext.services` and
falls back to legacy named/metadata bindings. No direct
`getattr(engine, "goal_controller")` remains in `thread_manager.py`; TUI command,
TUI session-binding, and runtime SSE callers also use the same adapter.

Why this matters:

Plan Phase 8 completion criteria says:

`RuntimeThreadManager` does not use `getattr(engine, "goal_controller")`.

Current state:

`RuntimeThreadManager` still uses `getattr(state.engine, "goal_controller", None)`
for:

- stale hidden follow-up validation
- `goal.status` payload emission
- pending follow-up scheduling

Target:

Add a narrow adapter in `capabilities/goal.py` so RuntimeThreadManager does not
know about the concrete Engine attribute.

Suggested files:

- `src/deepseek_tui/capabilities/goal.py`
- `src/deepseek_tui/app_server/thread_manager.py`
- `tests/host/test_goal_capability.py`
- `tests/goal/test_goal_thread_manager.py`

Implementation steps:

1. Add helper:
   - `goal_controller_from_engine_state(state: object) -> GoalController | None`
   or better:
   - `goal_controller_from_services(services: ServiceRegistry)`.
2. In RuntimeThreadManager, prefer:
   - `state.engine.tool_context.services.optional(GoalController)`
   - named legacy service fallback if needed.
3. Replace `getattr(state.engine, "goal_controller", None)` call sites.
4. Keep error strings unchanged, especially `"goal follow-up is stale"`.

Acceptance:

- No `getattr(..., "goal_controller")` remains in `thread_manager.py`.
- Goal thread manager tests pass.
- Contract SSE test passes.

Risk:

- Some tests may instantiate fake engine state without `tool_context.services`.
  Preserve graceful fallback or update tests deliberately.

## Priority 5: LSP Tool Observer

Status: completed for post-edit tool observation. Successful edit-tool
diagnostics now run through `LspToolObserver` registered on
`Engine.lifecycle_registry`. Pending diagnostic rendering remains in Engine so
next-request injection timing stays unchanged.

Why this matters:

Plan Phase 6 still has LSP observer work mostly unfinished. Current state:

- LSP manager construction moved to `capabilities/lsp.py`.
- Engine/tool execution still owns post-edit LSP hook and pending diagnostics.

Target:

Move post-edit LSP invocation to a `LspToolObserver` and pending diagnostic
injection to a narrow before-request/before-turn decorator.

Suggested files:

- `src/deepseek_tui/capabilities/lsp.py`
- `src/deepseek_tui/engine/engine.py`
- `src/deepseek_tui/lsp/hooks.py`
- `tests/host/test_lsp_capability.py`
- LSP-related existing tests found by searching `diagnostics_for`,
  `edited_paths_for_tool`, `_run_post_edit_lsp_hook`.

Implementation steps:

1. Add `LspToolObserver` in `capabilities/lsp.py`.
2. Move current `_run_post_edit_lsp_hook` decision logic behind that observer,
   not the LSP implementation itself.
3. Register it in lifecycle after-tool ordering after tool result success.
4. Preserve silent failure behavior.
5. Do not change diagnostic rendering or order.

Acceptance:

- Editing tools still produce same next-request diagnostic context.
- LSP failures remain silent.
- No direct LSP implementation import remains in Engine except compatibility
  wrappers if needed.

Risk:

- LSP observer must run only for successful relevant edit tools, matching the
  current `if result.success` guard.

## Priority 6: Memory Capture/Flush Trigger Timing

Status: characterization tests added for capture/flush dispatch. Engine still
owns trigger timing; lifecycle migration is not started yet.

Why this matters:

Memory before-turn recall is now lifecycle-backed, but capture/flush trigger
timing is still Engine-owned.

Target:

Do not force this too early. First create characterization tests for:

- normal post-turn capture
- PostTurn disabled direct capture fallback
- compaction `flush_before_loss`
- LRU eviction/session shutdown flush if present

Suggested files:

- `src/deepseek_tui/capabilities/memory.py`
- `src/deepseek_tui/capabilities/post_turn.py`
- `src/deepseek_tui/engine/engine.py`
- `tests/memory`
- `tests/post_turn`
- `tests/app_server/test_lru_flush.py`

Implementation steps:

1. Add or strengthen tests for flush trigger points.
2. Only then consider a lifecycle completion observer or post-turn host contract
   change.
3. Keep `MemoryPipeline` as capture/flush owner.
4. Do not remove direct fallback capture until PostTurn disabled behavior is
   proven equivalent.

Acceptance:

- `tests/memory`, `tests/post_turn`, and LRU flush tests pass.
- No duplicate capture on a successful normal turn.

Completed characterization coverage:

- `tests/host/test_memory_capture_flush_characterization.py`
  - orchestrator path skips direct `capture_memory_after_turn`
  - PostTurn-disabled fallback captures once
  - MemoryPipeline capture once via orchestrator
  - compaction-style `flush_before_loss` passes `flush_mode=True` evidence
  - LRU `_flush_engine_memory` coordinator fallback without post_turn or session
    messages

Risk:

- Duplicate memory capture is easy to introduce. Add explicit assertions.

## Priority 7: Evolution Review Scheduling And Ledger Events

Status: characterization tests added and approval route response helper moved to
`capabilities/evolution.py`. Pipeline/ledger internals unchanged.

Why this matters:

Evolution construction, evidence publication, main-tool response shaping, and
main-tool scheduler reset dispatch moved. Remaining behavior is deeper:

- review scheduling
- ledger mutation behavior
- event emission
- approval flow surface

Target:

Preserve existing behavior. Do not introduce generic extension events yet.

Suggested files:

- `src/deepseek_tui/capabilities/evolution.py`
- `src/deepseek_tui/evolution/pipeline.py`
- `src/deepseek_tui/evolution/ledger.py`
- `src/deepseek_tui/app_server/runtime_api/routes/evolution.py`
- `tests/evolution`
- `tests/contract` if proposal event shape is covered there

Implementation steps:

1. Add explicit characterization tests around:
   - `EvolutionPipeline.after_turn`
   - scheduler due/reset behavior
   - proposal event payload
   - approval/reject route response shapes
2. Move only route/presenter glue into capability surface helpers.
3. Keep `EvolutionPipeline` and `ExperienceLedger` internals in their domain
   package unless there is a clear adapter boundary.
4. Do not change ledger/audit formats.

Acceptance:

- `tests/evolution` pass.
- Evolution approval routes preserve status codes and payloads.
- Workbench proposal event shape unchanged.

Completed characterization coverage:

- `tests/host/test_evolution_scheduling_characterization.py`
  - main-tool scheduler reset (`memory_curate`, `skill_manage`)
  - `after_turn` review scheduling + scheduler reset when due
  - gate failure skips review scheduling
  - proposed mutation emits `EvolutionProposalEvent`
- `tests/app_server/test_evolution_routes.py`
  - list/approve/reject response shapes and error codes
- `evolution_action_response()` route presenter helper

Risk:

- Event and ledger changes are user-visible. Avoid broad rewrites here.

## Priority 8: Workflow/RLM Typed Execution Context

Status: completed for typed `ToolContext.tool_execution` bindings with legacy
metadata fallback. Engine still uses existing `workflow_tool_bindings()` /
`rlm_tool_bindings()` entry points.

Why this matters:

Workflow and RLM execution bodies moved to capability adapters, but they still
use metadata-based callback bindings:

- `workflow_*`
- `rlm_progress_cb`

Target:

Replace these with a typed short-lived tool execution context, not long-lived
services.

Suggested files:

- `src/deepseek_tui/host/lifecycle.py` or a new `host/tool_execution.py`
- `src/deepseek_tui/capabilities/workflow.py`
- `src/deepseek_tui/capabilities/rlm.py`
- `src/deepseek_tui/engine/engine.py`
- `tests/workflow`
- `tests/host/test_rlm_capability.py`

Implementation steps:

1. Define a turn/tool scoped context object for callbacks:
   - cancel event
   - emit status/progress
   - tool call id
   - parent runtime references if needed
2. Bind it in Engine for the duration of tool execution.
3. Keep metadata fallback until all call sites migrate.
4. Add tests proving cleanup after tool execution.

Acceptance:

- Workflow progress/cancel tests pass.
- RLM progress tests pass.
- No metadata leak after tool execution.

Completed:

- `host/tool_execution.py` with `ToolExecutionContext`, resolve helpers, and
  legacy metadata key constants
- `ToolContext.tool_execution` field
- `capabilities/workflow.py` and `capabilities/rlm.py` bind typed context and
  keep metadata fallback
- `tests/host/test_tool_execution_context.py`

Risk:

- These are dynamic per-call bindings. Do not promote them to `ServiceRegistry`
  process/engine services.

## Priority 9: Runtime Surface Registry Integration

Status: completed — capability route descriptors register through the builtin
catalog and `build_runtime_api_router()` mounts them via `mount_surface_routes()`.

Why this matters:

`host/surfaces.py` exists but app-server routes are still statically included.
The plan says route inclusion should move behind enabled surface contributions
only after contract parity is proven.

Target:

Do not remove static routes immediately. First register equivalent route
contributions in capabilities and test conflicts/order.

Suggested files:

- `src/deepseek_tui/host/surfaces.py`
- `src/deepseek_tui/capabilities/mcp.py`
- `src/deepseek_tui/capabilities/evolution.py`
- `src/deepseek_tui/capabilities/automation.py`
- `src/deepseek_tui/app_server/server.py`
- `src/deepseek_tui/app_server/runtime_api/routes/*.py`
- `tests/host/test_lifecycle_and_surfaces.py`
- route contract tests

Implementation steps:

1. Add capability functions that contribute route descriptors but do not yet
   replace static routes.
2. Add tests proving contributed paths match current static paths.
3. Add a host route mounting helper behind a test-only path or isolated router.
4. Only after contract tests pass should static route inclusion become
   capability-driven.

Acceptance:

- Current `/v1` routes unchanged.
- Surface registry tests cover duplicate route conflict.
- Route payload contract tests pass.

Completed:

- `contribute_runtime_surfaces()` in `capabilities/mcp.py`, `evolution.py`,
  `automation.py`
- `capabilities/runtime_surfaces.py::register_builtin_runtime_surfaces()`
- `collect_builtin_contributions()` now registers builtin runtime surfaces
- `host/surfaces.py::{mount_surface_routes, build_surface_router}`
- `tests/host/test_runtime_surface_contributions.py`

Risk:

- Changing route inclusion too early can break Workbench. Keep route shape
  static until parity is proven.

## Priority 10: MCP Manager Internals

Status: completed for host-integration audit and glue consolidation. Protocol
implementation remains in `mcp/manager.py`; `mcp_startup` hook emission in
`app_server/runtime.py` is intentionally unchanged.

Why this matters:

MCP is host extension infrastructure. Runtime construction, catalog merge,
external dispatch, and route helpers moved, but manager internals remain in
existing MCP paths.

Target:

Avoid over-pluginizing MCP. The capability adapter should own host integration,
while `mcp/manager.py` remains the protocol implementation.

Suggested work:

1. Audit whether any Engine/AppRuntime code still does MCP-specific manager
   orchestration that belongs in `capabilities/mcp.py`.
2. Do not move protocol/client code out of `mcp/`.
3. Add tests around:
   - warm cache
   - cold background discovery
   - missing manager error
   - external MCP approval/dispatch behavior

Acceptance:

- MCP integration tests pass.
- No behavior change to MCP config loading, startup failure policy, or tool
  result shaping.

Completed:

- Audit: Engine and AppRuntime MCP dispatch/preload now route through
  `capabilities/mcp.py` helpers (`try_execute_external_mcp_tool`,
  `schedule_mcp_preload_for_tool_runtime`, `mcp_preload_status_for_tool_runtime`).
  `list_mcp_servers` / `list_mcp_tools` / `mcp_startup` bodies remain in
  `app_server/runtime.py` (hook/event orchestration).
- `tests/host/test_mcp_integration_characterization.py` plus existing
  `tests/host/test_mcp_capability.py` coverage.

Risk:

- MCP servers are external processes. Avoid changing startup/shutdown semantics
  without integration tests.

## Refactor Phase Status (Priorities 1–10)

All planned characterization and safe-integration phases through Priority 10 are
complete.

## Priority 11: Remove Compatibility Debt

Status: steps 1–6 complete — `assemble_*` materializes from
`AssembledContributions`, the default builtin catalog registers contributions,
long-lived services use `ToolContext.services`, and legacy assembly aliases are
removed.

Completed in step 1:

- `assemble_registry_only()` builds registries via
  `build_tool_registry_from_contributions()`
- `assemble_tool_runtime()` calls `materialize_tool_runtime()` with collected
  contributions
- `assemble_engine()` collects contributions and passes them through
  `Engine._materialize(..., contributions=...)`
- Engine merges catalog lifecycle observers via `merge_lifecycle_registries()`
- Default tool packs remain the fallback when the builtin catalog is empty

Completed in step 2:

- `host/builtin_modules.py` registers first-party modules for tool packs, prompt
  contributors, and MCP/Evolution/Automation runtime surfaces
- `collect_builtin_contributions()` defaults to `default_builtin_catalog()`
  instead of `EMPTY_BUILTIN_CATALOG`
- `build_runtime_api_router()` mounts capability surfaces via
  `mount_surface_routes()` instead of static evolution/mcp/automation routers
- `EMPTY_BUILTIN_CATALOG` remains available for isolated/no-op collection tests

Completed in steps 3–6:

- Long-lived services (MCP, LSP, tasks, automation, memory provider, goal,
  evolution stores, hooks) register on `ToolContext.services` only
- Per-tool workflow/RLM bindings use `ToolContext.tool_execution` only
- Removed `_create_tool_runtime_legacy`, `_build_default_registry_legacy`
- Renamed `Engine._create_legacy` → `Engine._materialize`
- `ToolRuntime.shutdown()` documented as host shutdown coordinator

Completed post-P11 cleanup:

- `resolve_assembly_prompt_contributors()` wires `build_system_prompt()` to the
  default builtin catalog (removes duplicate contributor list in
  `engine/prompts.py`)
- `register_builtin_runtime_surfaces()` now mirrors catalog surface registration
  (always 17 routes; feature flags do not gate HTTP surface descriptors)
- `host/engine_attach.py::attach_engine_capabilities()` orchestrates
  memory/cycle/evolution/post_turn/subagent wiring; capability modules expose
  `attach_engine_*()` helpers; `Engine._materialize()` delegates to the host
  attach path

Completed final attach migration:

- `host/engine_lifecycle.py::register_engine_lifecycle_observers()` registers
  LSP, memory, post-turn, and goal observers at attach time (not in
  `Engine.__init__`).
- `capabilities/goal.py::attach_engine_goal()` creates goal runtime and service
  bindings during attach.
- `capabilities/hooks.py::attach_engine_hooks()` registers hook executor on
  services during attach.

Still deferred (separate projects):

1. Split CLI independently.
2. Consider versioned generic extension events/surfaces.
3. Consider external Python plugin loading as a separate project.
4. Static catalog lifecycle factories for observers that today need dynamic
   engine lambdas (optional future simplification).

## Known Pre-Existing Issues To Keep Separate

These are not part of the capability refactor unless deliberately fixed in a
separate change:

- `build_system_prompt(subagent_mandate=True)` references missing module
  `deepseek_tui.engine.subagent_intent`.
- Evolution procedural skill code imports `yaml`, but `pyproject.toml` does not
  declare `PyYAML`.
- `src/deepseek_tui/tools/knowledge_tools.py` has pre-existing line-length ruff
  issues.
- Some contract/integration tests have pre-existing unused-import or line-length
  ruff issues. Avoid broad `ruff --fix` on unrelated files unless committing
  those cleanups separately.

## Suggested Next Session Start

The planned refactor is complete. For follow-on work:

1. CLI split (`src/deepseek_tui/cli/app.py` monolith → per-command modules).
2. Versioned generic extension events/surfaces.
3. External Python plugin loading.

Regression command:

```bash
PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/workflow tests/engine/test_turn_evidence_sync.py tests/test_rlm_subagent_task_parity.py tests/test_rlm_subagent_task_integration.py tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/contract/test_goal_status_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py tests/test_mcp_engine_integration.py tests/test_mcp_preload.py -q
```

Optional focused tests:

```bash
PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_memory_capture_flush_characterization.py tests/host/test_memory_capability.py tests/host/test_lifecycle_and_surfaces.py tests/engine/test_turn_evidence_sync.py tests/memory tests/post_turn/test_orchestrator.py tests/app_server/test_lru_flush.py -q
```

5. Then run the comprehensive regression command from the Current Status
   section.

## Commit Guidance

This working tree is large. If splitting later:

1. Host foundation:
   - `src/deepseek_tui/host/`
   - `tests/host/test_services.py`
   - `tests/host/test_contributions.py`
   - `tests/host/test_lifecycle_and_surfaces.py`
2. ToolPack/prompt/service adapter migration.
3. Engine lifecycle/helper migrations.
4. Route/surface helper migrations.
5. Documentation updates.

Do not mix unrelated ruff-only cleanups into these commits.
