from __future__ import annotations

from typing import TYPE_CHECKING

from deepseek_tui.config.models import Config

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.tools.registry import ToolRegistry
from deepseek_tui.goal.tools import goal_tools
from deepseek_tui.tools.automation_tools import (
    AutomationCreateTool,
    AutomationDeleteTool,
    AutomationListTool,
    AutomationPauseTool,
    AutomationReadTool,
    AutomationResumeTool,
    AutomationRunTool,
    AutomationUpdateTool,
)
from deepseek_tui.tools.base import ToolSpec
from deepseek_tui.tools.deprecation import DeprecatingAliasTool
from deepseek_tui.tools.file_tools import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from deepseek_tui.tools.git_tools import (
    GitBlameTool,
    GitDiffTool,
    GitLogTool,
    GitShowTool,
    GitStatusTool,
)
from deepseek_tui.tools.github_tools import (
    GitHubCloseTool,
    GitHubCommentTool,
    GitHubIssueContextTool,
    GitHubPrContextTool,
)
from deepseek_tui.tools.knowledge_tools import (
    NoteTool,
    PlanUpdateTool,
    RecallArchiveTool,
    RememberTool,
    ReviewTool,
    RlmQueryTool,
    SkillLoadTool,
)
from deepseek_tui.tools.mcp_tools import (
    ListMcpResourcesTool,
    ListMcpResourceTemplatesTool,
    McpGetPromptTool,
    ReadMcpResourceTool,
)
from deepseek_tui.tools.parallel_tool import MultiToolUseParallelTool
from deepseek_tui.tools.registry import ToolRegistry
from deepseek_tui.tools.retrieve_tool_result import RetrieveToolResultTool
from deepseek_tui.tools.rlm import RlmTool
from deepseek_tui.tools.search_tools import FileSearchTool, GrepFilesTool
from deepseek_tui.tools.shell_tools import (
    ExecShellCancelTool,
    ExecShellInteractTool,
    ExecShellTool,
    ExecShellWaitTool,
)
from deepseek_tui.tools.subagent_tools import (
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
from deepseek_tui.tools.task_tools import (
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
from deepseek_tui.tools.todo_tools import TodoAddTool, TodoListTool, TodoUpdateTool, TodoWriteTool
from deepseek_tui.tools.user_input_tool import RequestUserInputTool
from deepseek_tui.tools.utility_tools import ApplyPatchTool, DiagnosticsTool, ProjectMapTool
from deepseek_tui.tools.validation_tools import RevertTurnTool, RunTestsTool, ValidateDataTool
from deepseek_tui.tools.web_tools import FetchUrlTool, WebSearchTool


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
        from deepseek_tui.tools.workflow_tool import WorkflowTool

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
    registry.register(RlmQueryTool(config=cfg))
    registry.register(
        RlmTool(client=None, root_model=cfg.default_text_model or "deepseek-chat")
    )
    registry.register(SkillLoadTool())

    # Engine-intercepted special tools (always active)
    registry.register(MultiToolUseParallelTool())
    registry.register(RequestUserInputTool())
    registry.register_all(goal_tools())

    if cfg.features.web_search:
        registry.register(ReviewTool(config=cfg))

    if cfg.memory_enabled():
        registry.register(RememberTool())
        registry.register(RecallArchiveTool())

    if cfg.smart_memory_enabled():
        from deepseek_tui.tools.memory_tools import (
            ConversationSearchTool,
            MemorySearchTool,
        )

        registry.register(MemorySearchTool())
        registry.register(ConversationSearchTool())

    if cfg.evolution.enabled and cfg.evolution.curated.enabled:
        from deepseek_tui.tools.memory_curate_tool import MemoryCurateTool

        registry.register(MemoryCurateTool())
    if cfg.evolution.enabled and cfg.evolution.procedural.enabled:
        from deepseek_tui.tools.skill_manage_tool import SkillManageTool

        registry.register(SkillManageTool())

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
    wire_registry_client(registry, client, root_model=root_model or "deepseek-chat")
    if allowed_tools is not None:
        registry.filter_by_names(set(allowed_tools))
    if extra_tools:
        registry.register_all(extra_tools)
    return registry


def wire_registry_client(
    registry: ToolRegistry,
    client: LLMClient | None,
    *,
    root_model: str | None = None,
) -> None:
    """Re-register ``rlm`` with a live client after :class:`Engine` construction.

    ``build_default_registry`` registers ``RlmTool(client=None)`` because the
    registry is built before the HTTP client exists. Call this from
    :meth:`Engine.create` once the client is available.
    """
    if not registry.contains("rlm"):
        return
    model = root_model or "deepseek-chat"
    registry.remove("rlm")
    registry.register(RlmTool(client=client, root_model=model))
