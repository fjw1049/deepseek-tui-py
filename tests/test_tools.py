from __future__ import annotations

import subprocess
from pathlib import Path

import httpx
import pytest

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
from deepseek_tui.tools.base import ToolError
from deepseek_tui.tools.context import ToolContext
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
from deepseek_tui.tools.registry import ToolRegistry
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
    AgentListTool,
    AgentResultTool,
    AgentSpawnTool,
    AgentWaitTool,
)
from deepseek_tui.tools.task_tools import (
    PrAttemptCancelTool,
    PrAttemptCompleteTool,
    PrAttemptCreateTool,
    PrAttemptListTool,
    PrAttemptReadTool,
    PrAttemptUpdateTool,
    TaskCancelTool,
    TaskCreateTool,
    TaskGateRunTool,
    TaskListTool,
    TaskReadTool,
)
from deepseek_tui.tools.todo_tools import (
    TodoAddTool,
    TodoListTool,
    TodoUpdateTool,
    TodoWriteTool,
)
from deepseek_tui.tools.utility_tools import DiagnosticsTool, ProjectMapTool
from deepseek_tui.tools.web_tools import FetchUrlTool, WebSearchTool


def _run_git_command(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.asyncio
async def test_file_tools_round_trip(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    write_tool = WriteFileTool()
    read_tool = ReadFileTool()
    edit_tool = EditFileTool()
    list_tool = ListDirTool()

    write_result = await write_tool.execute(
        {"path": "notes/test.txt", "content": "hello world"},
        context,
    )
    read_result = await read_tool.execute({"path": "notes/test.txt"}, context)
    await edit_tool.execute(
        {
            "path": "notes/test.txt",
            "old_string": "world",
            "new_string": "python",
        },
        context,
    )
    edited_result = await read_tool.execute({"path": "notes/test.txt"}, context)
    list_result = await list_tool.execute({"path": "notes"}, context)

    assert write_result.success is True
    assert read_result.content == "hello world"
    assert edited_result.content == "hello python"
    assert list_result.content == "test.txt"


@pytest.mark.asyncio
async def test_edit_tool_requires_unique_match(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    path = tmp_path / "dup.txt"
    path.write_text("x x", encoding="utf-8")

    with pytest.raises(ToolError, match="not unique"):
        await EditFileTool().execute(
            {
                "path": "dup.txt",
                "old_string": "x",
                "new_string": "y",
            },
            context,
        )


@pytest.mark.asyncio
async def test_registry_executes_and_sorts_tools(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path, timeout_ms=1000)
    registry = ToolRegistry()
    registry.register(WriteFileTool())
    registry.register(ReadFileTool())
    registry.register(EditFileTool())
    registry.register(ListDirTool())

    await registry.execute(
        "write_file",
        {"path": "alpha.txt", "content": "alpha"},
        context,
    )
    read_result = await registry.execute("read_file", {"path": "alpha.txt"}, context)
    api_names = [item["function"]["name"] for item in registry.to_api_tools()]

    assert read_result.content == "alpha"
    assert api_names == sorted(api_names)
    assert registry.to_api_tools()[0]["function"]["parameters"]["type"] == "object"


@pytest.mark.asyncio
async def test_registry_raises_for_missing_tool(tmp_path: Path) -> None:
    registry = ToolRegistry()
    context = ToolContext(working_directory=tmp_path)

    with pytest.raises(ToolError, match="Tool not found"):
        await registry.execute("missing", {}, context)


@pytest.mark.asyncio
async def test_workspace_boundary_blocks_escape(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes workspace"):
        await ReadFileTool().execute({"path": str(outside)}, context)

    with pytest.raises(ValueError, match="escapes workspace"):
        await ReadFileTool().execute({"path": "../outside.txt"}, context)

    trusted = ToolContext(working_directory=tmp_path, trust_mode=True)
    result = await ReadFileTool().execute({"path": str(outside)}, trusted)
    assert result.content == "secret"


@pytest.mark.asyncio
async def test_search_tools_find_files_and_matches(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "a.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    (docs_dir / "b.md").write_text("beta only\n", encoding="utf-8")

    grep_result = await GrepFilesTool().execute(
        {"pattern": "beta", "path": "docs"},
        context,
    )
    file_result = await FileSearchTool().execute(
        {"pattern": ".txt", "path": "docs"},
        context,
    )

    assert "a.txt:2:beta" in grep_result.content
    assert "b.md:1:beta only" in grep_result.content
    assert str(docs_dir / "a.txt") in file_result.content


@pytest.mark.asyncio
async def test_fetch_url_tool_returns_body_and_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeAsyncClient:
        def __init__(self, *, timeout: float | None, follow_redirects: bool) -> None:
            self.timeout = timeout
            self.follow_redirects = follow_redirects

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        async def get(
            self,
            url: str,
            *,
            params: dict[str, str] | None = None,
            headers: dict[str, str] | None = None,
        ) -> httpx.Response:
            request = httpx.Request("GET", url, params=params, headers=headers)
            return httpx.Response(
                200,
                headers={"content-type": "text/plain; charset=utf-8"},
                content=b"hello from web tool",
                request=request,
            )

    monkeypatch.setattr("deepseek_tui.tools.web_tools.httpx.AsyncClient", FakeAsyncClient)

    result = await FetchUrlTool().execute(
        {"url": "https://example.com/demo"},
        ToolContext(working_directory=tmp_path, timeout_ms=1500),
    )

    assert result.success is True
    assert result.content == "hello from web tool"
    assert result.metadata == {
        "url": "https://example.com/demo",
        "status_code": 200,
        "content_type": "text/plain; charset=utf-8",
    }


@pytest.mark.asyncio
async def test_web_search_tool_parses_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeAsyncClient:
        def __init__(self, *, timeout: float | None, follow_redirects: bool) -> None:
            self.timeout = timeout
            self.follow_redirects = follow_redirects

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

        async def get(
            self,
            url: str,
            *,
            params: dict[str, str] | None = None,
            headers: dict[str, str] | None = None,
        ) -> httpx.Response:
            assert url == "https://html.duckduckgo.com/html/"
            assert params == {"q": "deepseek tui"}
            assert headers == {"user-agent": "deepseek-tui-py/0.1"}
            request = httpx.Request("GET", url, params=params, headers=headers)
            html = b"""
            <html><body>
              <a class="result__a" href="//example.com/one">First Result</a>
              <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Ftwo">Second Result</a>
            </body></html>
            """
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                content=html,
                request=request,
            )

    monkeypatch.setattr("deepseek_tui.tools.web_tools.httpx.AsyncClient", FakeAsyncClient)

    result = await WebSearchTool().execute(
        {"query": "deepseek tui", "max_results": 1},
        ToolContext(working_directory=tmp_path, timeout_ms=2000),
    )

    assert result.success is True
    assert result.content == "1. First Result - https://example.com/one"
    assert result.metadata == {
        "query": "deepseek tui",
        "result_count": 1,
        "results": [{"title": "First Result", "url": "https://example.com/one"}],
        "source": "https://html.duckduckgo.com/html/?q=deepseek+tui",
    }


@pytest.mark.asyncio
async def test_github_context_tools_call_gh_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeProcess:
        def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
            self._stdout = stdout
            self._stderr = stderr
            self.returncode = returncode

        async def communicate(self) -> tuple[bytes, bytes]:
            return self._stdout, self._stderr

    calls: list[tuple[object, ...]] = []

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> FakeProcess:
        calls.append(args)
        command = tuple(str(arg) for arg in args)
        if command[:4] == ("gh", "issue", "view", "12"):
            return FakeProcess(b"issue body")
        if command[:4] == ("gh", "pr", "view", "34"):
            return FakeProcess(b"pr body")
        return FakeProcess(b"", b"unexpected", 1)

    monkeypatch.setattr(
        "deepseek_tui.tools.github_tools.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    context = ToolContext(working_directory=tmp_path)
    issue_result = await GitHubIssueContextTool().execute(
        {"repo": "owner/repo", "issue_number": 12},
        context,
    )
    pr_result = await GitHubPrContextTool().execute(
        {"repo": "owner/repo", "pr_number": 34},
        context,
    )

    assert issue_result.success is True
    assert issue_result.content == "issue body"
    assert issue_result.metadata["args"] == [
        "gh",
        "issue",
        "view",
        "12",
        "--repo",
        "owner/repo",
        "--comments",
    ]
    assert pr_result.success is True
    assert pr_result.content == "pr body"
    assert pr_result.metadata["args"] == [
        "gh",
        "pr",
        "view",
        "34",
        "--repo",
        "owner/repo",
        "--comments",
    ]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_github_write_tools_call_gh_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeProcess:
        def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
            self._stdout = stdout
            self._stderr = stderr
            self.returncode = returncode

        async def communicate(self) -> tuple[bytes, bytes]:
            return self._stdout, self._stderr

    calls: list[tuple[object, ...]] = []

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> FakeProcess:
        calls.append(args)
        command = tuple(str(arg) for arg in args)
        if command[:4] == ("gh", "issue", "comment", "12"):
            return FakeProcess(b"commented")
        if command[:4] == ("gh", "pr", "close", "34"):
            return FakeProcess(b"closed")
        return FakeProcess(b"", b"unexpected", 1)

    monkeypatch.setattr(
        "deepseek_tui.tools.github_tools.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    context = ToolContext(working_directory=tmp_path)
    comment_result = await GitHubCommentTool().execute(
        {
            "repo": "owner/repo",
            "issue_number": 12,
            "body": "hello from test",
        },
        context,
    )
    close_result = await GitHubCloseTool().execute(
        {
            "repo": "owner/repo",
            "pr_number": 34,
            "comment": "closing now",
        },
        context,
    )

    assert comment_result.success is True
    assert comment_result.content == "commented"
    assert comment_result.metadata["args"] == [
        "gh",
        "issue",
        "comment",
        "12",
        "--repo",
        "owner/repo",
        "--body",
        "hello from test",
    ]
    assert close_result.success is True
    assert close_result.content == "closed"
    assert close_result.metadata["args"] == [
        "gh",
        "pr",
        "close",
        "34",
        "--repo",
        "owner/repo",
        "--comment",
        "closing now",
    ]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_registry_executes_search_and_shell_tools(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path, timeout_ms=1000)
    registry = ToolRegistry()
    registry.register(GrepFilesTool())
    registry.register(FileSearchTool())
    registry.register(ExecShellTool())
    registry.register(ExecShellInteractTool())
    registry.register(ExecShellWaitTool())

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")

    grep_result = await registry.execute(
        "grep_files",
        {"pattern": "beta", "path": "docs"},
        context,
    )
    file_result = await registry.execute(
        "file_search",
        {"pattern": ".txt", "path": "docs"},
        context,
    )
    interactive = await registry.execute(
        "exec_shell",
        {
            "command": ('python3 -c "import sys; data = sys.stdin.read(); print(data[::-1])"'),
            "background": True,
        },
        context,
    )
    await registry.execute(
        "exec_shell_interact",
        {
            "process_id": interactive.content,
            "input": "drawer",
            "close_stdin": True,
        },
        context,
    )
    waited_result = await registry.execute(
        "exec_shell_wait",
        {"process_id": interactive.content},
        context,
    )

    assert "notes.txt:2:beta" in grep_result.content
    assert str(docs_dir / "notes.txt") in file_result.content
    assert waited_result.content == "reward"
    assert waited_result.metadata["stdout"] == "reward\n"


@pytest.mark.asyncio
async def test_git_tools_read_repository_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git_command(repo, "init")
    _run_git_command(repo, "config", "user.name", "Test User")
    _run_git_command(repo, "config", "user.email", "test@example.com")

    tracked_file = repo / "tracked.txt"
    tracked_file.write_text("alpha\nbeta\n", encoding="utf-8")
    _run_git_command(repo, "add", "tracked.txt")
    _run_git_command(repo, "commit", "-m", "initial commit")

    tracked_file.write_text("alpha\nchanged\n", encoding="utf-8")

    context = ToolContext(working_directory=repo)
    status_result = await GitStatusTool().execute({}, context)
    diff_result = await GitDiffTool().execute({}, context)
    log_result = await GitLogTool().execute({"max_count": 1}, context)
    show_result = await GitShowTool().execute({"object": "HEAD"}, context)
    blame_result = await GitBlameTool().execute(
        {"file": "tracked.txt", "line_start": 1, "line_end": 1},
        context,
    )

    assert "## master" in status_result.content or "## main" in status_result.content
    assert " M tracked.txt" in status_result.content
    assert "-beta" in diff_result.content
    assert "+changed" in diff_result.content
    assert "initial commit" in log_result.content
    assert "initial commit" in show_result.content
    assert "tracked.txt" in blame_result.content


@pytest.mark.asyncio
async def test_shell_tools_run_wait_interact_and_cancel(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    exec_tool = ExecShellTool()
    wait_tool = ExecShellWaitTool()
    interact_tool = ExecShellInteractTool()
    cancel_tool = ExecShellCancelTool()

    foreground_result = await exec_tool.execute(
        {"command": "python3 -c 'import sys; print(123); print(789, file=sys.stderr)'"},
        context,
    )
    assert foreground_result.success is True
    assert foreground_result.content == "123\n789"
    assert foreground_result.metadata == {
        "returncode": 0,
        "stdout": "123\n",
        "stderr": "789\n",
        "status": "completed",
    }

    background_result = await exec_tool.execute(
        {"command": "python3 -c 'print(456)'", "background": True},
        context,
    )
    waited_result = await wait_tool.execute(
        {"process_id": background_result.content},
        context,
    )
    assert waited_result.content == "456"
    assert waited_result.metadata == {
        "process_id": background_result.content,
        "returncode": 0,
        "stdout": "456\n",
        "stderr": "",
        "status": "completed",
    }

    interactive = await exec_tool.execute(
        {
            "command": ('python3 -c "import sys; data = sys.stdin.read(); print(data.upper())"'),
            "background": True,
        },
        context,
    )
    interact_result = await interact_tool.execute(
        {
            "process_id": interactive.content,
            "input": "hello world\n",
            "close_stdin": True,
        },
        context,
    )
    interactive_output = await wait_tool.execute(
        {"process_id": interactive.content},
        context,
    )
    assert interact_result.content == "sent"
    assert interact_result.metadata == {
        "process_id": interactive.content,
        "close_stdin": True,
    }
    assert interactive_output.content == "HELLO WORLD"

    cancellable = await exec_tool.execute(
        {"command": "python3 -c 'import time; time.sleep(5)'", "background": True},
        context,
    )
    cancelled_result = await cancel_tool.execute(
        {"process_id": cancellable.content},
        context,
    )
    assert cancelled_result.content == "cancelled"
    assert cancelled_result.metadata["process_id"] == cancellable.content
    assert cancelled_result.metadata["status"] == "cancelled"
    assert cancelled_result.metadata["stdout"] == ""
    assert cancelled_result.metadata["stderr"] == ""
    assert isinstance(cancelled_result.metadata["returncode"], int)


@pytest.mark.asyncio
async def test_task_tools_create_list_read_cancel(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    create_tool = TaskCreateTool()
    list_tool = TaskListTool()
    read_tool = TaskReadTool()
    cancel_tool = TaskCancelTool()

    r1 = await create_tool.execute(
        {"title": "First task", "description": "Do something"},
        context,
    )
    r2 = await create_tool.execute({"title": "Second task"}, context)

    assert r1.success is True
    assert r1.content == "1"
    assert r1.metadata["task"]["status"] == "open"
    assert r2.content == "2"

    list_result = await list_tool.execute({}, context)
    assert list_result.success is True
    assert list_result.metadata["count"] == 2
    assert "First task" in list_result.content
    assert "Second task" in list_result.content

    read_result = await read_tool.execute({"task_id": "1"}, context)
    assert read_result.success is True
    assert "Do something" in read_result.content

    cancel_result = await cancel_tool.execute({"task_id": "2"}, context)
    assert cancel_result.success is True
    assert cancel_result.metadata["task"]["status"] == "cancelled"

    with pytest.raises(ToolError, match="Unknown task_id"):
        await read_tool.execute({"task_id": "99"}, context)


@pytest.mark.asyncio
async def test_task_gate_run(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    await TaskCreateTool().execute({"title": "Gate test"}, context)

    result = await TaskGateRunTool().execute(
        {"task_id": "1", "gate": "lint"},
        context,
    )
    assert result.success is True
    assert "lint" in result.content
    assert result.metadata["result"] == "passed"


@pytest.mark.asyncio
async def test_pr_attempt_lifecycle(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    await TaskCreateTool().execute({"title": "PR task"}, context)

    create_result = await PrAttemptCreateTool().execute(
        {"task_id": "1", "branch": "feat/x"},
        context,
    )
    assert create_result.success is True
    assert create_result.content == "1"
    assert create_result.metadata["attempt"]["status"] == "open"

    list_result = await PrAttemptListTool().execute({"task_id": "1"}, context)
    assert list_result.metadata["count"] == 1
    assert "feat/x" in list_result.content

    read_result = await PrAttemptReadTool().execute({"attempt_id": "1"}, context)
    assert "task: 1" in read_result.content

    await PrAttemptUpdateTool().execute({"attempt_id": "1", "notes": "WIP"}, context)
    read_after = await PrAttemptReadTool().execute({"attempt_id": "1"}, context)
    assert "notes: WIP" in read_after.content

    complete_result = await PrAttemptCompleteTool().execute({"attempt_id": "1"}, context)
    assert complete_result.metadata["attempt"]["status"] == "completed"

    await PrAttemptCreateTool().execute({"task_id": "1", "branch": "feat/y"}, context)
    cancel_result = await PrAttemptCancelTool().execute({"attempt_id": "2"}, context)
    assert cancel_result.metadata["attempt"]["status"] == "cancelled"

    with pytest.raises(ToolError, match="Unknown attempt_id"):
        await PrAttemptReadTool().execute({"attempt_id": "99"}, context)


@pytest.mark.asyncio
async def test_todo_tools_write_add_update_list(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)

    write_result = await TodoWriteTool().execute({"items": ["Buy milk", "Write tests"]}, context)
    assert write_result.success is True
    assert write_result.metadata["count"] == 2

    add_result = await TodoAddTool().execute({"text": "Deploy"}, context)
    assert add_result.content == "3"

    list_result = await TodoListTool().execute({}, context)
    assert list_result.metadata["count"] == 3
    assert "[ ] 1: Buy milk" in list_result.content
    assert "[ ] 3: Deploy" in list_result.content

    await TodoUpdateTool().execute({"item_id": "1", "done": True}, context)
    list_after = await TodoListTool().execute({}, context)
    assert "[x] 1: Buy milk" in list_after.content

    await TodoUpdateTool().execute({"item_id": "2", "text": "Write more tests"}, context)
    list_renamed = await TodoListTool().execute({}, context)
    assert "Write more tests" in list_renamed.content

    overwrite = await TodoWriteTool().execute({"items": ["Fresh"]}, context)
    assert overwrite.metadata["count"] == 1
    fresh_list = await TodoListTool().execute({}, context)
    assert fresh_list.metadata["count"] == 1
    assert "Fresh" in fresh_list.content


@pytest.mark.asyncio
async def test_subagent_tools_spawn_assign_result_cancel(
    tmp_path: Path,
) -> None:
    context = ToolContext(working_directory=tmp_path)

    spawn_result = await AgentSpawnTool().execute(
        {"task": "Summarize file", "assignee": "worker-1"}, context
    )
    assert spawn_result.success is True
    assert spawn_result.content == "1"
    assert spawn_result.metadata["agent"]["status"] == "running"

    await AgentSpawnTool().execute({"task": "Lint code"}, context)

    list_result = await AgentListTool().execute({}, context)
    assert list_result.metadata["count"] == 2
    assert "Summarize file" in list_result.content

    await AgentAssignTool().execute({"agent_id": "1", "assignee": "worker-2"}, context)
    wait_result = await AgentWaitTool().execute({"agent_id": "1"}, context)
    assert wait_result.content == "(no result yet)"
    assert wait_result.metadata["agent"]["assignee"] == "worker-2"

    await AgentResultTool().execute({"agent_id": "1", "result": "Done summarizing"}, context)
    wait_after = await AgentWaitTool().execute({"agent_id": "1"}, context)
    assert wait_after.content == "Done summarizing"
    assert wait_after.metadata["agent"]["status"] == "completed"

    cancel_result = await AgentCancelTool().execute({"agent_id": "2"}, context)
    assert cancel_result.metadata["agent"]["status"] == "cancelled"

    with pytest.raises(ToolError, match="Unknown agent_id"):
        await AgentWaitTool().execute({"agent_id": "99"}, context)


@pytest.mark.asyncio
async def test_automation_tools_full_lifecycle(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)

    create_result = await AutomationCreateTool().execute(
        {"name": "Auto lint", "trigger": "on_push", "action": "run lint"},
        context,
    )
    assert create_result.success is True
    assert create_result.content == "1"

    await AutomationCreateTool().execute(
        {"name": "Auto test", "trigger": "on_pr", "action": "run tests"},
        context,
    )

    list_result = await AutomationListTool().execute({}, context)
    assert list_result.metadata["count"] == 2

    read_result = await AutomationReadTool().execute({"automation_id": "1"}, context)
    assert "on_push" in read_result.content
    assert "run lint" in read_result.content

    await AutomationUpdateTool().execute(
        {"automation_id": "1", "action": "run lint --fix"}, context
    )
    read_after = await AutomationReadTool().execute({"automation_id": "1"}, context)
    assert "run lint --fix" in read_after.content

    await AutomationPauseTool().execute({"automation_id": "1"}, context)
    read_paused = await AutomationReadTool().execute({"automation_id": "1"}, context)
    assert read_paused.metadata["automation"]["status"] == "paused"

    await AutomationResumeTool().execute({"automation_id": "1"}, context)
    read_resumed = await AutomationReadTool().execute({"automation_id": "1"}, context)
    assert read_resumed.metadata["automation"]["status"] == "active"

    run_result = await AutomationRunTool().execute({"automation_id": "1"}, context)
    assert "run lint --fix" in run_result.content

    await AutomationDeleteTool().execute({"automation_id": "2"}, context)
    list_after = await AutomationListTool().execute({}, context)
    assert list_after.metadata["count"] == 1

    with pytest.raises(ToolError, match="Unknown automation_id"):
        await AutomationReadTool().execute({"automation_id": "2"}, context)


@pytest.mark.asyncio
async def test_diagnostics_tool_returns_info(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    result = await DiagnosticsTool().execute({}, context)
    assert result.success is True
    assert "python:" in result.content
    assert "platform:" in result.content
    assert str(tmp_path) in result.content


@pytest.mark.asyncio
async def test_project_map_tool_lists_tree(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "README.md").write_text("", encoding="utf-8")

    result = await ProjectMapTool().execute({}, context)
    assert result.success is True
    assert "src/" in result.content
    assert "main.py" in result.content
    assert "README.md" in result.content
