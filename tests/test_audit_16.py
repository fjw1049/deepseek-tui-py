"""Behavioral regressions for builtin tool boundary fixes."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools import file as files
from deepseek_tui.tools.encoding import from_api_tool_name, to_api_tool_name
from deepseek_tui.tools.plan_mode import APPROVED_PLAN_MARKER, sync_approved_plan_reminder
from deepseek_tui.tools.registry import ToolContext, ToolError
from deepseek_tui.tools.search import GrepFilesTool
from deepseek_tui.tools.todo import ChecklistTool
from deepseek_tui.tools.user_input import validate_user_input_request
from deepseek_tui.tools.utils.gitignore import GitIgnoreMatcher
from deepseek_tui.tools.web import _merge_hits, _SearchHit


async def test_search_authorizes_real_targets(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "outside").write_text("fixture")
    (workspace / ".env").write_text("fixture")
    (workspace / "ok").write_text("fixture")
    (workspace / "external").symlink_to(tmp_path / "outside")
    (workspace / "alias").symlink_to(workspace / ".env")
    (workspace / "internal").symlink_to(workspace / "ok")
    result = await GrepFilesTool().execute(
        {"path": ".", "pattern": "fixture", "output_mode": "content"},
        ToolContext(working_directory=workspace),
    )
    assert "external:" not in result.content and "alias:" not in result.content
    assert "internal:" in result.content and "ok:" in result.content


async def test_content_stamp_refers_to_returned_content(tmp_path, monkeypatch):
    path = tmp_path / "file"
    path.write_text("old\n")
    original = files._read_text_page

    def change_after_read(*args, **kwargs):
        page = original(*args, **kwargs)
        path.write_text("new concurrent content\n")
        return page

    monkeypatch.setattr(files, "_read_text_page", change_after_read)
    context = ToolContext(working_directory=tmp_path)
    await files.ReadFileTool().execute({"path": "file"}, context)
    with pytest.raises(ToolError, match="changed"):
        await files.WriteFileTool().execute({"path": "file", "content": "stale"}, context)
    assert path.read_text() == "new concurrent content\n"


def test_page_stops_before_full_file(tmp_path):
    path = tmp_path / "large"
    path.write_bytes(b"first\n" + b"x\n" * 1048576)
    page = files._read_text_page(path, 0, 1)
    assert page.lines == [(1, "first")]
    assert page.bytes_scanned <= 65536 and page.has_more
    assert page.total_lines is None


@pytest.mark.parametrize("name", ["toolx00002E", "tool-x00002E-", "工具.foo", "mcp--name"])
def test_codec_roundtrip(name):
    assert from_api_tool_name(to_api_tool_name(name)) == name


def test_ignore_bad_rule_preserves_good_rule(tmp_path):
    (tmp_path / ".gitignore").write_text("[z-a]\n*.log\n")
    assert GitIgnoreMatcher(tmp_path).ignored(tmp_path / "debug.log", is_dir=False)


def question(qid="q"):
    return {
        "header": "H",
        "id": qid,
        "question": "Q",
        "options": [{"label": "A", "description": "a"}, {"label": "B", "description": "b"}],
    }


@pytest.mark.parametrize("field,value", [("header", 1), ("id", {"x": 1}), ("question", " ")])
def test_question_types(field, value):
    q = question()
    q[field] = value
    with pytest.raises(ToolError):
        validate_user_input_request({"questions": [q]})


def test_question_ids_unique_and_input_copied():
    q = question()
    with pytest.raises(ToolError):
        validate_user_input_request({"questions": [q, q]})
    parsed = validate_user_input_request({"questions": [q]})
    q["options"][0]["label"] = "changed"
    assert parsed[0].options[0]["label"] == "A"


def test_url_identity_preserves_query_and_case():
    urls = [
        "https://example.test/Page?id=1",
        "https://example.test/Page?id=2",
        "https://example.test/page?id=1",
    ]
    hits = [_SearchHit(str(i), u, "", "test", 1) for i, u in enumerate(urls)]
    assert len(_merge_hits(hits, 8)) == 3


def test_real_user_plan_phrase_survives(tmp_path):
    user = Message.user(f"Explain: {APPROVED_PLAN_MARKER}")
    history = [user]
    sync_approved_plan_reminder(
        history, mode="agent", working_directory=tmp_path, metadata={"runtime_thread_id": "fixture"}
    )
    assert history == [user]


async def test_checklist_awaits_persistence(tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    async def persist(*_):
        entered.set()
        await release.wait()

    context = ToolContext(
        working_directory=tmp_path,
        metadata={
            "task_id": "task",
            "task_manager": type(
                "Manager", (), {"record_tool_metadata": AsyncMock(side_effect=persist)}
            )(),
        },
    )
    pending = asyncio.create_task(ChecklistTool().execute({"items": ["one"]}, context))
    await entered.wait()
    was_done = pending.done()
    release.set()
    await pending
    assert not was_done


async def test_checklist_failure_can_retry(tmp_path):
    from types import SimpleNamespace

    manager = SimpleNamespace(record_tool_metadata=AsyncMock(side_effect=OSError("disk full")))
    context = ToolContext(
        working_directory=tmp_path, metadata={"task_id": "t", "task_manager": manager}
    )
    with pytest.raises(OSError):
        await ChecklistTool().execute({"items": ["one"]}, context)
    assert "todos" not in context.metadata
    manager.record_tool_metadata.side_effect = None
    await ChecklistTool().execute({"items": ["one"]}, context)
    assert manager.record_tool_metadata.await_count == 2


@pytest.mark.parametrize("reply", ["do not accept yolo", "不要接受计划", "never enter plan"])
def test_unknown_plan_answers_do_not_approve(reply):
    from deepseek_tui.tools.plan_mode import parse_enter_plan_response, parse_exit_plan_response

    response = {"answers": [{"label": reply}]}
    assert parse_enter_plan_response(response) is None
    assert parse_exit_plan_response(response) is None


def test_output_capture_limits_and_spill(tmp_path, monkeypatch):
    from deepseek_tui.tools import output_capture as output

    monkeypatch.setattr("deepseek_tui.tools.runtime.spillover_root", lambda: tmp_path)
    monkeypatch.setattr(output, "MEMORY_LIMIT", 64)
    monkeypatch.setattr(output, "DISK_LIMIT", 100)
    capture = output.OutputCapture()
    for _ in range(100):
        capture.append(b"x" * 16)
    capture.close()
    assert capture.total == 1600
    assert len(capture.head) + len(capture.tail) <= 64
    assert capture.path.stat().st_size == 100
    assert b"disk limit" in capture.preview()


@pytest.mark.parametrize("path_failure", [False, True])
def test_output_spill_failure_keeps_draining(tmp_path, monkeypatch, path_failure):
    from deepseek_tui.tools import output_capture as output

    bad_root = tmp_path / "not-a-directory"
    bad_root.write_text("fixture")
    monkeypatch.setattr("deepseek_tui.tools.runtime.spillover_root", lambda: bad_root)
    if path_failure:
        def fail_path(*_):
            raise OSError("spill directory unavailable")
        monkeypatch.setattr("deepseek_tui.tools.runtime.spillover_path", fail_path)
    monkeypatch.setattr(output, "MEMORY_LIMIT", 64)
    capture = output.OutputCapture()
    for _ in range(100):
        capture.append(b"x" * 16)
    capture.close()
    assert capture.total == 1600
    assert len(capture.head) + len(capture.tail) <= 64
    assert b"spill write failed" in capture.preview()


async def test_both_process_pipes_drain(tmp_path, monkeypatch):
    import sys

    from deepseek_tui.tools.output_capture import collect_process

    monkeypatch.setattr("deepseek_tui.tools.runtime.spillover_root", lambda: tmp_path)
    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        'import os; os.write(1,b"a"*200000); os.write(2,b"b"*200000)',
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(collect_process(proc), 5)
    assert proc.returncode == 0
    assert len(stdout) < 70000 and len(stderr) < 70000
    assert sorted(p.stat().st_size for p in tmp_path.glob("*.txt")) == [200000, 200000]


async def test_web_response_limit_and_bad_json(tmp_path):
    import httpx

    from deepseek_tui.tools.web import _anysearch_extract, _post_bounded

    async def oversized(request):
        return httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))

    async with httpx.AsyncClient(transport=httpx.MockTransport(oversized)) as client:
        with pytest.raises(ToolError, match="2 MiB"):
            await _post_bounded(client, "https://example.test")

    async def malformed(request):
        return httpx.Response(200, content=b"invalid JSON")

    async with httpx.AsyncClient(transport=httpx.MockTransport(malformed)) as client:
        with pytest.raises(ToolError, match="invalid JSON"):
            await _anysearch_extract(
                client,
                url="https://example.test",
                api_key=None,
                context=ToolContext(working_directory=tmp_path),
            )


async def test_write_cancel_waits_for_worker(tmp_path, monkeypatch):
    import threading

    started, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    path = tmp_path / "file"

    def writer(path, content):
        loop.call_soon_threadsafe(started.set)
        release.wait(5)
        path.write_text(content)

    monkeypatch.setattr(files, "write_text_atomic", writer)
    pending = asyncio.create_task(files._write_text(path, "written", expected=None))
    await started.wait()
    pending.cancel()
    await asyncio.sleep(0)
    assert not pending.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert path.read_text() == "written"


async def test_plan_failure_preserves_metadata(tmp_path, monkeypatch):
    from deepseek_tui.tools.knowledge import PlanUpdateTool

    path = tmp_path / ".deepseek" / "plan.md"
    path.parent.mkdir()
    path.write_text("previous")
    context = ToolContext(working_directory=tmp_path, metadata={"plan": {"goal": "keep"}})

    def fail(*_):
        raise OSError("disk full")

    monkeypatch.setattr("deepseek_tui.utils.write_text_atomic", fail)
    with pytest.raises(OSError):
        await PlanUpdateTool().execute({"plan": "new"}, context)
    assert path.read_text() == "previous"
    assert context.metadata["plan"] == {"goal": "keep"}


async def test_deleted_read_file_is_stale(tmp_path):
    path = tmp_path / "gone"
    path.write_text("old")
    context = ToolContext(working_directory=tmp_path)
    await files.ReadFileTool().execute({"path": "gone"}, context)
    path.unlink()
    with pytest.raises(ToolError, match="changed"):
        await files.WriteFileTool().execute({"path": "gone", "content": "stale"}, context)
    assert not path.exists()


async def test_pty_reader_caps_memory_and_closes(tmp_path, monkeypatch):
    from deepseek_tui.tools import shell

    monkeypatch.setattr("deepseek_tui.tools.runtime.spillover_root", lambda: tmp_path)
    chunks = iter([b"x" * 4096] * 256 + [b""])
    monkeypatch.setattr(shell, "_safe_read", lambda *_: next(chunks))
    monkeypatch.setattr(shell.os, "waitpid", lambda *_: (-1, 0))
    closed = []
    monkeypatch.setattr(shell.os, "close", lambda fd: closed.append(fd))
    proc = shell.PtyProcess(-1, 99999)
    await proc._reader_loop()
    assert proc.done and proc.master_fd == -1
    assert closed.count(99999) == 1
    assert len(proc.output) < 70000
    assert proc._output.path.stat().st_size == 1048576
