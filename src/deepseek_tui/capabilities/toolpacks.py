"""Default first-party ToolPacks.

This module preserves the old ``tools.builder`` registration order while
moving feature-specific tool ownership out of the builder composition root.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from deepseek_tui.config.models import Config
from deepseek_tui.goal.tools import goal_tools
from deepseek_tui.host.toolpacks import ToolPack
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

ToolFactory = Callable[[Config, str], list[ToolSpec]]


@dataclass(frozen=True, slots=True)
class FunctionToolPack:
    id: str
    factory: ToolFactory

    def tools(self, config: Config, *, mode: str) -> list[ToolSpec]:
        return self.factory(config, mode)


def _core_read_tools(_cfg: Config, _mode: str) -> list[ToolSpec]:
    return [
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
        TodoListTool(),
        TodoListTool(canonical=True),
    ]


def _core_write_tools(_cfg: Config, mode: str) -> list[ToolSpec]:
    if mode == "plan":
        return []
    return [
        WriteFileTool(),
        EditFileTool(),
        TodoWriteTool(),
        TodoWriteTool(canonical=True),
        TodoAddTool(),
        TodoAddTool(canonical=True),
        TodoUpdateTool(),
        TodoUpdateTool(canonical=True),
    ]


def _apply_patch_tools(cfg: Config, mode: str) -> list[ToolSpec]:
    if not cfg.features.apply_patch or mode == "plan":
        return []
    return [ApplyPatchTool()]


def _web_tools(cfg: Config, _mode: str) -> list[ToolSpec]:
    if not cfg.features.web_search:
        return []
    return [
        WebSearchTool(
            tavily_api_key=cfg.tavily_api_key,
            anysearch_api_key=cfg.anysearch_api_key,
        ),
        FetchUrlTool(anysearch_api_key=cfg.anysearch_api_key),
    ]


def _shell_tools(cfg: Config, mode: str) -> list[ToolSpec]:
    if not (cfg.allow_shell and cfg.features.shell_tool and mode != "plan"):
        return []
    return [
        ExecShellTool(),
        ExecShellWaitTool(),
        ExecShellInteractTool(),
        ExecShellCancelTool(),
    ]


def _github_tools(_cfg: Config, _mode: str) -> list[ToolSpec]:
    return [
        GitHubIssueContextTool(),
        GitHubPrContextTool(),
        GitHubCommentTool(),
        GitHubCloseTool(),
    ]


def _mcp_bridge_tools(cfg: Config, _mode: str) -> list[ToolSpec]:
    if not cfg.features.mcp:
        return []
    return [
        ListMcpResourcesTool(),
        ListMcpResourceTemplatesTool(),
        ReadMcpResourceTool(),
        McpGetPromptTool(),
    ]


def _task_tools(cfg: Config, _mode: str) -> list[ToolSpec]:
    if not cfg.features.tasks:
        return []
    return [
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
    ]


def _subagent_tools(cfg: Config, _mode: str) -> list[ToolSpec]:
    if not cfg.features.subagents:
        return []
    from deepseek_tui.tools.workflow_tool import WorkflowTool

    spawn = AgentSpawnTool()
    send = AgentSendInputTool()
    assign = AgentAssignTool()
    return [
        WorkflowTool(),
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
    ]


def _automation_tools(cfg: Config, _mode: str) -> list[ToolSpec]:
    if not cfg.features.automations:
        return []
    return [
        CurrentTimeTool(),
        AutomationCreateTool(),
        AutomationListTool(),
        AutomationReadTool(),
        AutomationUpdateTool(),
        AutomationPauseTool(),
        AutomationResumeTool(),
        AutomationDeleteTool(),
        AutomationRunTool(),
    ]


def _knowledge_tools(cfg: Config, _mode: str) -> list[ToolSpec]:
    return [
        NoteTool(),
        PlanUpdateTool(),
        RlmQueryTool(config=cfg),
        RlmTool(client=None, root_model=cfg.default_text_model or "deepseek-chat"),
        SkillLoadTool(),
    ]


def _engine_intercepted_tools(_cfg: Config, _mode: str) -> list[ToolSpec]:
    return [
        MultiToolUseParallelTool(),
        RequestUserInputTool(),
        *goal_tools(),
    ]


def _review_tools(cfg: Config, _mode: str) -> list[ToolSpec]:
    if not cfg.features.web_search:
        return []
    return [ReviewTool(config=cfg)]


def _memory_tools(cfg: Config, _mode: str) -> list[ToolSpec]:
    if not cfg.memory_enabled():
        return []
    return [RememberTool(), RecallArchiveTool()]


def _smart_memory_tools(cfg: Config, _mode: str) -> list[ToolSpec]:
    if not cfg.smart_memory_enabled():
        return []
    from deepseek_tui.tools.memory_tools import ConversationSearchTool, MemorySearchTool

    return [MemorySearchTool(), ConversationSearchTool()]


def _evolution_curated_tools(cfg: Config, _mode: str) -> list[ToolSpec]:
    if not (cfg.evolution.enabled and cfg.evolution.curated.enabled):
        return []
    from deepseek_tui.tools.memory_curate_tool import MemoryCurateTool

    return [MemoryCurateTool()]


def _evolution_procedural_tools(cfg: Config, _mode: str) -> list[ToolSpec]:
    if not (cfg.evolution.enabled and cfg.evolution.procedural.enabled):
        return []
    from deepseek_tui.tools.skill_manage_tool import SkillManageTool

    return [SkillManageTool()]


def _validation_tools(_cfg: Config, mode: str) -> list[ToolSpec]:
    tools: list[ToolSpec] = [ValidateDataTool(), RunTestsTool()]
    if mode != "plan":
        tools.append(RevertTurnTool())
    return tools


def default_tool_packs() -> tuple[ToolPack, ...]:
    return (
        FunctionToolPack("core_read", _core_read_tools),
        FunctionToolPack("core_write", _core_write_tools),
        FunctionToolPack("apply_patch", _apply_patch_tools),
        FunctionToolPack("web", _web_tools),
        FunctionToolPack("shell", _shell_tools),
        FunctionToolPack("github", _github_tools),
        FunctionToolPack("mcp_bridge", _mcp_bridge_tools),
        FunctionToolPack("tasks", _task_tools),
        FunctionToolPack("subagents", _subagent_tools),
        FunctionToolPack("automation", _automation_tools),
        FunctionToolPack("knowledge", _knowledge_tools),
        FunctionToolPack("engine_intercepted", _engine_intercepted_tools),
        FunctionToolPack("review", _review_tools),
        FunctionToolPack("memory", _memory_tools),
        FunctionToolPack("smart_memory", _smart_memory_tools),
        FunctionToolPack("evolution_curated", _evolution_curated_tools),
        FunctionToolPack("evolution_procedural", _evolution_procedural_tools),
        FunctionToolPack("validation", _validation_tools),
    )
