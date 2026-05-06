from __future__ import annotations

from deepseek_tui.config.models import Config
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
from deepseek_tui.tools.mcp_tools import (
    ListMcpResourcesTool,
    ListMcpResourceTemplatesTool,
    McpGetPromptTool,
    ReadMcpResourceTool,
)
from deepseek_tui.tools.registry import ToolRegistry
from deepseek_tui.tools.search_tools import FileSearchTool, GrepFilesTool
from deepseek_tui.tools.shell_tools import (
    ExecShellCancelTool,
    ExecShellInteractTool,
    ExecShellTool,
    ExecShellWaitTool,
)
from deepseek_tui.tools.todo_tools import TodoAddTool, TodoListTool, TodoUpdateTool, TodoWriteTool
from deepseek_tui.tools.utility_tools import ApplyPatchTool, DiagnosticsTool, ProjectMapTool
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
        TodoListTool(),
    ]:
        registry.register(tool)

    if mode != "plan":
        for tool in [
            WriteFileTool(),
            EditFileTool(),
            TodoWriteTool(),
            TodoAddTool(),
            TodoUpdateTool(),
        ]:
            registry.register(tool)

    if cfg.features.apply_patch and mode != "plan":
        registry.register(ApplyPatchTool())

    if cfg.features.web_search:
        registry.register(WebSearchTool())
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

    return registry
