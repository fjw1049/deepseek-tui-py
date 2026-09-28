"""Audit 15 observations; temporary files and mocked UI, no API calls.

Run: PYTHONPATH=src .venv/bin/python docs/audits/2026-09-27/tui_probe.py
These assertions reproduce defects, not desired regression contracts.
"""

from __future__ import annotations

import asyncio
import gc
import json
import tempfile
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tomllib
from rich.text import Text

from deepseek_tui.engine.events import SessionActivityEvent, TurnCompleteEvent
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools.subagent import MailboxMessage, MailboxMessageKind
from deepseek_tui.tui.app import DeepSeekTUI
from deepseek_tui.tui.cards import AgentLifecycle, DelegateCard, apply_to_delegate
from deepseek_tui.tui.commands import _config_write, cmd_clear, cmd_compact, cmd_export
from deepseek_tui.tui.dialogs import _collect_files
from deepseek_tui.tui.session_restore import apply_messages_to_engine
from deepseek_tui.tui.tool_cell import parse_unified_diff
from deepseek_tui.tui.transcript import Transcript


def sync_probes() -> dict:
    result = {}
    called = []

    async def clear():
        called.append(True)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        response = cmd_clear("", SimpleNamespace(action_new_session=clear))
        gc.collect()
    result["clear"] = {
        "actions_executed": len(called),
        "output": response.output,
        "unawaited_warning": any("never awaited" in str(w.message) for w in caught),
    }
    assert not called and result["clear"]["unawaited_warning"]

    engine = SimpleNamespace(session_messages=[], _compaction_summary_prompt="old session summary")
    apply_messages_to_engine(engine, [Message.user("new session")])
    result["restore_stale_summary"] = engine._compaction_summary_prompt
    assert result["restore_stale_summary"] == "old session summary"

    with tempfile.TemporaryDirectory(prefix="audit15-") as temporary:
        root = Path(temporary)
        config = root / "config.toml"
        config.write_text('model = "root"\n[providers.demo]\nmodel = "provider"\n')
        with patch("deepseek_tui.config.paths.user_config_path", return_value=config):
            _config_write("model", "changed")
            result["config_multiple_tables"] = tomllib.loads(config.read_text())
            assert result["config_multiple_tables"]["providers"]["demo"]["model"] == "changed"
            _config_write("locale", "en")
            result["config_new_key_in_wrong_table"] = tomllib.loads(config.read_text())
            assert "locale" not in result["config_new_key_in_wrong_table"]
            _config_write("model", 'quote"break')
            try:
                tomllib.loads(config.read_text())
            except tomllib.TOMLDecodeError:
                result["config_quote_invalid"] = True
            else:
                raise AssertionError("expected invalid TOML")
        export = root / "chat.md"
        cmd_export(
            str(export),
            SimpleNamespace(
                _engine=SimpleNamespace(session_messages=[Message.user("UNIQUE_CONVERSATION_TEXT")])
            ),
        )
        result["export_contains_conversation"] = "UNIQUE_CONVERSATION_TEXT" in export.read_text()
        assert not result["export_contains_conversation"]
        for name in ["a.txt", "b.py"]:
            (root / name).write_text("")
        result["picker_ignores_glob"] = _collect_files(root, 500, "*.py", set())
        assert any(name == "a.txt" for name, _ in result["picker_ignores_glob"])
        yielded = []

        def entries(_self, _pattern):
            for index in range(1000):
                yielded.append(index)
                yield root / "a.txt"

        with patch.object(Path, "rglob", entries):
            rows = _collect_files(root, 1, "**/*", set())
        result["picker_limit"] = {"rows": len(rows), "paths_traversed": len(yielded)}
        assert len(rows) == 1 and len(yielded) == 1000

    transcript = Transcript()
    with (
        patch.object(transcript, "_hide_welcome"),
        patch.object(transcript, "_mount_cell"),
        patch.object(transcript, "_scroll_end_safe"),
    ):
        transcript.append_delta("hi <deepseek:sub")
        transcript.append_delta("agent.done>secret</deepseek:subagent.done>bye")
    result["split_sentinel"] = {
        "cell": transcript._current_assistant.content_text,
        "normalized": transcript._display_buffer,
    }
    assert result["split_sentinel"]["cell"] != result["split_sentinel"]["normalized"]

    card = DelegateCard(
        "agent-a", "reviewer", status=AgentLifecycle.COMPLETED, summary="[/unknown]"
    )
    try:
        Text.from_markup(card.render_text())
    except Exception as exc:
        result["card_markup"] = type(exc).__name__
    else:
        raise AssertionError("expected malformed markup rejection")
    apply_to_delegate(
        card, MailboxMessage(kind=MailboxMessageKind.PROGRESS, agent_id="agent-a", status="late")
    )
    result["card_late_progress"] = card.status.value
    assert card.status == AgentLifecycle.RUNNING

    files = parse_unified_diff("--- a/file\n+++ b/file\n@@ -1 +1 @@\n--- old\n+++ new\n")
    result["diff_header_in_body"] = [
        {"old": f.old_path, "new": f.new_path, "additions": f.additions, "deletions": f.deletions}
        for f in files
    ]
    assert len(files) == 2 and sum(f.additions for f in files) == 0
    return result


async def async_probes() -> dict:
    result = {}
    entered, resume = asyncio.Event(), asyncio.Event()
    old, new = Message.user("old"), Message.user("new during compaction")

    async def compact(messages):
        entered.set()
        await resume.wait()
        return SimpleNamespace(messages=messages, success=True)

    engine = SimpleNamespace(session_messages=[old], _run_compaction=compact)
    tasks = []
    real_ensure_future = asyncio.ensure_future

    def schedule(coro):
        task = real_ensure_future(coro)
        tasks.append(task)
        return task

    with patch("asyncio.ensure_future", schedule):
        cmd_compact("", SimpleNamespace(_engine=engine, query_one=lambda _: Mock()))
    await entered.wait()
    engine.session_messages.append(new)
    resume.set()
    await asyncio.gather(*tasks)
    result["compact_loses_concurrent_message"] = new not in engine.session_messages
    assert result["compact_loses_concurrent_message"]

    handle = EngineHandle()
    await handle.emit(TurnCompleteEvent(None, running_subagents=1))
    await handle.emit(SessionActivityEvent(0, 0, "background finished"))
    ui = SimpleNamespace(
        handle=handle,
        _engine_task=None,
        _engine=None,
        query_one=lambda _: Mock(),
        _turn_started_at=None,
        _interaction_mode="agent",
        _schedule_info_sidebar_refresh=Mock(),
        _maybe_notify_turn_done=Mock(),
    )
    await asyncio.wait_for(DeepSeekTUI._listen_events(ui), 1)
    next_event = await asyncio.wait_for(anext(handle.events()), 1)
    result["listener_leaves_background_event"] = type(next_event).__name__
    assert isinstance(next_event, SessionActivityEvent)

    order = []

    async def producer():
        try:
            await asyncio.Event().wait()
        finally:
            order.append("producer stopped")

    task = asyncio.create_task(producer())
    await asyncio.sleep(0)

    async def hook(_event):
        order.append("session_end")

    async def shutdown():
        # Real Engine.shutdown_session also calls this hook.
        await hook("session_end")
        order.append("resources closed")

    ui = SimpleNamespace(
        _engine=SimpleNamespace(run_lifecycle_hook=hook, shutdown=shutdown),
        _engine_task=task,
        exit=lambda: order.append("exit"),
    )
    await DeepSeekTUI.action_quit(ui)
    result["quit_order_mocked_engine"] = order
    assert order.index("resources closed") < order.index("producer stopped")
    return result


if __name__ == "__main__":
    results = {**sync_probes(), **asyncio.run(async_probes())}
    target = Path(__file__).with_name("tui-probe-results.json")
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(results, ensure_ascii=False, indent=2))
