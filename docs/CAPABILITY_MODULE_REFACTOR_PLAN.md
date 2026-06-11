# Capability Module Refactor Plan

> Goal: reduce integration coupling without changing current behavior.
>
> This plan deliberately uses the term **capability module** instead of
> unrestricted Python plugin. First-party modules are assembled at process or
> session startup from typed contributions. External extensions continue to use
> MCP, Skills, and Hooks until the internal module API is stable.

## 1. Non-negotiable constraints

1. Existing user-visible behavior must remain unchanged during the refactor.
2. Existing public construction entry points remain available:
   - `Engine.create(...)`
   - `create_tool_runtime(...)`
   - `build_default_registry(...)`
3. Existing tool names, schemas, descriptions, approval requirements, and
   ordering in the serialized model catalog remain unchanged.
4. Existing prompt text and prompt fragment ordering remain unchanged.
5. Existing Engine events, SSE payloads, API routes, persistence formats, and
   Workbench rendering remain unchanged until a later explicitly versioned
   migration.
6. Existing config fields and defaults remain unchanged.
7. Capability modules do not receive the complete `Engine` object.
8. No active-session hot unload in this refactor. Configuration changes apply
   to newly created sessions or after a controlled runtime restart.

The refactor succeeds only when a capability can be added or removed from the
composition root without adding feature-specific branches to `Engine`.

## 2. What "plugin compatibility" means in this system

A capability module is not an object that is allowed to mutate arbitrary
Engine internals. It is a descriptor that contributes typed pieces to the
existing host.

At startup:

```text
Config
  -> BuiltinModuleCatalog selects enabled modules
  -> ModuleAssembler resolves dependencies and ordering
  -> each module contributes typed parts
  -> assembled parts create the existing Engine / ToolRuntime / API surfaces
```

A module may contribute:

```text
tools             ToolSpec instances exposed to the model
services          long-lived typed runtime services
prompt fragments  stable or volatile system-prompt content
turn observers    work at explicit turn lifecycle points
tool observers    work around successful/failed tool execution
post-turn pipes   capture/review/flush work using TurnEvidence
runtime surfaces  optional API routes and event presenters
```

The host owns execution order, error policy, shutdown order, approval, and
sandboxing. Modules supply behavior but cannot bypass those host invariants.

### 2.1 Compatibility with the current system

The new assembler initially builds the same objects currently built manually:

```text
MemoryModule
  -> creates the same MemoryCoordinator
  -> registers the same memory tools
  -> contributes the same recall data to the same prompt positions
  -> registers the same MemoryPipeline in PostTurnOrchestrator

EvolutionModule
  -> creates the same EvolutionPipeline and stores
  -> registers the same tools and metadata/service bindings
  -> contributes the same stable and volatile prompt content
  -> emits the same EvolutionProposalEvent

LspModule
  -> creates the same LspManager
  -> invokes the existing edited_paths_for_tool / diagnostics_for logic
  -> injects the same rendered DiagnosticBlock user message
```

No capability implementation is rewritten during its first migration. Only
construction and invocation ownership move.

### 2.2 First-party modules versus external plugins

For this refactor:

- First-party capability modules are imported from a fixed built-in catalog.
- MCP remains the external tool integration protocol.
- Skills remain the external prompt/instruction integration mechanism.
- Hooks remain the external lifecycle automation mechanism.
- Arbitrary third-party Python package loading is explicitly deferred.

This avoids introducing package compatibility, trust, crash isolation, and
upgrade problems before the internal API has proven stable.

## 3. Target architecture

```text
deepseek_tui/
├── host/
│   ├── assembler.py          # single composition root
│   ├── module.py             # module and contribution protocols
│   ├── catalog.py            # fixed first-party module catalog
│   ├── services.py           # typed service registry
│   ├── prompt.py             # ordered prompt contributors
│   ├── lifecycle.py          # typed turn/tool observer registries
│   └── surfaces.py           # optional runtime API/event surface registry
├── capabilities/
│   ├── core_tools.py
│   ├── memory.py
│   ├── evolution.py
│   ├── lsp.py
│   ├── goal.py
│   ├── subagents.py
│   ├── workflow.py
│   ├── tasks.py
│   ├── automation.py
│   ├── mcp.py
│   ├── web.py
│   └── rlm.py
├── engine/                   # host-owned agent kernel
├── tools/                    # tool implementations, not global assembly
├── post_turn/                # retained typed post-turn extension point
└── app_server/
```

Existing domain implementation directories remain in place. For example,
`memory/` continues to own memory implementation. `capabilities/memory.py`
only adapts that implementation to the host.

## 4. Core interfaces

The exact names may change during implementation, but the responsibilities and
direction of dependency must remain.

### 4.1 Typed service registry

Replace new uses of `ToolContext.metadata` for long-lived dependencies with a
typed registry. Existing metadata keys remain populated during migration.

```python
T = TypeVar("T")


class ServiceRegistry:
    def add(self, key: type[T], value: T, *, owner: str) -> None: ...
    def require(self, key: type[T]) -> T: ...
    def optional(self, key: type[T]) -> T | None: ...
    def add_named(self, key: str, value: object, *, owner: str) -> None: ...
    async def shutdown(self) -> None: ...
```

Rules:

- Duplicate typed service registration fails during assembly.
- Services record their owning module.
- Shutdown runs in reverse successful-start order.
- `add_named` exists only for temporary compatibility with current constants.
- Tools use typed services after their module migration.

`ToolContext` gains:

```python
services: ServiceRegistry
```

Its existing fields and `metadata` remain until all current consumers migrate.

### 4.2 Capability module

```python
@dataclass(frozen=True, slots=True)
class ModuleDescriptor:
    id: str
    enabled: Callable[[Config], bool]
    requires: tuple[str, ...] = ()
    after: tuple[str, ...] = ()


class CapabilityModule(Protocol):
    descriptor: ModuleDescriptor

    def contribute(self, contributions: "Contributions") -> None: ...
```

`contribute()` describes factories and adapters. It must not start background
tasks or perform workspace I/O. Startup happens later under host control.

### 4.3 Contributions

```python
class Contributions:
    tools: ToolPackRegistry
    services: RuntimeServiceRegistry
    prompts: PromptContributorRegistry
    turn_observers: TurnObserverRegistry
    tool_observers: ToolObserverRegistry
    post_turn: PostTurnPipelineRegistry
    surfaces: RuntimeSurfaceRegistry
```

Each contribution records:

- owner module id
- explicit order or phase
- required services
- failure policy

The assembler validates dependencies before constructing Engine.

### 4.4 Runtime services

```python
class RuntimeService(Protocol):
    async def start(self, ctx: RuntimeStartContext) -> None: ...
    async def stop(self) -> None: ...
```

Examples:

- `TaskManagerService`
- `SubAgentService`
- `McpService`
- `LspService`
- `AutomationService`
- `MemoryService`

Services are the correct integration mechanism for stateful managers and
background tasks. They are not generic Engine hooks.

### 4.5 Prompt contributors

Prompt contributors return text and declare their exact existing location.

```python
class PromptSlot(str, Enum):
    AFTER_PROJECT_CONTEXT = "after_project_context"
    AFTER_ENVIRONMENT = "after_environment"
    BEFORE_COMPACTION_GUIDANCE = "before_compaction_guidance"
    VOLATILE_BEFORE_USER_MEMORY = "volatile_before_user_memory"
    VOLATILE_AFTER_USER_MEMORY = "volatile_after_user_memory"


class PromptContributor(Protocol):
    id: str
    slot: PromptSlot
    order: int
    async def render(self, ctx: PromptContext) -> str | None: ...
```

Prompt slots preserve prefix-cache behavior. A module cannot silently move
volatile text into the stable prefix.

Initial mapping:

| Current prompt input | Contributor |
|---|---|
| skills context | `SkillsPromptContributor` |
| smart-memory recall system block | `MemoryRecallPromptContributor` |
| `memory.md` | `UserMemoryPromptContributor` |
| curated snapshot | `EvolutionStablePromptContributor` |
| volatile evolution lines | `EvolutionVolatilePromptContributor` |
| workflow guidelines | `WorkflowPromptContributor` |
| working set | core contributor |

During migration, golden prompt tests must prove byte-for-byte equality for
the same workspace and inputs.

### 4.6 Turn lifecycle observers

Use explicit phases rather than an unrestricted event bus:

```python
class BeforeUserTurnObserver(Protocol):
    async def before_user_turn(self, ctx: BeforeUserTurnContext) -> None: ...


class TurnCompletionObserver(Protocol):
    async def on_turn_completed(self, ctx: CompletedTurnContext) -> None: ...


class TurnFailureObserver(Protocol):
    async def on_turn_failed(self, ctx: FailedTurnContext) -> None: ...
```

Contexts expose only required operations, such as:

- current thread/session identity
- workspace
- user input
- mutable next-turn message decorations where explicitly allowed
- usage and outcome
- host `emit()` and `steer()` capabilities

They do not expose the Engine object.

Initial mapping:

| Existing behavior | New owner |
|---|---|
| memory recall before user message | Memory before-turn observer |
| goal `on_turn_start/complete/failed` | Goal lifecycle observer |
| session activity polling | SubAgent/Task activity service |

### 4.7 Tool observers

Tool observers are called by the existing host-owned dispatch path, after
approval and sandbox decisions.

```python
class ToolObserver(Protocol):
    async def before_tool(self, ctx: BeforeToolContext) -> None: ...
    async def after_tool(self, ctx: AfterToolContext) -> None: ...
```

Host invariants:

- Observers cannot execute an unapproved tool.
- Approval and sandbox remain in core dispatch.
- Observer failure policy is explicit.
- Tool result mutation is not allowed initially.

Initial mapping:

| Existing behavior | Observer |
|---|---|
| pre-edit snapshot for undo | core `SnapshotToolObserver` |
| lifecycle shell hooks | `LifecycleHookToolObserver` |
| LSP post-edit diagnostics | `LspToolObserver` |
| evolution `on_main_tool_called` | `EvolutionToolObserver` |

### 4.8 Post-turn pipelines

Keep `PostTurnPipeline`, `TurnEvidence`, and `PostTurnOrchestrator`.

Required improvements:

- move `TurnEvidence` ownership to a neutral host contract package if needed
- register pipelines through `PostTurnPipelineRegistry`
- keep current in-order execution, timeout, error isolation, and flush behavior
- remove direct Engine knowledge of concrete Memory/Evolution pipelines

The current post-turn implementation is already close to the target boundary.

### 4.9 Runtime surfaces and events

Do not genericize current events during the first migrations. Preserve:

- `WorkflowProgressEvent`
- `EvolutionProposalEvent`
- goal status SSE
- existing API route paths
- current Workbench payloads

First-party modules initially register adapters that route to the same current
handlers. Only after behavior parity is complete should a versioned
`ExtensionEvent` or generic surface API be considered.

## 5. Single composition root

Add `host/assembler.py` as the only place that decides which capabilities are
enabled and how their dependencies are connected.

```python
@dataclass(slots=True)
class AssembledRuntime:
    services: ServiceRegistry
    registry: ToolRegistry
    tool_context: ToolContext
    prompt_contributors: PromptContributorRegistry
    lifecycle: LifecycleRegistries
    post_turn: PostTurnOrchestrator | None
    surfaces: RuntimeSurfaceRegistry


async def assemble_runtime(request: AssemblyRequest) -> AssembledRuntime:
    modules = builtin_catalog.enabled_for(request.config)
    ordered = resolve_module_order(modules)
    contributions = collect_and_validate(ordered)
    services = await start_services(contributions, request)
    return materialize_runtime(contributions, services, request)
```

Compatibility wrappers:

```python
async def create_tool_runtime(...):
    return LegacyToolRuntimeAdapter(await assemble_runtime(...))


def build_default_registry(config=None, mode="agent"):
    return assemble_registry_only(config or Config(), mode)


class Engine:
    @classmethod
    async def create(...):
        assembled = await assemble_runtime(...)
        return cls(..., assembled_runtime=assembled)
```

The wrappers remain until all call sites and tests are intentionally migrated.

## 6. Built-in capability mapping

### 6.1 Core kernel, never optional through modules

- Turn Loop and streaming
- message/session state
- tool dispatcher
- approval cache and approval flow
- ExecPolicy and Sandbox
- cancellation, timeout, retry, error flow
- compaction, capacity, working set
- core events and base Runtime API
- core file/read/write/search/shell tool execution semantics

Core tools may use a `CoreToolPack` for assembly cleanliness, but it is always
enabled and is not externally replaceable.

### 6.2 MemoryModule

Enabled using the current `memory_enabled()` and `smart_memory_enabled()`
semantics.

Contributes:

- `MemoryCoordinator` / provider service
- `RememberTool`, `RecallArchiveTool`, `MemorySearchTool`,
  `ConversationSearchTool`
- memory recall before-turn observer
- user-memory and recall prompt contributors
- `MemoryPipeline`
- existing compatibility metadata keys

Must preserve:

- trivial prompt recall skipping
- `memory_thread_id` resolution
- `memory_mode`
- recall injection position
- capture gates
- compaction/LRU/session-shutdown flush
- on-disk formats

### 6.3 EvolutionModule

Enabled using current `cfg.evolution.enabled`.

Contributes:

- existing EvolutionPipeline and stores
- `MemoryCurateTool` and `SkillManageTool`
- stable/volatile prompt contributors
- post-turn pipeline
- main-tool observer
- same proposal event and existing API route adapter
- compatibility bindings for current store/ledger keys

Must preserve:

- review scheduling and buffers
- tool-round accounting
- flush thresholds
- policy behavior
- ledger and audit formats
- current Workbench approval flow

### 6.4 LspModule

Enabled using current `cfg.lsp.enabled`.

Contributes:

- existing `LspManager` service
- post-edit tool observer
- before-request diagnostic message decorator

Must preserve:

- edited tool/path detection
- silent failures
- diagnostic ordering and rendering
- diagnostics arriving on the next model request
- shutdown of all servers

### 6.5 GoalModule

Goal is a mode capability, not a universal core invariant.

Contributes:

- `GoalController` scoped to thread/session
- goal tools
- goal turn lifecycle observer
- goal follow-up scheduler adapter
- goal status surface adapter

Initially keep Goal enabled by default to preserve the current always-present
controller and tools. Optional enablement can be a separate product decision
after parity.

Must preserve:

- hidden follow-up behavior
- stale follow-up rejection
- accounting and budgets
- thread journal paths
- follow-up scheduling differences between TUI and Workbench
- current goal SSE payload

### 6.6 SubAgentModule and WorkflowModule

`SubAgentModule` contributes:

- SubAgentManager and Mailbox service
- subagent tools
- activity service
- parent completion sink wiring

`WorkflowModule` requires `subagents` and contributes:

- existing WorkflowTool
- workflow prompt contributor
- existing progress event adapter

Must preserve:

- current tool names and legacy aliases
- spawn-depth behavior
- cancellation
- approvals
- parent completion handoff
- workflow progress payloads

### 6.7 TaskModule and AutomationModule

`TaskModule` contributes TaskManager and task tools.

`AutomationModule` requires `tasks` and contributes:

- AutomationManager service
- scheduler service
- automation tools
- existing automation API routes

Keep checklist tools separate from durable tasks. They may share a UI label but
not a persistence or execution model.

### 6.8 McpModule

MCP remains host extension infrastructure.

Contributes:

- McpManager service
- bridge tools
- dynamic model tool catalog provider
- existing API routes

The core dispatcher continues to own approval of dynamically discovered MCP
tools. MCP tools must not bypass core approval or sandbox policy.

## 7. Behavior-equivalence strategy

Refactoring starts by freezing current behavior in characterization tests.

### 7.1 Golden tool-catalog tests

For representative config/mode combinations, snapshot:

- registry tool names in insertion order
- serialized API tool names in sorted order
- full serialized tool schemas and descriptions
- capabilities and approval requirements

Required matrices:

```text
agent default
plan default
all optional features disabled
tasks enabled
subagents + workflow enabled
automations + tasks enabled
memory enabled
smart memory enabled
evolution enabled
MCP bridge enabled
```

The old and new assembly paths must produce identical snapshots.

### 7.2 Golden prompt tests

For fixed workspace fixtures, compare exact prompt strings for:

- default agent
- plan, goal, and workflow modes
- skills enabled
- memory.md enabled
- memory recall in user position
- memory recall in system-volatile position
- evolution stable and volatile content
- workflow guidelines
- working set and compaction summary

Prompt equality must be byte-for-byte, including ordering and blank lines.

### 7.3 Engine event-trace tests

Using a deterministic fake client, record event class and normalized payload
sequence for:

- text-only turn
- one read tool
- approved write tool
- denied shell tool
- parallel tools
- request-user-input
- workflow progress
- goal follow-up
- cancelled turn
- failed turn

Run the same scenario through legacy and new assembly paths and compare traces.

### 7.4 Lifecycle-order tests

Record invocation order for:

```text
service start
before user turn
prompt contributors
turn start
before tool
tool execution
after tool
turn complete/failure
post-turn pipelines
flush before compaction/loss
reverse service stop
```

This prevents plugins from changing behavior through accidental reordering.

### 7.5 Persistence and contract tests

Verify unchanged:

- memory databases and JSONL
- goal journals
- task/subagent state
- evolution ledger/audit
- runtime thread/turn/item records
- all existing `/v1` endpoints
- all current SSE payload shapes
- Workbench TypeScript tests

## 8. Phased implementation plan

Each phase is independently mergeable and must leave all existing behavior
available through current public entry points.

### Phase 0: Freeze current behavior

Implementation:

1. Add tool-catalog snapshot/characterization tests.
2. Add prompt golden tests.
3. Add deterministic event-trace tests.
4. Add lifecycle and shutdown-order characterization tests.
5. Add missing direct LSP integration tests.
6. Record current config-default snapshots.

Files:

- add `tests/architecture/`
- add fixtures under `tests/fixtures/architecture/`
- no production behavior changes

Completion criteria:

- behavior snapshots are reviewed and intentional
- existing tests still pass
- tests fail when tool names, prompt ordering, event order, or shutdown order is
  intentionally perturbed

Test gate:

```bash
make check
pytest tests/architecture -q
pytest tests/contract -q
```

### Phase 1: Add host foundation with zero migrated capabilities

Implementation:

1. Add `host/services.py`, `host/module.py`, `host/catalog.py`.
2. Add contribution registries.
3. Add dependency/order validation.
4. Add service startup rollback and reverse shutdown.
5. Add empty built-in catalog.
6. Add `ServiceRegistry` to `ToolContext` while retaining `metadata`.

No Engine logic is moved in this phase.

Completion criteria:

- empty module assembly starts and stops deterministically
- duplicate services and missing dependencies fail before Engine starts
- failed service startup rolls back already-started services
- existing Engine construction behavior is unchanged

Tests:

- module ordering
- dependency cycle detection
- duplicate contribution rejection
- failed startup rollback
- reverse shutdown order
- ToolContext metadata compatibility
- full existing suite

### Phase 2: Unify assembly behind compatibility wrappers

Implementation:

1. Add `host/assembler.py`.
2. Move current construction sequencing into assembler adapters without
   changing feature ownership.
3. Make `Engine.create()` call assembler.
4. Make `create_tool_runtime()` call assembler or a shared lower-level path.
5. Make `build_default_registry()` call registry-only assembly.
6. Preserve returned `ToolRuntime` fields through a compatibility adapter.

Important: do not migrate Memory/Evolution/LSP logic yet. This phase only
creates one composition root.

Completion criteria:

- only assembler decides the startup sequence
- old public entry points return behavior-equivalent objects
- shared runtime behavior remains unchanged
- no tool, prompt, event, API, or persistence diff

Tests:

- legacy-versus-assembler tool catalog equality
- Engine.create fixture suite
- shared ToolRuntime workspace behavior
- manager ownership/shutdown behavior
- complete contract suite

### Phase 3: Migrate tool registration into ToolPacks

Implementation:

1. Split `build_default_registry()` registration blocks into first-party
   ToolPacks.
2. Preserve exact current registration order.
3. Keep `build_default_registry()` as a wrapper.
4. Keep tool implementations in current files.

Suggested packs:

```text
CoreReadToolPack
CoreWriteToolPack
ShellToolPack
GitToolPack
GitHubToolPack
KnowledgeToolPack
ValidationToolPack
TaskToolPack
SubAgentToolPack
AutomationToolPack
MemoryToolPack
EvolutionToolPack
McpBridgeToolPack
```

Completion criteria:

- `tools/builder.py` no longer imports every concrete tool
- serialized catalog is identical for every Phase 0 matrix
- plan-mode filtering is identical
- legacy aliases remain unchanged

Tests:

- full tool-catalog golden matrix
- approval requirement snapshots
- subagent registry allowlist/extra-tools tests
- tool profile tests
- full existing suite

### Phase 4: Migrate runtime services

Order:

1. LSP service
2. Task service
3. SubAgent service
4. MCP service
5. Automation service

Implementation:

- each service factory moves out of `create_tool_runtime()`
- assembler resolves dependencies
- compatibility fields on `ToolRuntime` remain populated
- compatibility metadata keys remain populated
- services own their shutdown

Completion criteria:

- `create_tool_runtime()` contains no feature-specific construction branches
- Automation dependency on Tasks is declared, not manually checked in runtime
- startup failure and shutdown behavior remain unchanged

Tests:

- feature-on/off matrix
- Automation-without-Tasks rejection message
- shared Task/MCP manager ownership
- background scheduler shutdown
- SubAgent loop-runtime attachment
- LSP shutdown
- MCP preload/discovery

### Phase 5: Migrate Prompt Contributors

Implementation:

1. Introduce prompt slots matching current prompt order.
2. Convert Skills, Workflow, Memory, and Evolution prompt inputs into
   contributors one at a time.
3. Keep core project context, environment, compaction guidance, and working set
   host-owned initially.
4. Preserve current `build_system_prompt()` signature as a compatibility
   adapter until call sites migrate.

Completion criteria:

- Engine no longer imports Memory/Evolution/Workflow prompt implementation
- exact prompt golden tests pass
- stable and volatile boundaries remain unchanged

Tests:

- all Phase 0 prompt goldens
- prefix-stability test
- disabled module contributes no text
- deterministic same-slot ordering

### Phase 6: Migrate LSP and Evolution observers

Implementation:

1. Move post-edit LSP invocation to `LspToolObserver`.
2. Move pending-diagnostic injection to a before-request decorator.
3. Move Evolution `on_main_tool_called` to `EvolutionToolObserver`.
4. Register existing EvolutionPipeline through post-turn registry.
5. Keep existing events and routes.

Completion criteria:

- Engine contains no direct LSP imports or Evolution concrete type checks
- LSP and Evolution behavior is unchanged
- observer ordering is explicit and tested

Tests:

- edits produce identical next-request diagnostics
- LSP failure remains silent
- Evolution tool-round counters/reset behavior
- Evolution review/flush tests
- contract tests for evolution proposals

### Phase 7: Migrate MemoryModule

Implementation:

1. Memory service owns provider/coordinator startup and shutdown.
2. Before-turn observer performs current recall.
3. A typed turn decoration carries recall results into user-message and prompt
   construction.
4. MemoryPipeline remains the capture/flush path.
5. Thread/session binding moves to a narrow session-binding adapter.
6. Preserve current metadata keys and Engine compatibility properties during
   migration.

Completion criteria:

- Engine no longer constructs or type-checks MemoryCoordinator
- no duplicate fallback capture path remains
- thread LRU eviction, compaction, shutdown, and TUI persistence all flush
  through the same post-turn host contract
- all memory acceptance behavior is unchanged

Tests:

- all `tests/memory`
- memory wiring on/off
- recall position equality
- trivial recall skip
- capture gates
- compaction flush
- LRU eviction flush
- provider restart recall
- contract memory tests

### Phase 8: Migrate GoalModule

Implementation:

1. Goal service owns GoalController.
2. Goal lifecycle observer handles start/complete/failure/accounting.
3. Goal follow-up scheduler uses a narrow host command interface.
4. RuntimeThreadManager accesses a typed Goal service adapter.
5. Keep existing goal tools, journal format, events, and SSE.

Completion criteria:

- Engine has no concrete GoalController construction or lifecycle calls
- RuntimeThreadManager does not use `getattr(engine, "goal_controller")`
- hidden/stale follow-up behavior remains identical

Tests:

- all `tests/goal`
- goal mode turn traces
- hidden message persistence
- token budget accounting
- thread binding/forking
- goal SSE contract
- Workflow/Goal coexistence

### Phase 9: Migrate SubAgent, Workflow, Task, and Automation modules

Implementation:

- replace remaining Engine/Runtime feature branches with service lookups and
  registered observers/surfaces
- preserve special dispatch behavior until a dedicated typed tool-execution
  context replaces workflow/RLM metadata callbacks
- move API route inclusion behind enabled surface contributions only after
  contract parity is proven

Completion criteria:

- capabilities can be disabled without constructing their managers
- enabled capabilities expose the same tools, events, routes, and UI behavior
- core Engine does not import these feature implementation packages

Tests:

- subagent activity and handoff
- workflow cancellation/progress/contracts
- task execution and persistence
- automation scheduler/API/contracts
- Workbench tests and smoke

### Phase 10: Remove compatibility debt

Only after all previous phases are green:

1. Remove migrated long-lived services from `ToolContext.metadata`.
2. Remove Engine compatibility properties after all call sites migrate.
3. Remove duplicate assembly paths.
4. Split CLI independently.
5. Consider a versioned generic extension event/surface protocol.
6. Evaluate external Python plugin loading as a separate project.

Completion criteria:

- no feature-specific imports in Engine except stable host contracts
- no feature-specific construction in ToolRuntime or tool builder
- adding a first-party capability changes only its module adapter, tests, and
  optional UI renderer

## 9. Required compatibility tests per migrated module

Every module migration must include:

1. **Disabled parity:** same behavior as current config-disabled state.
2. **Enabled parity:** same tool catalog and startup state.
3. **Lifecycle parity:** same invocation order and shutdown.
4. **Prompt parity:** same text and position, when applicable.
5. **Event parity:** same Engine events and normalized payload sequence.
6. **Persistence parity:** same files/database records.
7. **Surface parity:** same API/SSE/Workbench behavior, when applicable.
8. **Failure parity:** same best-effort versus fatal behavior.

No module migration should combine behavioral improvements. Discovered bugs are
recorded separately and fixed before or after the migration in isolated commits.

## 10. Merge and rollback policy

Each phase should be a separate merge unit.

Recommended commit sequence inside a module migration:

```text
1. test: characterize current <module> behavior
2. refactor: add <module> adapter behind legacy path
3. refactor: switch assembler to <module> adapter
4. refactor: remove old duplicate wiring
```

During the transition, a temporary internal feature flag may select legacy or
assembled wiring in tests. It must not become a user-facing permanent setting.

Rollback is accomplished by switching the assembler back to the legacy adapter,
not by reverting unrelated capability migrations.

## 11. Global verification gate

Run after every phase:

```bash
make lint
make typecheck
make test
pytest tests/architecture -q
pytest tests/contract -q
```

Run before completing a major module migration:

```bash
pytest tests/memory tests/evolution tests/post_turn -q
pytest tests/goal tests/workflow -q
pytest tests/test_mcp_engine_integration.py -q
pytest tests/test_session_activity_integration.py -q
pytest tests/test_tui_smoke.py -q
```

Workbench gate:

```bash
cd packages/workbench
npm test
npm run typecheck
```

Manual smoke gate:

```text
1. start TUI and complete a text-only turn
2. execute read, edit, shell approval, and cancellation flows
3. start Workbench and verify text/tool/SSE rendering
4. enable smart memory and verify recall + capture
5. enable evolution and verify proposal flow
6. run a workflow and verify progress rendering
7. create a goal and verify hidden continuation
8. shut down with active background services and verify clean exit
```

Live API tests remain opt-in and are not required for every small phase, but
must run before declaring the complete refactor finished.

## 12. Definition of done for the complete refactor

The complete refactor is done when:

- `Engine` owns the agent loop and core invariants, not feature construction.
- `Engine.create()`, `create_tool_runtime()`, and `build_default_registry()`
  delegate to one composition root.
- Memory, Evolution, LSP, Goal, Workflow, SubAgents, Tasks, Automation, and MCP
  are represented as first-party capability modules.
- Feature implementations do not receive the full Engine object.
- Long-lived feature dependencies use typed services.
- Prompt contributions use explicit ordered slots.
- Post-turn pipelines remain ordered, isolated, and flushable.
- Current configs, tools, prompts, events, routes, persistence, TUI, and
  Workbench behavior remain compatible.
- All automated gates pass.
- Manual smoke and selected live API tests pass.

