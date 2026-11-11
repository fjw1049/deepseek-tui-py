"""Real file tools, process death, cold task stores and conflict-safe undo."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from deepseek_tui.config.models import Config
from deepseek_tui.engine.dispatch import real_task_executor
from deepseek_tui.protocol.responses import ToolCall
from deepseek_tui.tools.file import WriteFileTool
from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.task import NewTaskRequest, TaskManager, TaskManagerConfig
from deepseek_tui.tools.task.file_checkpoints import TaskFileCheckpoints, checkpoint_store
from tests.engine.test_browser_primary_loop import ScriptedClient


def manager(root, executor=None):
    workspace = root / "workspace"
    workspace.mkdir(exist_ok=True)
    return TaskManager(
        TaskManagerConfig(data_dir=root / "state", default_workspace=workspace), executor
    )


async def stopped_task(root):
    mgr = manager(root)
    task = await mgr.add_task(NewTaskRequest(prompt="edit files"))
    await mgr.cancel_task(task.id)
    return mgr, task


async def write(checkpoints, workspace, path, content):
    ctx = ToolContext(working_directory=workspace)
    checkpoints.bind(ctx)
    result = await WriteFileTool().execute({"path": path, "content": content}, ctx)
    assert result.success


@pytest.mark.parametrize("original", [b"old\r\ntext\n", "姓名,金额\n张三,20".encode("gbk")])
async def test_real_engine_task_and_cold_restore(tmp_path, monkeypatch, original):
    mgr = manager(tmp_path, real_task_executor)
    workspace = tmp_path / "workspace"
    path = workspace / "data.csv"
    path.write_bytes(original)
    path.chmod(0o640)
    client = ScriptedClient(
        [
            ToolCall(
                id="write", name="write_file", arguments={"path": "data.csv", "content": "new\n"}
            ),
            ToolCall(
                id="create", name="write_file", arguments={"path": "new.txt", "content": "created"}
            ),
            "finished",
        ]
    )
    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", lambda _: client)
    await mgr.start()
    try:
        task = await mgr.add_task(
            NewTaskRequest(prompt="update files", config=Config(), auto_approve=True)
        )
        async with asyncio.timeout(10):
            while not (await mgr.get_task(task.id)).status.is_terminal():  # noqa: ASYNC110
                await asyncio.sleep(0.01)
        assert path.read_bytes() == b"new\n"
        assert (workspace / "new.txt").exists()
    finally:
        await mgr.shutdown()
    cold = manager(tmp_path)
    await cold.start()
    try:
        preview = await cold.restore_files(task.id)
        assert set(preview["paths"]) == {"data.csv", "new.txt"}
        assert path.read_bytes() == b"new\n"  # GET cannot mutate
        result = await cold.restore_files(task.id, preview=False)
        assert result["report"]["restored"] == ["data.csv", "new.txt"]
        assert path.read_bytes() == original
        assert path.stat().st_mode & 0o777 == 0o640
        assert not (workspace / "new.txt").exists()
        await cold.restore_files(task.id, preview=False)
        assert path.read_bytes() == original
        with pytest.raises(RuntimeError, match="stale history"):
            await cold.resume_task(task.id)
    finally:
        await cold.shutdown()


async def test_actual_process_death_preserves_completed_file_write(tmp_path):
    mgr, task = await stopped_task(tmp_path)
    workspace = Path(task.workspace)
    (workspace / "a.txt").write_text("original")
    script = """
import asyncio, os, sys
from pathlib import Path
from deepseek_tui.tools.task.file_checkpoints import TaskFileCheckpoints
from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.file import WriteFileTool
data, task, workspace = sys.argv[1:]
ctx = ToolContext(working_directory=Path(workspace))
TaskFileCheckpoints(Path(data), task, Path(workspace)).bind(ctx)
asyncio.run(WriteFileTool().execute({"path": "a.txt", "content": "changed"}, ctx))
os._exit(23)
"""
    try:
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-c", script, str(tmp_path / "state"), task.id, str(workspace)],
            capture_output=True,
            timeout=20,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        )
        assert result.returncode == 23, result.stderr.decode()
        await mgr.shutdown()
        mgr = manager(tmp_path)
        await mgr.start()
        restored = await mgr.restore_files(task.id, preview=False)
        assert restored["report"]["restored"] == ["a.txt"]
        assert (workspace / "a.txt").read_text() == "original"
    finally:
        await mgr.shutdown()


async def test_external_edit_and_unfinished_write_are_preserved(tmp_path):
    mgr, task = await stopped_task(tmp_path)
    workspace = Path(task.workspace)
    path = workspace / "a.txt"
    path.write_text("before")
    journal = TaskFileCheckpoints(tmp_path / "state", task.id, workspace)
    try:
        await write(journal, workspace, "a.txt", "task")
        path.write_text("external")
        result = await mgr.restore_files(task.id, preview=False)
        assert result["report"]["conflicted"] == ["a.txt"]
        assert path.read_text() == "external"
        # Pre-image persisted but process died before a post-image was recorded.
        path2 = workspace / "interrupted.txt"
        path2.write_text("old")
        journal.store.record_pre_write(journal.turn_id, "interrupted.txt", "old")
        path2.write_text("unattributed")
        result = await mgr.restore_files(task.id, preview=False)
        assert "interrupted.txt" in result["report"]["skipped"] + result["report"]["conflicted"]
        assert path2.read_text() == "unattributed"
    finally:
        await mgr.shutdown()


async def test_capture_failure_blocks_text_and_child_workspace_is_resolved(tmp_path, monkeypatch):
    mgr, task = await stopped_task(tmp_path)
    workspace = Path(task.workspace)
    child = workspace / "child"
    child.mkdir()
    journal = TaskFileCheckpoints(tmp_path / "state", task.id, workspace)
    try:
        await write(journal, child, "new.txt", "child")
        assert (await mgr.restore_files(task.id))["paths"] == {"child/new.txt": "restored"}

        def fail(*args):
            raise OSError("disk full")

        monkeypatch.setattr(journal.store, "_save", fail)
        with pytest.raises(ToolError, match="write was not started"):
            await write(journal, workspace, "blocked.txt", "must not appear")
        assert not (workspace / "blocked.txt").exists()
    finally:
        await mgr.shutdown()


async def test_restore_refuses_active_tasks_and_corrupt_checkpoint(tmp_path):
    mgr, task = await stopped_task(tmp_path)
    workspace = Path(task.workspace)
    journal = TaskFileCheckpoints(tmp_path / "state", task.id, workspace)
    try:
        await write(journal, workspace, "new.txt", "keep")
        queued = await mgr.add_task(NewTaskRequest(prompt="busy"))
        with pytest.raises(RuntimeError, match="Other tasks"):
            await mgr.restore_files(task.id, preview=False)
        await mgr.cancel_task(queued.id)
        (tmp_path / "state" / "file-checkpoints" / task.id / f"{journal.turn_id}.json").write_text(
            "broken"
        )
        with pytest.raises(RuntimeError, match="unreadable"):
            await mgr.restore_files(task.id, preview=False)
        assert (workspace / "new.txt").read_text() == "keep"
    finally:
        await mgr.shutdown()


@pytest.mark.parametrize("initial", [b"initial", "原始内容".encode("gbk")])
async def test_multiple_attempts_restore_to_initial_content(tmp_path, initial):
    mgr, task = await stopped_task(tmp_path)
    workspace = Path(task.workspace)
    path = workspace / "a.txt"
    path.write_bytes(initial)
    try:
        for content in ("first attempt", "resumed attempt"):
            journal = TaskFileCheckpoints(tmp_path / "state", task.id, workspace)
            await write(journal, workspace, "a.txt", content)
        assert len(checkpoint_store(tmp_path / "state", task.id).list_for_thread(task.id)) == 1
        await mgr.restore_files(task.id, preview=False)
        assert path.read_bytes() == initial
    finally:
        await mgr.shutdown()


async def test_http_preview_restore_and_stale_resume(tmp_path):
    import httpx
    from fastapi import FastAPI

    from deepseek_tui.server.routes import router_tasks
    from deepseek_tui.server.runtime import AppRuntime

    mgr, task = await stopped_task(tmp_path)
    workspace = Path(task.workspace)
    app = FastAPI()
    app.state.runtime = AppRuntime(
        config=Config(),
        working_directory=workspace,
        tool_runtime=SimpleNamespace(task_manager=mgr),
    )
    app.include_router(router_tasks)
    journal = TaskFileCheckpoints(tmp_path / "state", task.id, workspace)
    try:
        await write(journal, workspace, "new.txt", "created")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://local"
        ) as client:
            response = await client.get(f"/v1/tasks/{task.id}/files")
            assert response.status_code == 200
            assert response.json()["paths"] == {"new.txt": "restored"}
            assert (workspace / "new.txt").exists()
            response = await client.post(f"/v1/tasks/{task.id}/files/restore")
            assert response.status_code == 200
            assert response.json()["resume_blocked"]
            assert not (workspace / "new.txt").exists()
            response = await client.get(f"/v1/tasks/{task.id}")
            assert response.json()["file_restore_started"]
            response = await client.post(f"/v1/tasks/{task.id}/resume")
            assert response.status_code == 409
    finally:
        await mgr.shutdown()


async def test_real_subagent_file_tool_inherits_task_journal(tmp_path, monkeypatch):
    from deepseek_tui.protocol.messages import Role
    from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta, StreamToolCallComplete

    child_finished = asyncio.Event()

    class Client(ScriptedClient):
        async def stream_chat_completion(self, request):
            self.requests.append(request)
            child = any(
                m.role is Role.USER and "child-only-marker" in m.text_content()
                for m in request.messages
            )
            tool_results = [m for m in request.messages if m.role is Role.TOOL]
            if child and not tool_results:
                yield StreamToolCallComplete(
                    tool_call=ToolCall(
                        id="child_write",
                        name="write_file",
                        arguments={"path": "child.txt", "content": "child wrote this"},
                    )
                )
            elif child:
                child_finished.set()
                yield StreamTextDelta(text="child finished")
            elif not tool_results:
                yield StreamToolCallComplete(
                    tool_call=ToolCall(
                        id="spawn",
                        name="agent",
                        arguments={
                            "action": "spawn",
                            "agent_type": "custom",
                            "allowed_tools": ["write_file"],
                            "prompt": "child-only-marker",
                        },
                    )
                )
            else:
                await asyncio.wait_for(child_finished.wait(), timeout=5)
                yield StreamTextDelta(text="parent finished")
            yield StreamDone()

    client = Client([])
    monkeypatch.setattr("deepseek_tui.client.factory.build_llm_client", lambda _: client)
    mgr = manager(tmp_path, real_task_executor)
    await mgr.start()
    try:
        task = await mgr.add_task(
            NewTaskRequest(prompt="delegate a file edit", config=Config(), auto_approve=True)
        )
        async with asyncio.timeout(10):
            while not (await mgr.get_task(task.id)).status.is_terminal():  # noqa: ASYNC110
                await asyncio.sleep(0.01)
        path = Path(task.workspace) / "child.txt"
        assert path.read_text() == "child wrote this"
        assert (await mgr.restore_files(task.id))["paths"] == {"child.txt": "restored"}
        await mgr.restore_files(task.id, preview=False)
        assert not path.exists()
    finally:
        await mgr.shutdown()
