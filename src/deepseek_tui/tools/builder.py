from __future__ import annotations

from deepseek_tui.config.models import Config
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
        registry.register(WebSearchTool(api_key=cfg.tavily_api_key))
        registry.register(FetchUrlTool())

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
        for tool in [
            AgentSpawnTool(),
            AgentResultTool(),
            AgentCancelTool(),
            AgentCloseTool(),
            AgentResumeTool(),
            AgentListTool(),
            AgentSendInputTool(),
            AgentAssignTool(),
            AgentWaitTool(),
            DelegateToAgentTool(),
        ]:
            registry.register(tool)

    if cfg.features.automations:
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
    registry.register(RlmTool(client=None, root_model=cfg.default_text_model or "deepseek-chat"))
    registry.register(SkillLoadTool())

    # Engine-intercepted special tools (always active)
    registry.register(MultiToolUseParallelTool())
    registry.register(RequestUserInputTool())

    if cfg.features.web_search:
        registry.register(ReviewTool(config=cfg))

    if getattr(cfg, "memory_enabled", True):
        registry.register(RememberTool())
        registry.register(RecallArchiveTool())

    registry.register(ValidateDataTool())
    registry.register(RunTestsTool())
    if mode != "plan":
        registry.register(RevertTurnTool())

    return registry
