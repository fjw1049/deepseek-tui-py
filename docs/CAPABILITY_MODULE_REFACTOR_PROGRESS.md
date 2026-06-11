# Capability Module Refactor Progress

## Current Phase

Phase 7 has started typed-service adoption in migrated tools, moved Workflow,
RLM, SubAgent, Hook, Cycle/Seam, PostTurn, and ToolRuntime shutdown details into
capability adapters, moved Memory turn-time helper logic into the Memory
capability adapter, moved Evolution evidence publication and Goal lifecycle
helpers into capability adapters, moved Task/MCP cross-wiring, MCP catalog
assembly, Workflow mode hints, and Cycle/Seam turn-time helper details into
capability adapters, moved MCP external tool dispatch helpers into the MCP
capability adapter, moved Workflow tool execution/validation orchestration into
the Workflow capability adapter, moved RLM tool execution/reporting into the RLM
capability adapter, moved Evolution API route ledger/record helpers into the
Evolution capability adapter, moved Goal status/follow-up surface helpers into
the Goal capability adapter, moved MCP runtime API route helpers into the MCP
capability adapter, moved Memory turn-start preparation into the Memory
capability adapter, moved Evolution main-tool response helpers into the
Evolution capability adapter, moved PostTurn after-turn/flush dispatch helpers
into the PostTurn capability adapter, moved Goal hidden follow-up request helper
details into the Goal capability adapter, moved legacy MCP route runtime-response
helpers into the MCP capability adapter, added host lifecycle/surface registries
and a `Contributions` collection for future observer/surface migrations, wired
Memory turn-start recall through the lifecycle registry under the legacy Engine
path, wired PostTurn main-tool notifications through the lifecycle registry
under the legacy Engine path, and moved the remaining core prompt contributors out of `engine/prompts.py`. Phase 6 moved Memory, Evolution, and Goal
runtime/service construction into capability adapters while keeping turn
lifecycle timing in `Engine`.
Phase 5 introduced the PromptContributor extension contract and moved
prompt-only ownership for Skills, Workflow, Memory, and Evolution into
capability adapters while keeping `build_system_prompt(...)` as the public
compatibility entry point. Phase 4 moved the process-level managers out of
`tools/runtime.py`: LSP, MCP, Tasks, SubAgents, and Automation. The three public
construction entry points already enter `host.assembler`, and
`build_default_registry(...)` delegates tool ownership to first-party ToolPacks.

## Completed In This Step

### Phase 7 Typed Service Adoption + Engine Wiring Adapters

- Added host contribution contracts needed by the later observer/surface phases:
  - `host/lifecycle.py` with explicit before-turn, turn-completion,
    turn-failure, before-tool, and after-tool observer phases.
  - `host/surfaces.py` with runtime route and event presenter contribution
    registries.
  - `host/contributions.py` with the aggregate `Contributions` collection for
    services, ToolPacks, prompt contributors, lifecycle observers, post-turn
    pipelines, and runtime surfaces.
- Updated `CapabilityModule.contribute(...)` to accept `Contributions` as its
  typed input while keeping imports type-check-only to avoid host/tools cycles.
- Added `capabilities/core_prompt.py` and moved the remaining core prompt
  contributors out of `engine/prompts.py`:
  - project context
  - environment block
  - context management guidance
  - compaction template
  - previous-session handoff
  - working-set summary
  - subagent mandate
- Preserved `engine.prompts.render_environment_block(...)` as a compatibility
  wrapper over the new core prompt adapter.
- Added `capabilities/rlm.py` with `rlm_tool_bindings()`.
- Moved RLM progress callback setup/cleanup out of `Engine._execute_tool()`.
- Extended `capabilities/rlm.py` with `execute_rlm_tool()` and moved RLM input
  validation, file/inline content loading, child model pinning, progress callback
  lookup, `run_rlm_turn()` invocation, error shaping, report rendering, trace
  summary, and metadata payload construction out of `tools/rlm/tool.py`.
- Extended `capabilities/subagents.py` with:
  - `attach_subagent_engine_bindings()`
  - `attach_subagent_parent_cancel()`
- Moved SubAgent parent cancel, parent completion sink, and loop runtime
  attachment out of `Engine._create_legacy()`.
- Moved per-turn parent cancel refresh to the SubAgent capability adapter.
- Added `capabilities/hooks.py` and moved Hook dispatcher construction,
  lifecycle `HookExecutor` construction, normalization, and legacy
  `metadata["hook_executor"]` binding into the Hook capability adapter.
- Added `capabilities/cycle.py` and moved CycleConfig, optional SeamManager,
  cycle session id, and cycle started timestamp creation into the Cycle/Seam
  capability adapter.
- Added `capabilities/post_turn.py` and moved Memory/Evolution post-turn
  pipeline assembly plus PostTurnOrchestrator start/stop helpers into the
  PostTurn capability adapter.
- Extended `capabilities/post_turn.py` with `run_post_turn_after_turn()` and
  `flush_post_turn_before_loss()`, moving after-turn dispatch, direct
  smart-memory capture fallback, and compaction-before-loss flush dispatch out
  of inline Engine branches.
- Extended `capabilities/post_turn.py` with `PostTurnToolObserver` and
  `post_turn_tool_observer()`, then routed Engine's successful tool-result
  main-tool notifications through `LifecycleRegistry.after_tool()`. This
  preserves the existing EvolutionPipeline `on_main_tool_called()` scheduler
  reset behavior.
- Moved ToolRuntime manager shutdown details into capability adapters:
  - Automation scheduler cancel/wait/cancel fallback:
    `stop_automation_runtime()`
  - Mailbox close and owned SubAgentManager shutdown:
    `shutdown_subagent_runtime()`
  - Owned TaskManager shutdown: `shutdown_task_manager()`
  - Owned McpManager shutdown: `shutdown_mcp_manager()`
  - LspManager close-all: `shutdown_lsp_manager()`
- Extended `capabilities/memory.py` with turn-time helpers:
  - trivial recall skip detection
  - memory thread id resolution
  - `memory.md` enablement check
  - turn-start search budget reset, recall, and user-message injection wrapping
  - `MemoryBeforeTurnObserver` lifecycle adapter and memory turn-context
    decoration key
  - turn capture message serialization
  - tool-call detection for evidence
  - TurnEvidence and flush evidence construction
  - smart-memory recall invocation
  - direct capture fallback when PostTurn is disabled
- Extended `capabilities/evolution.py` with `publish_turn_evidence()` and moved
  `TURN_EVIDENCE_KEY`, `TURN_EVIDENCE_FACTORY_KEY`, and
  `EvolutionPipeline.note_active_turn()` publication details out of Engine.
- Extended `capabilities/evolution.py` with `evolution_record_to_dict()` and
  `evolution_ledger_for_thread()`, then routed the Workbench Evolution approval
  endpoints through those helpers while preserving URLs, status codes, and
  response payload shapes.
- Extended `capabilities/evolution.py` with
  `evolution_decision_from_record_status()` and
  `build_main_tool_evolution_response()`, then routed `memory_curate` and
  `skill_manage` main-agent response shaping through those helpers while
  preserving tool result payloads.
- Extended `capabilities/goal.py` with Goal lifecycle helpers:
  - local thread rebinding
  - runtime thread rebind + change callback binding
  - goal-mode hint rendering
  - follow-up stale validation
  - hidden follow-up request payload construction
  - turn start/fail/finish calls
  - pending steer extraction
  - follow-up dispatch eligibility
  - `goal.status` SSE payload construction
  - pending follow-up take+validate helper
- Extended `capabilities/tasks.py` with `attach_task_mcp_bridge()` and moved
  TaskManager's shared MCP executor reuse wiring out of `tools/runtime.py`.
- Extended `capabilities/mcp.py` with:
  - `mcp_manager_from_runtime_or_context()`
  - `build_mcp_augmented_tool_catalog()`
  - `is_external_mcp_tool_call()`
  - `execute_mcp_tool()`
  - `mcp_startup_response()`
  - `mcp_preload_status_response()`
  - legacy app-server/stdio runtime response helpers for MCP startup and
    `/apps/mcp/*` list routes
  These preserve runtime/context service lookup, warm-cache behavior, background
  discovery deferral, MCP/native catalog merge order, tool profile filtering,
  external MCP tool identification, missing-manager errors, and
  `execute_external_mcp_tool()` result shaping, plus `/v1/mcp/startup` and
  `/v1/mcp/preload-status` runtime delegation.
- Extended `capabilities/workflow.py` with `workflow_mode_hint()`.
- Extended `capabilities/workflow.py` with:
  - `resolve_workflow_spec()`
  - `execute_workflow_tool()`
  These preserve script+spec merge behavior, validation error shaping,
  SubAgentManager/loop runtime checks, progress/status callbacks, timeout
  cancellation, spawned-agent cancellation, result rendering, and metadata
  payloads.
- Extended `capabilities/cycle.py` with:
  - `apply_layered_context_checkpoint()`
  - `advance_cycle_if_needed()`
  These preserve Seam threshold detection, pinned working-set handling, seam
  recompact/produce behavior, cycle threshold detection, archive behavior, and
  recent-message retention.
- Extended `capabilities/workflow.py` with `workflow_tool_bindings()`.
- Moved workflow tool-call scoped metadata setup/cleanup out of
  `Engine._execute_tool()`:
  - `engine_cancel_event`
  - `workflow_tool_call_id`
  - `workflow_emit`
  - `workflow_status_cb`
- Preserved Workflow event payloads, status events, cancel behavior, RLM progress
  event payloads, SubAgent completion wakeup behavior, parent cancellation,
  Hook lifecycle behavior, Cycle/Seam opt-in defaults, PostTurn pipeline order,
  ToolRuntime shutdown order/ownership semantics, Memory recall/capture timing,
  evidence payload shape, Memory turn-start lifecycle observer decoration and
  recall injection behavior, PostTurn after-turn/capture fallback/flush dispatch
  behavior, PostTurn after-tool main-tool notification behavior, Evolution
  live/final evidence metadata semantics, Evolution main-tool response payloads,
  Evolution main-tool scheduler reset behavior, Goal turn
  accounting/follow-up/status payload semantics, Goal hidden follow-up request
  payload semantics, Task/MCP bridge semantics, MCP tool catalog/dispatch/runtime
  route helper behavior, MCP legacy app-server/stdio route behavior, Workflow
  mode hint text, Workflow tool execution behavior, RLM tool execution/reporting
  behavior, Evolution approval route helper behavior, Cycle/Seam archive and
  seam append behavior, and cleanup semantics.
- Updated migrated tools to read typed/named services first and fall back to
  legacy `ToolContext.metadata`:
  - Goal tools: `GoalController`
  - Memory tools and `remember`: `MEMORY_PROVIDER_KEY`
  - Automation tools: `AutomationManager` and run-now `TaskManager`
  - MCP resource/prompt tools: `McpManager`
  - Evolution curated/skill tools: store and ledger named services
  - Task tools and Todo checklist forwarding: `TaskManager`
  - Shell tools: lifecycle `HookExecutor`
  - SubAgent tools: `SubAgentManager`
- Registered Hook executor as a typed and named service while preserving
  `metadata["hook_executor"]`.
- Registered SubAgentManager as a named service in addition to the existing
  typed service.
- Kept all existing metadata writes for compatibility with current callers and
  tests.
- Added service-first tool tests for Goal, Memory, Automation, MCP, Evolution,
  Task, Todo, Shell, and SubAgent lookups; Workflow scoped binding cleanup
  tests; SubAgent Engine binding tests; and Hook/Cycle/PostTurn wiring tests.

### Phase 6 Engine-Owned Runtime Migration: Goal

- Added `capabilities/goal.py` with `GoalRuntime`,
  `create_goal_runtime()`, and `attach_goal_legacy_bindings()`.
- Moved `GoalController` construction and `GOAL_CONTROLLER_KEY` metadata
  binding out of `Engine.__init__()`.
- Added typed service registration for `GoalController` and a named legacy
  service for `GOAL_CONTROLLER_KEY`.
- Preserved `engine.goal_controller`, workspace resolution, default/thread id
  behavior, and legacy tool access through `ToolContext.metadata`.
- Kept all Goal turn lifecycle behavior in Engine:
  `on_turn_start()`, `on_turn_complete()`, `on_turn_failed()`,
  follow-up validation, steer handling, and hidden follow-up scheduling.
- Added Goal capability tests for controller creation, legacy binding,
  typed/named service registration, duplicate-service compatibility, and
  Engine integration.

### Phase 6 Engine-Owned Runtime Migration: Evolution

- Extended `capabilities/evolution.py` beyond prompt-only ownership with
  `EvolutionRuntime`, `create_evolution_runtime()`, and
  `attach_evolution_legacy_bindings()`.
- Moved `build_evolution_pipeline(...)`, curated stable snapshot resolution, and
  legacy metadata binding out of `Engine._create_legacy()`.
- Preserved existing Engine fields:
  - `engine._curated_snapshot`
  - `engine._evolution_pipeline`
- Preserved existing post-turn lifecycle: EvolutionPipeline is still appended to
  the Engine-owned `pipelines` list and started/stopped by PostTurnOrchestrator.
- Preserved legacy metadata:
  - `CURATED_MEMORY_STORE_KEY`
  - `SKILL_STORE_KEY`
  - `EVOLUTION_LEDGER_KEY`
- Added typed service registration for `EvolutionPipeline` and named legacy
  services for the metadata keys.
- Kept pipeline import lazy so prompt-only `capabilities.evolution` imports do
  not require PyYAML.
- Did not migrate review scheduling, ledger behavior, approval policy, API
  routes, events, tool response behavior, turn evidence publication, or
  post-turn orchestration.
- Added Evolution capability tests for disabled configuration, enabled pipeline
  creation, legacy binding, typed service registration, and Engine integration.

### Phase 6 Engine-Owned Runtime Migration: Memory

- Extended `capabilities/memory.py` beyond prompt-only ownership with
  `MemoryRuntime`, `create_memory_runtime()`, and
  `attach_memory_legacy_bindings()`.
- Moved smart-memory provider creation, `MemoryCoordinator` construction/start,
  `memory_enabled`, `memory_path`, and `memory_mode` resolution out of
  `Engine._create_legacy()`.
- Preserved existing Engine attributes:
  - `engine.memory_enabled`
  - `engine.memory_path`
  - `engine.memory_mode`
  - `engine.memory_coordinator`
- Preserved legacy metadata:
  - `MEMORY_SEARCH_CALLS_KEY` initialized to `0`
  - `MEMORY_PROVIDER_KEY` populated only when smart memory is active
- Added typed services for `MemoryCoordinator` and `MemoryProvider`, plus a
  named legacy service for `MEMORY_PROVIDER_KEY`.
- Kept duplicate typed service registration non-fatal for shared runtime
  compatibility; the Engine attribute remains the source of truth for turn-time
  memory behavior.
- Did not migrate recall, capture, flush, tool search behavior, memory tools,
  provider implementation, or post-turn evidence handling.
- Added Memory capability tests for disabled/manual behavior, smart runtime
  creation, legacy binding, typed service registration, and shared-runtime
  duplicate-service compatibility.

### Phase 5 PromptContributor Foundation

- Added `host/prompts.py` with `PromptContributorContext`,
  `PromptContributor`, `PromptContribution`, `FunctionPromptContributor`, and
  ordered composition helper `append_prompt_contributions()`.
- Refactored `engine/prompts.py::build_system_prompt()` internally from one
  long feature-aware append sequence into `compose_prompt(...)` plus ordered
  default contributors.
- Added prompt-only capability adapters:
  - `capabilities/skills.py` owns rendered skills context injection.
  - `capabilities/workflow.py` owns workflow guidance injection.
  - `capabilities/memory.py` owns stable memory recall, volatile L1 recall, and
    user `memory.md` prompt blocks.
  - `capabilities/evolution.py` owns curated snapshot, Evolution guidance, and
    session-evolution prompt blocks.
- Preserved the public `build_system_prompt(...)` signature, override behavior,
  prompt block order, block text, and call sites.
- Kept core prompt contributors colocated in `engine/prompts.py` for now:
  project context, environment, context management, compaction template, handoff,
  working set, and SubAgent mandate.
- Added PromptContributor tests for ordering and prompt block-order parity.

### Phase 4 Runtime Service Migration: LSP

- Added `capabilities/lsp.py` as the LSP capability adapter.
- Moved LSP manager creation out of `tools/runtime.py`.
- Moved LSP legacy metadata/named-service binding out of `tools/runtime.py`.
- Preserved `ToolRuntime.lsp_manager`, `ToolContext.metadata[LSP_MANAGER_KEY]`,
  typed `ServiceRegistry[LspManager]`, and shutdown behavior.
- Added LSP capability tests for disabled/enabled configuration and legacy
  binding compatibility.

### Phase 4 Runtime Service Migration: MCP

- Added `capabilities/mcp.py` as the MCP capability adapter.
- Moved MCP manager creation out of `tools/runtime.py`.
- Moved MCP legacy metadata/named-service binding out of `tools/runtime.py`.
- Preserved provided-manager ownership semantics, `start_mcp` startup behavior,
  `ToolRuntime.mcp_manager`, `ToolRuntime._owns_mcp_manager`, and
  `ToolContext.metadata[MCP_MANAGER_KEY]`.
- Added MCP capability tests for disabled configuration, provided-manager
  ownership, and legacy binding compatibility.

### Phase 4 Runtime Service Migration: Tasks

- Added `capabilities/tasks.py` as the TaskManager capability adapter.
- Moved TaskManager construction out of `tools/runtime.py`.
- Moved `metadata["task_manager"]` and legacy named-service binding out of
  `tools/runtime.py`.
- Preserved shared TaskManager ownership semantics, owned-manager startup,
  `ToolRuntime.task_manager`, `ToolRuntime._owns_task_manager`,
  `ToolContext.task_manager`, and Automation's fail-fast dependency behavior.
- Kept `tools/runtime.py` in control of cross-service wiring
  (`TaskManager._shared_mcp_manager`) and Automation scheduler startup.
- Added Task capability tests for disabled configuration, shared manager
  ownership, owned manager startup, and legacy binding compatibility.

### Phase 4 Runtime Service Migration: SubAgents

- Added `capabilities/subagents.py` as the SubAgent capability adapter.
- Moved `SubAgentManager` and `Mailbox` construction out of `tools/runtime.py`.
- Preserved max-agent calculation, default model selection, state path behavior,
  `ToolRuntime.subagent_manager`, `ToolRuntime.mailbox`, `ToolContext.subagent_manager`,
  and typed `ServiceRegistry[SubAgentManager]`.
- Kept parent cancel, parent completion sink, and loop-runtime attachment in
  `Engine.create()` for now.
- Added SubAgent capability tests for disabled configuration, manager/mailbox
  creation, state path behavior, max-agent cap, and typed service registration.

### Phase 4 Runtime Service Migration: Automation

- Added `capabilities/automation.py` as the Automation capability adapter.
- Moved `AutomationManager` construction and scheduler task startup out of
  `tools/runtime.py`.
- Moved `AUTOMATION_MANAGER_KEY` legacy metadata/named-service binding out of
  `tools/runtime.py`.
- Preserved `features.automations requires features.tasks=True`, scheduler task
  name, cancel event, tick interval behavior, `ToolRuntime.automation_manager`,
  `ToolRuntime._automation_scheduler_task`, `ToolRuntime._automation_cancel`,
  and `ToolContext.metadata[AUTOMATION_MANAGER_KEY]`.
- Kept TaskManager construction and legacy `metadata["task_manager"]` binding
  in the Tasks adapter, so Automation still sees the same runtime dependency.
- Added Automation capability tests for disabled configuration, fail-fast
  dependency behavior, scheduler startup, and legacy binding compatibility.

### Phase 3 ToolPack Migration

- Added `host/toolpacks.py` with the `ToolPack` protocol.
- Added `capabilities/toolpacks.py` as the first-party ToolPack adapter layer.
- Moved concrete tool imports and feature-gated tool lists out of
  `tools/builder.py`.
- Kept `build_default_registry()` and `_build_default_registry_legacy()` as
  compatibility entry points.
- Preserved existing registration order by encoding the old builder block order
  in `default_tool_packs()`.
- Added ToolPack tests for pack ordering, plan-mode filtering, and feature
  gates.

### Phase 2 Compatibility Assembly

- Added `host/assembler.py` with `AssemblyRequest` and
  `assemble_tool_runtime()`.
- Changed public `create_tool_runtime()` into a compatibility wrapper that
  builds an `AssemblyRequest` and enters the host assembler.
- Preserved the previous runtime construction body as
  `_create_tool_runtime_legacy()` for rollback and parity comparisons.
- Added `assemble_registry_only()` and changed public
  `build_default_registry()` into a compatibility wrapper over
  `_build_default_registry_legacy()`.
- Added `EngineAssemblyRequest` and `assemble_engine()`, then changed public
  `Engine.create()` into a compatibility wrapper over `Engine._create_legacy()`.
- Added a direct assembler compatibility test so the new entry point is not an
  isolated module.

### Phase 1 Foundation

- Added `deepseek_tui.host` as the stable package for capability-module host
  contracts.
- Added `ServiceRegistry` with typed service registration, named legacy-key
  registration, duplicate detection, owner/scope metadata, and reverse
  best-effort shutdown.
- Added `ServiceScope` with `process`, `engine`, `thread`, and `turn` scopes so
  future modules can distinguish shared runtime services from thread/turn
  scoped state.
- Added `ModuleDescriptor`, `CapabilityModule`, and dependency-order resolution
  helpers.
- Added an empty `BuiltinModuleCatalog`; this deliberately does not discover
  arbitrary Python plugins.
- Added `ToolContext.services` while keeping all existing `ToolContext`
  fields and `metadata`.
- Extended `create_tool_runtime()` to populate typed services and legacy named
  service aliases for current managers:
  - `TaskManager`
  - `SubAgentManager`
  - `McpManager`
  - `LspManager`
  - `AutomationManager`
- Added focused tests for service registry behavior and runtime compatibility.

## Added Files

- `src/deepseek_tui/host/__init__.py`
- `src/deepseek_tui/host/services.py`
- `src/deepseek_tui/host/module.py`
- `src/deepseek_tui/host/catalog.py`
- `src/deepseek_tui/host/assembler.py`
- `src/deepseek_tui/host/toolpacks.py`
- `src/deepseek_tui/host/prompts.py`
- `src/deepseek_tui/host/lifecycle.py`
- `src/deepseek_tui/host/surfaces.py`
- `src/deepseek_tui/host/contributions.py`
- `src/deepseek_tui/capabilities/__init__.py`
- `src/deepseek_tui/capabilities/toolpacks.py`
- `src/deepseek_tui/capabilities/lsp.py`
- `src/deepseek_tui/capabilities/mcp.py`
- `src/deepseek_tui/capabilities/tasks.py`
- `src/deepseek_tui/capabilities/subagents.py`
- `src/deepseek_tui/capabilities/automation.py`
- `src/deepseek_tui/capabilities/skills.py`
- `src/deepseek_tui/capabilities/workflow.py`
- `src/deepseek_tui/capabilities/memory.py`
- `src/deepseek_tui/capabilities/evolution.py`
- `src/deepseek_tui/capabilities/goal.py`
- `src/deepseek_tui/capabilities/core_prompt.py`
- `src/deepseek_tui/capabilities/rlm.py`
- `tests/host/test_services.py`
- `tests/host/test_runtime_services.py`
- `tests/host/test_registry_assembly.py`
- `tests/host/test_lsp_capability.py`
- `tests/host/test_mcp_capability.py`
- `tests/host/test_task_capability.py`
- `tests/host/test_subagent_capability.py`
- `tests/host/test_automation_capability.py`
- `tests/host/test_prompt_contributors.py`
- `tests/host/test_memory_capability.py`
- `tests/host/test_evolution_capability.py`
- `tests/host/test_goal_capability.py`
- `tests/host/test_service_first_tools.py`
- `tests/host/test_lifecycle_and_surfaces.py`
- `tests/host/test_contributions.py`

## Modified Files

- `src/deepseek_tui/tools/context.py`
- `src/deepseek_tui/tools/runtime.py`
- `src/deepseek_tui/tools/builder.py`
- `src/deepseek_tui/goal/tools.py`
- `src/deepseek_tui/tools/automation_tools.py`
- `src/deepseek_tui/tools/knowledge_tools.py`
- `src/deepseek_tui/tools/mcp_tools.py`
- `src/deepseek_tui/tools/memory_curate_tool.py`
- `src/deepseek_tui/tools/memory_tools.py`
- `src/deepseek_tui/tools/skill_manage_tool.py`
- `src/deepseek_tui/engine/engine.py`
- `src/deepseek_tui/engine/prompts.py`
- `src/deepseek_tui/app_server/routes.py`
- `docs/HANDOVER.md`

## Removed Files

None.

## Compatibility Preserved

- `Engine.create(...)`, `create_tool_runtime(...)`, and
  `build_default_registry(...)` still exist.
- Existing managers are still constructed by the existing runtime path.
- Existing `ToolRuntime` fields remain populated.
- Existing `ToolContext.metadata` keys remain populated.
- Existing tool names, prompt output, events, API routes, persistence formats,
  TUI behavior, and Workbench behavior are not changed by this step.
- Tool implementations remain in `src/deepseek_tui/tools/`; the new
  `capabilities/toolpacks.py` file only adapts them to host registry assembly.
- LSP post-edit behavior is not changed; only manager construction and binding
  ownership moved.
- MCP tool dispatch, preload/discovery, startup failure policy, and API routes
  are not changed; only manager construction and binding ownership moved.
- Task execution, persistence format, queue behavior, task tools, and
  Automation scheduling are not changed; only manager construction and binding
  ownership moved.
- SubAgent execution, persistence format, mailbox protocol, parent cancellation,
  completion sink, and loop-runtime attachment are not changed; construction and
  Engine wiring ownership moved to `capabilities/subagents.py`.
- Hook dispatcher, lifecycle executor, and legacy metadata binding behavior are
  unchanged; construction and binding ownership moved to `capabilities/hooks.py`.
- Cycle/Seam runtime behavior remains opt-in and unchanged; config/session
  timestamp/optional seam manager creation plus turn-time seam/cycle helper
  details moved to `capabilities/cycle.py`.
- PostTurn pipeline ordering, start/stop semantics, after-turn calls,
  flush-before-loss calls, and tool-called notifications are unchanged; pipeline
  assembly, orchestrator start/stop helpers, after-turn dispatch, direct capture
  fallback, and flush dispatch moved to
  `capabilities/post_turn.py`.
- Automation tools, automation record formats, scheduler tick implementation,
  task enqueue behavior, and API routes are not changed; only manager
  construction, scheduler startup, binding ownership, and scheduler shutdown
  helper moved.
- ToolRuntime shutdown order is unchanged: Automation scheduler, SubAgent
  mailbox/manager, TaskManager, McpManager, then LspManager. Individual shutdown
  details now live in the owning capability adapters, while `ToolRuntime`
  remains the ordering coordinator.
- Prompt output remains equivalent for covered blocks; Skills, Workflow,
  Memory, Evolution, and core prompt ownership moved to capability adapters.
- Memory provider/coordinator construction, legacy metadata binding,
  turn-start preparation, recall invocation, user-message injection wrapping,
  direct capture fallback, and evidence construction are equivalent; Engine
  still owns when those helpers are called in the turn lifecycle.
- Evolution pipeline construction, curated snapshot resolution, and legacy
  metadata binding are equivalent; turn evidence publication details moved to
  `capabilities/evolution.py`; Workbench route ledger lookup and record
  serialization helpers plus main-tool response shaping also moved to the
  Evolution capability adapter. Review scheduling, ledger mutation behavior,
  events, and PostTurnOrchestrator ownership are unchanged.
- GoalController construction, legacy metadata binding, lifecycle helper
  behavior, runtime thread binding, `goal.status` payload shape, pending
  follow-up validation, and hidden follow-up request payload construction are
  equivalent; Engine/RuntimeThreadManager still own when those helpers run in
  the turn lifecycle and when hidden follow-up turns are scheduled.
- Goal, Memory, Automation, MCP, Evolution, Task, Todo, Shell, and SubAgent
  tools still accept legacy metadata, but now prefer typed/named services when
  available for long-lived runtime dependencies.
- Workflow progress/cancel/status callbacks are still exposed through the same
  metadata keys, but setup/cleanup, mode hint text, spec resolution, and tool
  execution orchestration are now owned by the Workflow capability adapter.
- RLM progress callbacks are still exposed through the same metadata key, but
  setup/cleanup and tool execution/reporting ownership moved to
  `capabilities/rlm.py`.
- MCP startup/preload routes plus legacy app-server/stdio MCP startup and
  `/apps/mcp/*` list routes keep the same URLs and delegate to the same
  `AppRuntime` methods; route helper ownership moved to `capabilities/mcp.py`.

## Known Remaining Work

Detailed continuation checklist: `docs/CAPABILITY_MODULE_REFACTOR_REMAINING.md`.

- `ServiceRegistry` is now available and the migrated Goal, Memory, Automation,
  MCP, Evolution, Task, Todo, Shell, and SubAgent tools read typed/named
  services first. Remaining metadata lookups are mostly short-lived per-call or
  per-turn bindings (`workflow_*`, `rlm_progress_cb`, `subagent_runtime`,
  `parent_session_messages`, shell process stores, todo in-memory store, active
  task id), which should not be promoted to process/engine services without a
  narrower lifecycle contract.
- `ToolRuntime.shutdown()` still coordinates shutdown order for the current
  runtime. Individual manager shutdown details have moved to capability
  adapters, but callers should still not call both `ToolRuntime.shutdown()` and
  `context.services.shutdown()` for the same runtime until service ownership is
  fully transferred.
- The assembler is introduced for the three public construction entry points,
  but each path still delegates to legacy implementation bodies.
- Host lifecycle/surface registries and `Contributions` now exist. Memory
  before-turn recall is the first lifecycle-backed dispatch under the legacy
  Engine path, but the assembler does not yet collect concrete capability
  contributions through `Contributions`.
- `assemble_tool_runtime()` still delegates to `_create_tool_runtime_legacy()`;
  manager construction ownership has moved into capability adapters inside that
  compatibility body.
- `assemble_registry_only()` still delegates to `_build_default_registry_legacy()`;
  the legacy function now registers default ToolPacks rather than owning
  concrete tool lists directly.
- `assemble_engine()` still delegates to `Engine._create_legacy()`; Memory,
  Evolution, Goal, SubAgent Engine wiring, Hook wiring, Cycle/Seam setup, and
  PostTurn assembly are now delegated to capability adapters, while turn-time
  behavior remains in existing Engine paths.
- LSP runtime service construction has moved, but LSP observer behavior is
  still owned by existing Engine/tool execution paths.
- MCP runtime service construction, dynamic catalog assembly, external tool
  dispatch helper details, runtime API startup/preload route helpers, and legacy
  app-server/stdio route helper details have moved, but manager internals remain
  owned by existing MCP paths.
- TaskManager construction and Task/MCP cross-wiring have moved, while task
  execution behavior remains owned by existing manager/tool paths.
- SubAgentManager construction and Engine wiring have moved, but SubAgent
  execution, persistence, mailbox protocol, and parent completion consumption
  remain owned by existing manager/Engine paths.
- Automation scheduler construction and shutdown details have moved, but
  `ToolRuntime.shutdown()` still coordinates shutdown order through the existing
  task/cancel fields.
- `engine/prompts.py` is now mostly a compatibility wrapper around ordered
  contributors; `build_system_prompt(subagent_mandate=True)` still reaches a
  missing module through the core prompt contributor.
- Memory runtime construction, before-turn recall observer, turn-start
  decoration, helper logic, capture fallback dispatch, and flush-before-loss
  dispatch have moved, but Engine still owns turn lifecycle timing for
  recall/capture/flush and post-turn evidence publication.
- Evolution runtime construction, turn evidence publication details,
  approval-route helper details, main-tool response shaping, and main-tool
  scheduler reset dispatch have moved, but review scheduling, ledger mutation
  behavior, and evolution events are still owned by existing Engine/evolution
  paths.
- Goal runtime construction, lifecycle helper details, runtime thread binding,
  status payload construction, pending follow-up validation, and hidden
  follow-up payload construction have moved, but Engine/RuntimeThreadManager
  still own turn lifecycle timing and hidden follow-up scheduling.
- Workflow tool-call scoped bindings and tool execution/validation orchestration
  have moved, but the underlying Workflow runtime package, progress event
  schema, and server/TUI rendering remain unchanged.
- RLM tool-call scoped progress binding and tool execution/reporting helper have
  moved, but the underlying RLM turn loop package and progress event schema
  remain unchanged.
- Remaining high-coupling areas after the latest audit:
  - Memory capture/flush trigger timing in the Engine turn lifecycle
  - Lifecycle registry collection through assembler `Contributions`
  - Evolution review scheduling/ledger events
  - Goal turn lifecycle timing and hidden follow-up scheduling trigger
  - RLM turn loop internals
  - Workflow runtime package/server/TUI rendering surfaces
  - MCP manager internals
  - Runtime/API event surface versioning
- `src/deepseek_tui/tools/knowledge_tools.py` has pre-existing E501 long-line
  ruff issues outside this refactor. Scoped ruff checks exclude that file while
  compile/tests cover the service-first edit in it.
- Evolution procedural skill code imports `yaml`; current verification uses
  `uv run --with pyyaml ...`. `pyproject.toml` does not currently declare
  `PyYAML`.
- `build_system_prompt(subagent_mandate=True)` still references
  `deepseek_tui.engine.subagent_intent`, which is not present in the current
  tree. This appears to be pre-existing and was not changed in this phase.
- Events and runtime API surfaces remain unchanged; versioned extension events
  are still deferred.

## Verification

Completed:

```bash
PYTHONPATH=src .venv/bin/python -m compileall -q src/deepseek_tui/host src/deepseek_tui/tools/context.py src/deepseek_tui/tools/runtime.py tests/host
PYTHONPATH=src .venv/bin/python - <<'PY'
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.host.services import ServiceRegistry
from pathlib import Path
ctx = ToolContext(working_directory=Path('.'))
assert isinstance(ctx.services, ServiceRegistry)
print('host imports ok')
PY

PYTHONPATH=src .venv/bin/python - <<'PY'
from deepseek_tui.host import AssemblyRequest, assemble_tool_runtime
from deepseek_tui.tools.runtime import create_tool_runtime
print(AssemblyRequest.__name__, callable(assemble_tool_runtime), callable(create_tool_runtime))
PY

PYTHONPATH=src .venv/bin/python - <<'PY'
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.tools.runtime import create_tool_runtime

async def main():
    with TemporaryDirectory() as td:
        cfg = Config(features=FeatureConfig(tasks=False, subagents=False, mcp=False, automations=False))
        runtime = await create_tool_runtime(config=cfg, working_directory=Path(td))
        assert runtime.context.working_directory == Path(td).resolve()
        assert runtime.context.metadata == {}
        await runtime.shutdown()
    print('runtime wrapper ok')

asyncio.run(main())
PY

PYTHONPATH=src .venv/bin/python - <<'PY'
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.tools.builder import build_default_registry
cfg = Config(features=FeatureConfig(tasks=False, subagents=False, mcp=False))
registry = build_default_registry(cfg, mode='plan')
assert registry.contains('read_file')
assert not registry.contains('edit_file')
print('registry wrapper ok')
PY

PYTHONPATH=src .venv/bin/python - <<'PY'
import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.handle import EngineHandle

async def main():
    with TemporaryDirectory() as td:
        handle = EngineHandle()
        cfg = Config(features=FeatureConfig(tasks=False, subagents=False, mcp=False, automations=False))
        engine = await Engine.create(handle=handle, client=AsyncMock(), config=cfg, working_directory=Path(td))
        assert engine.tool_context.working_directory == Path(td).resolve()
        await engine.shutdown_session()
        handle.drain_events()
    print('engine wrapper ok')

asyncio.run(main())
PY

PYTHONPATH=src .venv/bin/python - <<'PY'
from deepseek_tui.capabilities.toolpacks import default_tool_packs
from deepseek_tui.config.models import Config, FeatureConfig
from deepseek_tui.tools.builder import build_default_registry
assert default_tool_packs()[0].id == 'core_read'
cfg = Config(features=FeatureConfig(tasks=True, subagents=True, mcp=True, automations=False))
registry = build_default_registry(cfg, mode='agent')
for name in ['read_file', 'task_create', 'agent_spawn', 'list_mcp_resources']:
    assert registry.contains(name), name
assert not registry.contains('automation_create')
print('toolpacks final ok', len(registry.names()))
PY

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host -q
# 47 passed, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/memory/test_prompts_memory.py -q
# 40 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/memory -q
# 126 passed, 3 skipped

PYTHONPATH=src uv run --with ruff --index-url https://pypi.tuna.tsinghua.edu.cn/simple ruff check src/deepseek_tui/capabilities src/deepseek_tui/host src/deepseek_tui/engine/engine.py src/deepseek_tui/engine/prompts.py src/deepseek_tui/goal/tools.py src/deepseek_tui/tools/memory_tools.py src/deepseek_tui/tools/automation_tools.py src/deepseek_tui/tools/mcp_tools.py src/deepseek_tui/tools/skill_manage_tool.py src/deepseek_tui/tools/memory_curate_tool.py tests/host
# All checks passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/test_automation_manager.py -q
# 3 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/test_session_activity_integration.py -q
# 9 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/memory/test_prompts_memory.py tests/test_automation_manager.py tests/test_session_activity_integration.py -q
# 52 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/memory tests/test_automation_manager.py tests/test_session_activity_integration.py -q
# 138 passed, 3 skipped

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/memory tests/evolution tests/test_automation_manager.py tests/test_session_activity_integration.py -q
# 185 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/test_automation_manager.py tests/test_session_activity_integration.py -q
# 229 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py -q
# 241 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_subagent_capability.py tests/test_session_activity_integration.py -q
# 14 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_prompt_contributors.py tests/host/test_service_first_tools.py tests/memory/test_prompts_memory.py -q
# 16 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_engine_wiring_capabilities.py tests/host/test_subagent_capability.py tests/post_turn/test_orchestrator.py tests/test_session_activity_integration.py -q
# 21 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/post_turn/test_orchestrator.py -q
# 248 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_service_first_tools.py tests/host/test_engine_wiring_capabilities.py tests/host/test_task_capability.py tests/host/test_subagent_capability.py tests/contract/test_todo_tool_metadata.py -q
# 28 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py -q
# 267 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_automation_capability.py tests/host/test_task_capability.py tests/host/test_subagent_capability.py tests/host/test_mcp_capability.py tests/host/test_lsp_capability.py tests/host/test_runtime_services.py -q
# 29 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py -q
# 272 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_memory_capability.py tests/memory tests/evolution tests/test_session_activity_integration.py -q
# 147 passed, 3 skipped

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py -q
# 278 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_evolution_capability.py tests/evolution tests/test_session_activity_integration.py -q
# 58 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_goal_capability.py tests/host/test_evolution_capability.py tests/goal tests/evolution tests/test_session_activity_integration.py -q
# 104 passed, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py -q
# 282 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_mcp_capability.py tests/host/test_task_capability.py tests/host/test_engine_wiring_capabilities.py tests/host/test_runtime_services.py -q
# 27 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py -q
# 287 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_engine_wiring_capabilities.py tests/test_session_activity_integration.py -q
# 18 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py -q
# 289 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_mcp_capability.py tests/test_mcp_engine_integration.py tests/host/test_runtime_services.py -q
# 30 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py tests/test_mcp_engine_integration.py -q
# 305 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/workflow tests/contract/test_workflow_progress_sse.py tests/app_server/test_workflow_cancel_finalize.py tests/host/test_engine_wiring_capabilities.py -q
# 34 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/workflow tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py tests/test_mcp_engine_integration.py -q
# 328 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_rlm_capability.py tests/test_rlm_subagent_task_parity.py tests/test_rlm_subagent_task_integration.py tests/host/test_evolution_capability.py tests/evolution -q
# 70 passed, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/workflow tests/engine/test_turn_evidence_sync.py tests/test_rlm_subagent_task_parity.py tests/test_rlm_subagent_task_integration.py tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py tests/test_mcp_engine_integration.py -q
# 351 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_goal_capability.py tests/goal/test_goal_thread_manager.py tests/contract/test_goal_status_sse.py tests/host/test_mcp_capability.py tests/test_mcp_preload.py -q
# 32 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/workflow tests/engine/test_turn_evidence_sync.py tests/test_rlm_subagent_task_parity.py tests/test_rlm_subagent_task_integration.py tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/contract/test_goal_status_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py tests/test_mcp_engine_integration.py tests/test_mcp_preload.py -q
# 368 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_memory_capability.py tests/host/test_evolution_capability.py tests/evolution/test_main_tool_evidence.py tests/engine/test_turn_evidence_sync.py -q
# 23 passed, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/workflow tests/engine/test_turn_evidence_sync.py tests/test_rlm_subagent_task_parity.py tests/test_rlm_subagent_task_integration.py tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/contract/test_goal_status_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py tests/test_mcp_engine_integration.py tests/test_mcp_preload.py -q
# 370 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_engine_wiring_capabilities.py tests/host/test_memory_capability.py tests/host/test_evolution_capability.py tests/evolution/test_main_tool_evidence.py tests/engine/test_turn_evidence_sync.py -q
# 34 passed, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/workflow tests/engine/test_turn_evidence_sync.py tests/test_rlm_subagent_task_parity.py tests/test_rlm_subagent_task_integration.py tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/contract/test_goal_status_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py tests/test_mcp_engine_integration.py tests/test_mcp_preload.py -q
# 372 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_goal_capability.py tests/goal/test_goal_thread_manager.py tests/contract/test_goal_status_sse.py tests/host/test_mcp_capability.py tests/test_mcp_preload.py -q
# 34 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/workflow tests/engine/test_turn_evidence_sync.py tests/test_rlm_subagent_task_parity.py tests/test_rlm_subagent_task_integration.py tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/contract/test_goal_status_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py tests/test_mcp_engine_integration.py tests/test_mcp_preload.py -q
# 374 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_contributions.py tests/host/test_lifecycle_and_surfaces.py tests/host/test_services.py tests/host/test_registry_assembly.py -q
# 17 passed

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/workflow tests/engine/test_turn_evidence_sync.py tests/test_rlm_subagent_task_parity.py tests/test_rlm_subagent_task_integration.py tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/contract/test_goal_status_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py tests/test_mcp_engine_integration.py tests/test_mcp_preload.py -q
# 383 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_memory_capability.py tests/host/test_lifecycle_and_surfaces.py tests/engine/test_turn_evidence_sync.py tests/memory -q
# 103 passed, 3 skipped

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/workflow tests/engine/test_turn_evidence_sync.py tests/test_rlm_subagent_task_parity.py tests/test_rlm_subagent_task_integration.py tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/contract/test_goal_status_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py tests/test_mcp_engine_integration.py tests/test_mcp_preload.py -q
# 384 passed, 3 skipped, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host/test_engine_wiring_capabilities.py tests/host/test_evolution_capability.py tests/evolution/test_pipeline_review_buffer.py tests/evolution/test_evolution_scheduler.py -q
# 24 passed, 1 warning

PYTHONPATH=src uv run --with pytest --with pytest-asyncio --with pyyaml --index-url https://pypi.tuna.tsinghua.edu.cn/simple pytest tests/host tests/goal tests/memory tests/evolution tests/workflow tests/engine/test_turn_evidence_sync.py tests/test_rlm_subagent_task_parity.py tests/test_rlm_subagent_task_integration.py tests/test_automation_manager.py tests/test_session_activity_integration.py tests/app_server/test_workflow_cancel_finalize.py tests/contract/test_workflow_progress_sse.py tests/contract/test_goal_status_sse.py tests/post_turn/test_orchestrator.py tests/contract/test_todo_tool_metadata.py tests/parity/phase_d/test_mcp_hooks_p1.py tests/test_mcp_engine_integration.py tests/test_mcp_preload.py -q
# 385 passed, 3 skipped, 1 warning
```

Previously Blocked:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/host -q
# No module named pytest

PYTHONPATH=src uv run pytest tests/host -q
# Failed to spawn: pytest

PYTHONPATH=src uv run --extra dev pytest tests/host -q
# Failed to download nodeenv from configured package index

PYTHONPATH=src .venv/bin/python -m ruff check src/deepseek_tui/host src/deepseek_tui/tools/context.py src/deepseek_tui/tools/runtime.py tests/host
# No module named ruff
```

The workaround is to use `uv run --with ... --index-url
https://pypi.tuna.tsinghua.edu.cn/simple` with full network access, avoiding
the full `dev` extra that pulls `pre-commit -> nodeenv`.

## Next Safe Step

Continue by wiring the next low-risk observer under the legacy path, likely Goal
turn lifecycle observer. Do not move event protocols or broad API surfaces until
behavior-equivalence tests are stronger.
