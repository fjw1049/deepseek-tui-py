"""Tool registry — base types, context, registry, and builder.

Consolidates base.py, context.py, registry.py, builder.py.
"""

from __future__ import annotations



from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any



class ToolCapability(str, Enum):
    """Capabilities a tool may have or require.

    Mirrors Rust's `tools/spec.rs::ToolCapability`.
    """

    READ_ONLY = "read_only"
    WRITES_FILES = "writes_files"
    EXECUTES_CODE = "executes_code"
    NETWORK = "network"
    SANDBOXABLE = "sandboxable"
    REQUIRES_APPROVAL = "requires_approval"


class ApprovalRequirement(str, Enum):
    """Approval requirement for a tool.

    Mirrors Rust's `tools/spec.rs::ApprovalRequirement`.

    * AUTO: never needs approval (safe, read-only operations)
    * SUGGEST: hint that the user should approve, but allow skipping
    * REQUIRED: always require explicit user approval
    """

    AUTO = "auto"
    SUGGEST = "suggest"
    REQUIRED = "required"


class ToolError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class ToolResult:
    success: bool
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolSpec(ABC):
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def description(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> list[ToolCapability]:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        raise NotImplementedError

    # --- Optional metadata with sensible defaults --------------------

    def approval_requirement(self) -> ApprovalRequirement:
        """Return whether this tool needs user approval before running.

        Mirrors Rust ``ToolSpec::approval_requirement`` default in ``spec.rs``.
        """
        caps = self.capabilities()
        if ToolCapability.EXECUTES_CODE in caps:
            return ApprovalRequirement.REQUIRED
        if ToolCapability.WRITES_FILES in caps:
            return ApprovalRequirement.SUGGEST
        if ToolCapability.REQUIRES_APPROVAL in caps:
            return ApprovalRequirement.REQUIRED
        return ApprovalRequirement.AUTO

    def defer_loading(self) -> bool:
        """Whether the model should defer loading the tool's full schema.

        Default ``False``. Mirrors Rust `ToolSpec::defer_loading`.
        """
        return False

    def is_read_only(self) -> bool:
        """True iff the tool's capabilities include READ_ONLY.

        Mirrors Rust `ToolSpec::is_read_only` (default impl).
        """
        return ToolCapability.READ_ONLY in self.capabilities()

    def supports_parallel(self) -> bool:
        return True


from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deepseek_tui.policy.exec_policy import Policy
    from deepseek_tui.policy.sandbox import ExecutionSandboxPolicy
    from deepseek_tui.policy.network import NetworkPolicyDecider
    from deepseek_tui.tools.subagent import SubAgentManager
    from deepseek_tui.tools.task import TaskManager


@dataclass(slots=True)
class ToolContext:
    working_directory: Path
    timeout_ms: int | None = None
    trust_mode: bool = False
    active_task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    policy: Policy | None = None
    task_manager: TaskManager | None = None
    subagent_manager: SubAgentManager | None = None
    network_policy: NetworkPolicyDecider | None = None
    execution_sandbox_policy: ExecutionSandboxPolicy | None = None
    elevated_sandbox_policy: ExecutionSandboxPolicy | None = None

    def resolve_path(self, path: str) -> Path:
        """Resolve ``path`` against the workspace, refusing escapes.

        Mirrors Rust ``PathEscape`` (tools/src/lib.rs:67-75): when the
        resolved path falls outside ``working_directory``, raise
        ``ValueError`` instead of silently rewriting it. The negative
        signal lets the LLM self-correct on the next turn — without it,
        absolute-path hallucinations (``/home/user/foo.py``) keep
        succeeding and the model never learns.

        ``trust_mode`` bypasses the check (used for system-initiated
        operations that must touch e.g. ``~/.deepseek``).
        """
        workspace = self.working_directory.expanduser().resolve()
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (workspace / candidate).resolve()
        if not self.trust_mode:
            try:
                resolved.relative_to(workspace)
            except ValueError as exc:
                raise ValueError(
                    f"path escapes workspace: {path!r} "
                    f"(workspace: {workspace}). Use a relative path."
                ) from exc
        return resolved


# Tool registry, mirroring `crates/tui/src/tools/registry.rs`.
#
# Two important Rust invariants the Python port preserves:
#
# 1. **Alphabetical sort in `to_api_tools()`** (Rust L144-149, GitHub
#    issue #263). DeepSeek's KV prefix cache only stays warm if the tool
#    array is byte-stable across launches. Python's ``dict`` preserves
#    insertion order, but cross-process registration order varies (env,
#    config, MCP discovery), so we sort by name on serialisation.
# 2. **Memoised serialised catalog** (Rust L151-156). Each tool's
#    ``description()`` and ``input_schema()`` is sampled exactly once per
#    registration. Some tools — notably MCP adapters whose upstream
#    description string drifts on reconnect — would otherwise rewrite
#    the catalog mid-session and bust the prefix cache.
#
# The wire format we emit is the standard OpenAI ``{type, function}``
# envelope, with two non-OpenAI Rust extension fields (``allowed_callers``
# and ``defer_loading``) tucked into the ``function`` object. Both fields
# are silently ignored by providers that don't recognise them.
#
import asyncio
import logging
from typing import Any


__all__ = ["ToolRegistry"]

_LOG = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, context: ToolContext | None = None) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._context: ToolContext | None = context
        self._api_cache: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # registration
    # ------------------------------------------------------------------

    def register(self, tool: ToolSpec) -> None:
        """Register a tool. Logs a warning if it overwrites an existing one.

        Mirrors Rust ``ToolRegistry::register`` (registry.rs:46-52).
        """
        name = tool.name()
        if name in self._tools:
            _LOG.warning("Overwriting existing tool: %s", name)
        self._tools[name] = tool
        self._invalidate_api_cache()

    def register_all(self, tools: list[ToolSpec]) -> None:
        """Register every tool in ``tools`` (Rust L55-59)."""
        for tool in tools:
            self.register(tool)

    def remove(self, name: str) -> ToolSpec | None:
        """Remove a tool by name; return the removed spec or ``None``.

        Mirrors Rust L264-271. Cache is only invalidated if a removal
        actually happened, matching the Rust early-return.
        """
        removed = self._tools.pop(name, None)
        if removed is not None:
            self._invalidate_api_cache()
        return removed

    def clear(self) -> None:
        """Remove every registered tool (Rust L274-278)."""
        self._tools.clear()
        self._invalidate_api_cache()

    def filter_by_names(self, allowed: set[str]) -> None:
        """Keep only tools whose names appear in *allowed*.

        Mirrors Rust SubAgent scope restriction (mod.rs:810-825).
        """
        to_remove = [n for n in self._tools if n not in allowed]
        if to_remove:
            for n in to_remove:
                del self._tools[n]
            self._invalidate_api_cache()

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolError(f"Tool not found: {name}") from exc

    def contains(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        """Return all registered tool names (insertion order, NOT sorted).

        Rust ``names()`` returns insertion-order; only ``to_api_tools``
        sorts. Keeping this asymmetric matches the Rust contract.
        """
        return list(self._tools)

    def all(self) -> list[ToolSpec]:
        return list(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def is_empty(self) -> bool:
        return not self._tools

    # ------------------------------------------------------------------
    # capability / approval filtering
    # ------------------------------------------------------------------

    def read_only_tools(self) -> list[ToolSpec]:
        """Mirrors Rust L214-219."""
        return [t for t in self._tools.values() if t.is_read_only()]

    def approval_required_tools(self) -> list[ToolSpec]:
        """Tools whose ``approval_requirement()`` is ``REQUIRED``.

        Mirrors Rust L225-231.
        """
        return [
            t
            for t in self._tools.values()
            if t.approval_requirement() == ApprovalRequirement.REQUIRED
        ]

    # ------------------------------------------------------------------
    # context
    # ------------------------------------------------------------------

    @property
    def context(self) -> ToolContext | None:
        return self._context

    def set_context(self, context: ToolContext) -> None:
        """Replace the registry's tool execution context (Rust L251)."""
        self._context = context

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        name: str,
        input_data: dict[str, Any],
        context: ToolContext,
    ) -> ToolResult:
        """Run a tool by name with ``context``. Returns the full result.

        Honours ``context.timeout_ms`` if set. Wraps lookup / timeout /
        ``ValueError`` into :class:`ToolError`.
        """
        tool = self.get(name)
        timeout_seconds = (
            context.timeout_ms / 1000 if context.timeout_ms is not None else None
        )
        try:
            if timeout_seconds is None:
                return await tool.execute(input_data, context)
            return await asyncio.wait_for(
                tool.execute(input_data, context),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise ToolError(f"Tool {name} timed out after {timeout_seconds}s") from exc
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    async def execute_full(
        self,
        name: str,
        input_data: dict[str, Any],
        context: ToolContext | None = None,
        context_override: ToolContext | None = None,
    ) -> ToolResult:
        """Rust-named alias for :meth:`execute`, with context override.

        Mirrors Rust ``execute_full_with_context`` (registry.rs:122-134).

        Resolution order for the actual context passed to the tool:

        1. ``context_override`` if provided (used when the engine retries
           with an elevated sandbox policy)
        2. ``context`` if provided
        3. ``self.context`` (the registry-level default)

        Raises :class:`ToolError` if no context is resolvable.
        """
        ctx = context_override or context or self._context
        if ctx is None:
            raise ToolError(
                "ToolRegistry.execute_full: no context available "
                "(pass context= or call set_context() first)"
            )
        return await self.execute(name, input_data, ctx)

    # ------------------------------------------------------------------
    # API serialisation
    # ------------------------------------------------------------------

    def to_api_tools(self) -> list[dict[str, Any]]:
        """Return the tool catalog in the OpenAI Chat Completions schema.

        The catalog is **sorted alphabetically by name** for DeepSeek
        prefix-cache stability (issue #263) and **memoised** so each
        tool's metadata is sampled exactly once per registration.

        Wire format::

            {
              "type": "function",
              "function": {
                "name": ...,
                "description": ...,
                "parameters": ...,
                "allowed_callers": ["direct"],   # Rust extension
                "defer_loading": false           # Rust extension
              }
            }

        ``allowed_callers`` and ``defer_loading`` are Rust extension
        fields preserved for behaviour parity; OpenAI / DeepSeek silently
        ignore unknown keys inside ``function``.
        """
        if self._api_cache is None:
            self._api_cache = [
                self._serialise_tool(tool)
                for _, tool in sorted(self._tools.items())
            ]
        return self._api_cache

    def to_api_tools_with_cache(self, enable_cache: bool) -> list[dict[str, Any]]:
        """Return :meth:`to_api_tools` with a cache marker on the last tool.

        Mirrors Rust L190-198. When ``enable_cache`` is true, the last
        entry gets ``cache_control = {"type": "ephemeral"}``, which lets
        prompt-cache-aware providers (Anthropic, some OpenAI proxies)
        anchor the prefix at the end of the tool list.
        """
        # Copy the list so callers don't mutate the memoised payload.
        tools = [dict(t) for t in self.to_api_tools()]
        if enable_cache and tools:
            last = tools[-1]
            # Avoid mutating the cached `function` dict in place.
            last["function"] = dict(last["function"])
            last["cache_control"] = {"type": "ephemeral"}
        return tools

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _invalidate_api_cache(self) -> None:
        self._api_cache = None

    @staticmethod
    def _serialise_tool(tool: ToolSpec) -> dict[str, Any]:
        # Encode the tool name to the provider-safe wire form. Rust
        # `to_api_tool_name` (client.rs:25-39) is reversible, so the
        # Python in-memory name (which may contain `.` / `:` / non-ASCII)
        # round-trips correctly via `from_api_tool_name` when the model
        # echoes it back. See client.streaming for the decode side.
        from deepseek_tui.tools.encoding import to_api_tool_name

        from deepseek_tui.tools.encoding import sanitize

        params = tool.input_schema()
        if isinstance(params, dict):
            params = sanitize(params)

        return {
            "type": "function",
            "function": {
                "name": to_api_tool_name(tool.name()),
                "description": tool.description(),
                "parameters": params,
                "allowed_callers": ["direct"],
                "defer_loading": tool.defer_loading(),
            },
        }


from typing import TYPE_CHECKING

from deepseek_tui.config.models import Config

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
from deepseek_tui.tools.automation import (
    AutomationCreateTool,
    AutomationDeleteTool,
    AutomationListTool,
    AutomationPauseTool,
    AutomationReadTool,
    AutomationResumeTool,
    AutomationRunTool,
    AutomationUpdateTool,
)
from deepseek_tui.tools.encoding import DeprecatingAliasTool
from deepseek_tui.tools.file import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from deepseek_tui.tools.git import (
    GitBlameTool,
    GitDiffTool,
    GitLogTool,
    GitShowTool,
    GitStatusTool,
)
from deepseek_tui.tools.git import (
    GitHubCloseTool,
    GitHubCommentTool,
    GitHubIssueContextTool,
    GitHubPrContextTool,
)
from deepseek_tui.tools.knowledge import (
    NoteTool,
    PlanUpdateTool,
    ReviewTool,
    SkillLoadTool,
)
from deepseek_tui.tools.mcp import (
    ListMcpResourcesTool,
    ListMcpResourceTemplatesTool,
    McpGetPromptTool,
    ReadMcpResourceTool,
)
from deepseek_tui.tools.runtime import MultiToolUseParallelTool
from deepseek_tui.tools.user_input import RetrieveToolResultTool
from deepseek_tui.tools.search import FileSearchTool, GrepFilesTool
from deepseek_tui.tools.shell import (
    ExecShellCancelTool,
    ExecShellInteractTool,
    ExecShellTool,
    ExecShellWaitTool,
)
from deepseek_tui.tools.subagent import (
    AgentAssignTool,
    AgentCancelTool,
    AgentCloseTool,
    AgentListTool,
    AgentResultTool,
    AgentResumeTool,
    AgentSendInputTool,
    AgentSpawnTool,
    AgentWaitTool,
    DelegateToAgentTool,
)
from deepseek_tui.tools.task import (
    PrAttemptListTool,
    PrAttemptPreflightTool,
    PrAttemptReadTool,
    PrAttemptRecordTool,
    TaskCancelTool,
    TaskCreateTool,
    TaskGateRunTool,
    TaskListTool,
    TaskReadTool,
    TaskShellStartTool,
    TaskShellWaitTool,
)
from deepseek_tui.tools.time_tools import CurrentTimeTool
from deepseek_tui.tools.todo import TodoAddTool, TodoListTool, TodoUpdateTool, TodoWriteTool
from deepseek_tui.tools.user_input import RequestUserInputTool
from deepseek_tui.tools.patch import ApplyPatchTool, DiagnosticsTool, ProjectMapTool
from deepseek_tui.tools.validation import RevertTurnTool, RunTestsTool, ValidateDataTool
from deepseek_tui.tools.web import FetchUrlTool, WebSearchTool


def build_default_registry(config: Config | None = None, *, mode: str = "agent") -> ToolRegistry:
    cfg = config or Config()
    registry = ToolRegistry()

    for tool in [
        ReadFileTool(),
        ListDirTool(),
        GrepFilesTool(),
        FileSearchTool(),
        GitStatusTool(),
        GitDiffTool(),
        GitLogTool(),
        GitShowTool(),
        GitBlameTool(),
        DiagnosticsTool(),
        ProjectMapTool(),
        RetrieveToolResultTool(),
        # Register both legacy ``todo_list`` and canonical ``checklist_list``
        # under the same singleton class (mirrors Rust ``with_todo_tool``
        # in ``crates/tui/src/tools/registry.rs`` which registers all 8
        # names against one ``SharedTodoList``).
        TodoListTool(),
        TodoListTool(canonical=True),
    ]:
        registry.register(tool)

    if mode != "plan":
        for tool in [
            WriteFileTool(),
            EditFileTool(),
            TodoWriteTool(),
            TodoWriteTool(canonical=True),
            TodoAddTool(),
            TodoAddTool(canonical=True),
            TodoUpdateTool(),
            TodoUpdateTool(canonical=True),
        ]:
            registry.register(tool)

    if cfg.features.apply_patch and mode != "plan":
        registry.register(ApplyPatchTool())

    if cfg.features.web_search:
        registry.register(
            WebSearchTool(
                tavily_api_key=cfg.tavily_api_key,
                anysearch_api_key=cfg.anysearch_api_key,
            )
        )
        registry.register(FetchUrlTool(anysearch_api_key=cfg.anysearch_api_key))

    if cfg.allow_shell and cfg.features.shell_tool and mode != "plan":
        for tool in [
            ExecShellTool(),
            ExecShellWaitTool(),
            ExecShellInteractTool(),
            ExecShellCancelTool(),
        ]:
            registry.register(tool)

    for tool in [
        GitHubIssueContextTool(),
        GitHubPrContextTool(),
        GitHubCommentTool(),
        GitHubCloseTool(),
    ]:
        registry.register(tool)

    if cfg.features.mcp:
        for tool in [
            ListMcpResourcesTool(),
            ListMcpResourceTemplatesTool(),
            ReadMcpResourceTool(),
            McpGetPromptTool(),
        ]:
            registry.register(tool)

    if cfg.features.tasks:
        for tool in [
            TaskCreateTool(),
            TaskListTool(),
            TaskReadTool(),
            TaskCancelTool(),
            TaskGateRunTool(),
            TaskShellStartTool(),
            TaskShellWaitTool(),
            PrAttemptRecordTool(),
            PrAttemptListTool(),
            PrAttemptReadTool(),
            PrAttemptPreflightTool(),
        ]:
            registry.register(tool)

    if cfg.features.subagents:
        from deepseek_tui.tools.workflow import WorkflowTool

        registry.register(WorkflowTool())
        spawn = AgentSpawnTool()
        send = AgentSendInputTool()
        assign = AgentAssignTool()
        for tool in [
            spawn,
            DeprecatingAliasTool(spawn, "spawn_agent", "agent_spawn"),
            AgentResultTool(),
            AgentCancelTool(),
            AgentCloseTool(),
            AgentResumeTool(),
            AgentListTool(),
            send,
            DeprecatingAliasTool(send, "send_input", "agent_send_input"),
            assign,
            DeprecatingAliasTool(assign, "assign_agent", "agent_assign"),
            AgentWaitTool(),
            DelegateToAgentTool(),
        ]:
            registry.register(tool)

    if cfg.features.automations:
        registry.register(CurrentTimeTool())
        for tool in [
            AutomationCreateTool(),
            AutomationListTool(),
            AutomationReadTool(),
            AutomationUpdateTool(),
            AutomationPauseTool(),
            AutomationResumeTool(),
            AutomationDeleteTool(),
            AutomationRunTool(),
        ]:
            registry.register(tool)

    # Knowledge / memory / review tools
    registry.register(NoteTool())
    registry.register(PlanUpdateTool())
    registry.register(SkillLoadTool())

    # Engine-intercepted special tools (always active)
    registry.register(MultiToolUseParallelTool())
    registry.register(RequestUserInputTool())
    if cfg.features.web_search:
        registry.register(ReviewTool(config=cfg))

    registry.register(ValidateDataTool())
    registry.register(RunTestsTool())
    if mode != "plan":
        registry.register(RevertTurnTool())

    return registry


def build_subagent_registry(
    config: Config | None = None,
    *,
    mode: str = "agent",
    allowed_tools: list[str] | None = None,
    client: LLMClient | None = None,
    root_model: str | None = None,
    extra_tools: list[ToolSpec] | None = None,
) -> ToolRegistry:
    """Tool surface for a sub-agent loop (mirrors Rust ``SubAgentToolRegistry``).

    Default ``allowed_tools=None`` inherits the full agent registry. Custom
    agents pass an explicit allowlist.
    """
    cfg = config or Config()
    registry = build_default_registry(cfg, mode=mode)
    if allowed_tools is not None:
        registry.filter_by_names(set(allowed_tools))
    if extra_tools:
        registry.register_all(extra_tools)
    return registry
