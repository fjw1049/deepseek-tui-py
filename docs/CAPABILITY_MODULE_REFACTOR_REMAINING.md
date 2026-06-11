# Capability Module Refactor Remaining Work

Last updated: 2026-06-11

This document is the handoff checklist for continuing the capability-module
refactor after the current large working tree. It is written against
`docs/CAPABILITY_MODULE_REFACTOR_PLAN.md` and the current implementation tracked
in `docs/CAPABILITY_MODULE_REFACTOR_PROGRESS.md`.

## Current Status

The refactor is not complete yet.

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
- Memory before-turn recall now goes through `LifecycleRegistry.before_user_turn`
  under the existing legacy Engine path.
- PostTurn/Evolution main-tool notification now goes through
  `LifecycleRegistry.after_tool` under the existing legacy Engine path.

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

## Definition Of Not Done

Do not call the complete refactor finished until these are true:

- `assemble_engine()`, `assemble_tool_runtime()`, and `assemble_registry_only()`
  no longer only delegate to legacy bodies.
- The assembler actually collects concrete capability contributions through
  `Contributions`.
- Lifecycle observers are registered once through host assembly, not ad hoc
  local registries inside `Engine`.
- Runtime API/event surfaces have a host-owned contribution registry path.
- `Engine` no longer directly constructs or reaches into feature controllers
  such as `GoalController`, `MemoryCoordinator`, LSP manager, or concrete
  Evolution pipeline paths except through host contracts.
- `ToolRuntime.shutdown()` ownership is either fully transferred to services or
  explicitly retained with no duplicate shutdown path.
- Full automated gates, selected live API tests, and manual smoke pass.

## Priority 1: Wire Contributions Into The Assembler

Why this matters:

`host/contributions.py`, `host/lifecycle.py`, and `host/surfaces.py` now exist,
but the assembler still does not collect real module contributions. Current
observer usage is local and temporary:

- Memory before-turn creates a local `LifecycleRegistry` in `Engine`.
- PostTurn after-tool creates a local `LifecycleRegistry` in `Engine`.

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

Why this matters:

Memory and PostTurn now use `LifecycleRegistry`, but `Engine` creates a new
local registry at each call site. This proves the observer contract but does not
yet satisfy the plan's host-owned lifecycle ordering goal.

Target:

`Engine` should hold one lifecycle registry for the engine/session, populated
during `_create_legacy()` or by the assembler compatibility adapter.

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

Risk:

- Duplicate memory capture is easy to introduce. Add explicit assertions.

## Priority 7: Evolution Review Scheduling And Ledger Events

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

Risk:

- Event and ledger changes are user-visible. Avoid broad rewrites here.

## Priority 8: Workflow/RLM Typed Execution Context

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

Risk:

- These are dynamic per-call bindings. Do not promote them to `ServiceRegistry`
  process/engine services.

## Priority 9: Runtime Surface Registry Integration

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

Risk:

- Changing route inclusion too early can break Workbench. Keep route shape
  static until parity is proven.

## Priority 10: MCP Manager Internals

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

Risk:

- MCP servers are external processes. Avoid changing startup/shutdown semantics
  without integration tests.

## Priority 11: Remove Compatibility Debt

Do this only after previous phases are green.

Items:

1. Remove migrated long-lived services from `ToolContext.metadata`.
2. Remove Engine compatibility properties after all call sites use services.
3. Remove duplicate legacy assembly bodies:
   - `_create_tool_runtime_legacy`
   - `_build_default_registry_legacy`
   - `Engine._create_legacy`
4. Transfer shutdown ownership fully to services or explicitly keep
   `ToolRuntime.shutdown()` as the host shutdown coordinator.
5. Split CLI independently.
6. Consider versioned generic extension events/surfaces.
7. Consider external Python plugin loading as a separate project.

Do not start this while `assemble_*` still delegates to legacy bodies.

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

Start here:

1. Read this file and `docs/CAPABILITY_MODULE_REFACTOR_PROGRESS.md`.
2. Run:

```bash
git status --short
```

3. Implement Priority 2 first: replace local lifecycle registries in Engine
   with one Engine-owned lifecycle registry.
4. Run focused tests:

```bash
PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_memory_capability.py tests/host/test_engine_wiring_capabilities.py tests/engine/test_turn_evidence_sync.py tests/memory -q
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
