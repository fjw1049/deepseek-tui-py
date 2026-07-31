"""Conformance suite: a Claude Code-standard plugin exercised end-to-end.

Builds a plugin using only Claude Code conventions (``.claude-plugin/
plugin.json``, ``hooks/hooks.json`` with CamelCase events and Claude tool
matchers, namespaced skills, ``settings.json`` defaultAgent) and verifies
the DeepSeek-TUI plugin pipeline loads and executes it with Claude
semantics:

* stdin JSON hook protocol (claude dialect tool/event names)
* exit-code semantics (2 = block, reason on stderr)
* stdout JSON decisions (decision/reason, permissionDecision,
  additionalContext, systemMessage, continue:false)
* Stop / SubagentStop event mapping with stop_hook_active
* skills namespacing (plugin:skill) with bare-name fallback
* settings.json defaultAgent manifest surface
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from deepseek_tui.config.models import HooksConfig, LifecycleHookEntry
from deepseek_tui.integrations.hooks import (
    HookContext,
    HookExecutor,
    HookResult,
    _apply_output_semantics,
    aggregate_hook_decision,
)
from deepseek_tui.integrations.plugins import (
    collect_contributions,
    discover_plugins,
    load_plugin_manifest,
    set_plugin_trusted,
)


def make_conformance_plugin(plugins_dir: Path) -> Path:
    """A plugin written purely against Claude Code conventions."""
    plugin = plugins_dir / "conformance"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "conformance",
                "version": "1.0.0",
                "description": "Claude conformance test plugin",
            }
        ),
        encoding="utf-8",
    )
    # settings.json: main-thread agent activation.
    (plugin / "settings.json").write_text(
        json.dumps({"defaultAgent": "conductor"}), encoding="utf-8"
    )
    # Namespaced skill.
    skill = plugin / "skills" / "echo-check"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: echo-check\ndescription: Conformance skill.\n---\nBody.\n",
        encoding="utf-8",
    )
    # Agent persona.
    agents = plugin / "agents"
    agents.mkdir()
    (agents / "conductor.md").write_text(
        "---\nname: conductor\ndescription: Conformance conductor.\n---\n"
        "You are the conductor persona.\n",
        encoding="utf-8",
    )
    # hooks.json with Claude CamelCase events + Claude tool matcher.
    hooks = plugin / "hooks"
    hooks.mkdir()
    (hooks / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [
                                {"type": "command", "command": "echo pre"}
                            ],
                        }
                    ],
                    "Stop": [
                        {
                            "hooks": [
                                {"type": "command", "command": "echo stop"}
                            ]
                        }
                    ],
                    "SubagentStop": [
                        {
                            "hooks": [
                                {"type": "command", "command": "echo substop"}
                            ]
                        }
                    ],
                    "UserPromptSubmit": [
                        {
                            "hooks": [
                                {"type": "command", "command": "echo ctx"}
                            ]
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )
    return plugin


# ── Loader conformance ───────────────────────────────────────────────────


def test_conformance_plugin_loads_with_claude_semantics(tmp_path: Path) -> None:
    plugin = make_conformance_plugin(tmp_path)
    set_plugin_trusted("conformance", True, plugins_dir=tmp_path)
    manifest = load_plugin_manifest(plugin)
    assert manifest is not None
    assert manifest.name == "conformance"
    # settings.json defaultAgent surfaces on the manifest.
    assert manifest.default_agent == "conductor"

    contribs = collect_contributions(discover_plugins(plugins_dir=tmp_path))
    # Skills namespaced plugin:skill.
    assert [s.name for s in contribs.skills] == ["conformance:echo-check"]
    events = {h.event: h for h in contribs.hook_entries}
    # All four Claude events map onto runtime lifecycle events.
    assert set(events) == {
        "tool_call_before",
        "turn_end",
        "subagent_stop",
        "message_submit",
    }
    for hook in events.values():
        # Foreign hooks carry the claude I/O dialect and Claude's
        # documented 600s default timeout.
        assert hook.io_dialect == "claude"
        assert hook.timeout_secs == 600.0
    # Claude matcher "Bash" resolved to our exec_shell taxonomy.
    assert events["tool_call_before"].condition == {
        "type": "tool_name_any",
        "names": ["exec_shell"],
    }


# ── stdin JSON protocol ──────────────────────────────────────────────────


def test_stdin_payload_claude_dialect_translates_names() -> None:
    ctx = HookContext(
        tool_name="exec_shell",
        tool_args=json.dumps({"command": "ls"}),
        session_id="s1",
        workspace=Path("/tmp/ws"),
    )
    payload = ctx.to_stdin_payload("tool_call_before", "claude")
    assert payload["hook_event_name"] == "PreToolUse"
    assert payload["tool_name"] == "Bash"
    assert payload["tool_input"] == {"command": "ls"}
    assert payload["session_id"] == "s1"
    assert payload["cwd"] == "/tmp/ws"


def test_stdin_payload_native_dialect_keeps_names() -> None:
    ctx = HookContext(tool_name="exec_shell", tool_args="{}")
    payload = ctx.to_stdin_payload("tool_call_before", "native")
    assert payload["hook_event_name"] == "tool_call_before"
    assert payload["tool_name"] == "exec_shell"


def test_stdin_payload_stop_carries_stop_hook_active() -> None:
    ctx = HookContext(stop_hook_active=True)
    payload = ctx.to_stdin_payload("turn_end", "claude")
    assert payload["hook_event_name"] == "Stop"
    assert payload["stop_hook_active"] is True


def test_stdin_payload_prompt_and_tool_response() -> None:
    ctx = HookContext(message="hello")
    assert ctx.to_stdin_payload("message_submit", "claude")["prompt"] == "hello"
    ctx2 = HookContext(
        tool_name="read_file", tool_result="content", tool_success=True
    )
    post = ctx2.to_stdin_payload("tool_call_after", "claude")
    assert post["tool_response"] == "content"
    assert post["tool_success"] is True


# ── exit-code / stdout decision semantics ───────────────────────────────


def _result(exit_code: int, stdout: str = "", stderr: str = "") -> HookResult:
    return HookResult(
        name="t",
        success=exit_code == 0,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
    )


def test_exit_2_blocks_with_stderr_reason() -> None:
    r = _apply_output_semantics("tool_call_before", _result(2, stderr="nope"))
    assert r.blocked and r.block_reason == "nope"


def test_exit_1_is_non_blocking() -> None:
    r = _apply_output_semantics("tool_call_before", _result(1, stderr="warn"))
    assert not r.blocked


def test_stdout_decision_block() -> None:
    doc = json.dumps({"decision": "block", "reason": "policy"})
    r = _apply_output_semantics("tool_call_after", _result(0, stdout=doc))
    assert r.blocked and r.block_reason == "policy"


def test_stdout_continue_false_blocks() -> None:
    doc = json.dumps({"continue": False, "stopReason": "halt"})
    r = _apply_output_semantics("turn_end", _result(0, stdout=doc))
    assert r.blocked and r.block_reason == "halt"


def test_stdout_permission_decision_deny_and_ask() -> None:
    deny = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "no writes",
            }
        }
    )
    r = _apply_output_semantics("tool_call_before", _result(0, stdout=deny))
    assert r.blocked and r.permission_decision == "deny"
    assert r.block_reason == "no writes"

    ask = json.dumps(
        {"hookSpecificOutput": {"permissionDecision": "ask"}}
    )
    r2 = _apply_output_semantics("tool_call_before", _result(0, stdout=ask))
    assert not r2.blocked and r2.permission_decision == "ask"


def test_stdout_additional_context_and_system_message() -> None:
    doc = json.dumps(
        {
            "systemMessage": "heads up",
            "hookSpecificOutput": {"additionalContext": "extra facts"},
        }
    )
    r = _apply_output_semantics("message_submit", _result(0, stdout=doc))
    assert r.additional_context == "extra facts"
    assert r.system_message == "heads up"


def test_bare_top_level_additional_context_accepted() -> None:
    """Community hooks (e.g. superpowers) emit a bare top-level
    additionalContext; hookSpecificOutput takes precedence when both
    are present."""
    bare = json.dumps({"additionalContext": "bare ctx"})
    r = _apply_output_semantics("session_start", _result(0, stdout=bare))
    assert r.additional_context == "bare ctx"

    both = json.dumps(
        {
            "additionalContext": "bare ctx",
            "hookSpecificOutput": {"additionalContext": "nested ctx"},
        }
    )
    r2 = _apply_output_semantics("session_start", _result(0, stdout=both))
    assert r2.additional_context == "nested ctx"


def test_plain_stdout_becomes_context_for_prompt_events() -> None:
    r = _apply_output_semantics("message_submit", _result(0, stdout="raw ctx"))
    assert r.additional_context == "raw ctx"
    # Tool events do not treat plain stdout as context.
    r2 = _apply_output_semantics("tool_call_before", _result(0, stdout="noise"))
    assert r2.additional_context is None


def test_aggregate_decision_deny_wins_and_context_collects() -> None:
    a = HookResult(name="a", success=True, exit_code=0, additional_context="c1")
    b = HookResult(
        name="b", success=False, exit_code=2, blocked=True, block_reason="r"
    )
    c = HookResult(
        name="c", success=True, exit_code=0, permission_decision="ask"
    )
    decision = aggregate_hook_decision([a, b, c])
    assert decision.blocked and decision.reason == "r"
    assert decision.ask
    assert decision.additional_context == ["c1"]


# ── Executor end-to-end (real subprocesses) ──────────────────────────────


async def test_executor_pipes_claude_stdin_and_blocks_on_exit_2(
    tmp_path: Path,
) -> None:
    """A 'community' hook script reads stdin JSON, sees Claude names, and
    blocks dangerous Bash commands with exit 2 + stderr reason."""
    capture = tmp_path / "seen.json"
    script = tmp_path / "guard.py"
    script.write_text(
        "import json, sys\n"
        "data = json.load(sys.stdin)\n"
        f"open({str(capture)!r}, 'w').write(json.dumps(data))\n"
        "if data['tool_name'] == 'Bash' and 'rm -rf' in data['tool_input'].get('command', ''):\n"
        "    print('dangerous command blocked', file=sys.stderr)\n"
        "    sys.exit(2)\n",
        encoding="utf-8",
    )
    cfg = HooksConfig(
        hooks=[
            LifecycleHookEntry(
                event="tool_call_before",
                command=f"{sys.executable} {script}",
                io_dialect="claude",
                name="conformance:PreToolUse",
                owner_plugin_id="conformance",
            )
        ]
    )
    executor = HookExecutor(cfg, tmp_path)

    # Benign command: passes, stdin carried Claude names.
    ctx = HookContext(
        tool_name="exec_shell",
        tool_args=json.dumps({"command": "ls"}),
        workspace=tmp_path,
    )
    results = await executor.execute("tool_call_before", ctx)
    assert len(results) == 1 and not results[0].blocked
    seen = json.loads(capture.read_text(encoding="utf-8"))
    assert seen["hook_event_name"] == "PreToolUse"
    assert seen["tool_name"] == "Bash"

    # Dangerous command: exit 2 → blocked with stderr reason.
    ctx2 = HookContext(
        tool_name="exec_shell",
        tool_args=json.dumps({"command": "rm -rf /"}),
        workspace=tmp_path,
    )
    results2 = await executor.execute("tool_call_before", ctx2)
    decision = aggregate_hook_decision(results2)
    assert decision.blocked
    assert "dangerous command blocked" in (decision.reason or "")


async def test_executor_exports_claude_plugin_root_env(tmp_path: Path) -> None:
    """Claude community hooks (hookify etc.) import via CLAUDE_PLUGIN_ROOT."""
    plugin_root = tmp_path / "my-plugin"
    plugin_root.mkdir()
    script = tmp_path / "check_env.py"
    script.write_text(
        "import json, os, sys\n"
        "print(json.dumps({\n"
        "  'CLAUDE_PLUGIN_ROOT': os.environ.get('CLAUDE_PLUGIN_ROOT'),\n"
        "  'CLAUDE_PROJECT_DIR': os.environ.get('CLAUDE_PROJECT_DIR'),\n"
        "}))\n",
        encoding="utf-8",
    )
    cfg = HooksConfig(
        hooks=[
            LifecycleHookEntry(
                event="message_submit",
                command=f"{sys.executable} {script}",
                io_dialect="claude",
                plugin_root=str(plugin_root),
            )
        ]
    )
    executor = HookExecutor(cfg, tmp_path)
    results = await executor.execute(
        "message_submit",
        HookContext(message="hi", workspace=tmp_path),
    )
    assert len(results) == 1 and results[0].success
    seen = json.loads(results[0].stdout.strip())
    assert seen["CLAUDE_PLUGIN_ROOT"] == str(plugin_root)
    assert seen["CLAUDE_PROJECT_DIR"] == str(tmp_path)


async def test_executor_stop_hook_stdout_decision(tmp_path: Path) -> None:
    """A Stop hook blocks the first stop via stdout JSON, then allows once
    stop_hook_active is set (self-limiting per Claude docs)."""
    script = tmp_path / "stop_guard.py"
    script.write_text(
        "import json, sys\n"
        "data = json.load(sys.stdin)\n"
        "assert data['hook_event_name'] == 'Stop'\n"
        "if not data.get('stop_hook_active'):\n"
        "    print(json.dumps({'decision': 'block', 'reason': 'finish the report'}))\n",
        encoding="utf-8",
    )
    cfg = HooksConfig(
        hooks=[
            LifecycleHookEntry(
                event="turn_end",
                command=f"{sys.executable} {script}",
                io_dialect="claude",
            )
        ]
    )
    executor = HookExecutor(cfg, tmp_path)

    first = aggregate_hook_decision(
        await executor.execute("turn_end", HookContext(stop_hook_active=False))
    )
    assert first.blocked and first.reason == "finish the report"

    second = aggregate_hook_decision(
        await executor.execute("turn_end", HookContext(stop_hook_active=True))
    )
    assert not second.blocked


async def test_engine_pre_tool_hook_deny_blocks_execution(
    tmp_path: Path,
) -> None:
    """A blocking PreToolUse hook prevents the tool from running and the
    reason is returned to the model as a failed tool result."""
    from unittest.mock import AsyncMock, MagicMock

    from deepseek_tui.engine.orchestrator.core import Engine
    from deepseek_tui.protocol.responses import ToolCall
    from deepseek_tui.tools.registry import ToolResult

    script = tmp_path / "deny.py"
    script.write_text(
        "import sys\nprint('write blocked by policy', file=sys.stderr)\nsys.exit(2)\n",
        encoding="utf-8",
    )
    cfg = HooksConfig(
        hooks=[
            LifecycleHookEntry(
                event="tool_call_before",
                command=f"{sys.executable} {script}",
                io_dialect="claude",
            )
        ]
    )
    engine = Engine.__new__(Engine)
    engine.mode = "agent"
    engine.default_model = "deepseek-chat"
    engine.hook_executor = HookExecutor(cfg, tmp_path)
    engine.tool_context = MagicMock()
    engine.tool_context.working_directory = tmp_path
    engine.tool_context.metadata = {}
    engine.session_messages = []
    impl = AsyncMock(return_value=ToolResult(success=True, content="ran"))
    engine._execute_single_tool_impl = impl  # type: ignore[method-assign]

    tc = ToolCall(id="t1", name="write_file", arguments={"path": "x", "content": "y"})
    result = await engine._execute_single_tool(tc, [], "deepseek-chat")

    impl.assert_not_called()
    assert result is not None and not result.success
    assert "write blocked by policy" in result.content


async def test_engine_post_tool_hook_feedback_appended(tmp_path: Path) -> None:
    """A PostToolUse block does not revert the tool but appends the reason
    so the model sees the objection."""
    from unittest.mock import AsyncMock, MagicMock

    from deepseek_tui.engine.orchestrator.core import Engine
    from deepseek_tui.protocol.responses import ToolCall
    from deepseek_tui.tools.registry import ToolResult

    script = tmp_path / "post.py"
    script.write_text(
        "import json\n"
        "print(json.dumps({'decision': 'block', 'reason': 'lint failed, fix it'}))\n",
        encoding="utf-8",
    )
    cfg = HooksConfig(
        hooks=[
            LifecycleHookEntry(
                event="tool_call_after",
                command=f"{sys.executable} {script}",
                io_dialect="claude",
            )
        ]
    )
    engine = Engine.__new__(Engine)
    engine.mode = "agent"
    engine.default_model = "deepseek-chat"
    engine.hook_executor = HookExecutor(cfg, tmp_path)
    engine.tool_context = MagicMock()
    engine.tool_context.working_directory = tmp_path
    engine.tool_context.metadata = {}
    engine.session_messages = []
    engine._accrue_child_token_cost_from_metadata = MagicMock()
    impl = AsyncMock(return_value=ToolResult(success=True, content="edited"))
    engine._execute_single_tool_impl = impl  # type: ignore[method-assign]

    tc = ToolCall(id="t2", name="edit_file", arguments={"path": "x"})
    result = await engine._execute_single_tool(tc, [], "deepseek-chat")

    impl.assert_called_once()
    assert result is not None and result.success
    assert "lint failed, fix it" in result.content


async def test_engine_message_submit_block_stops_turn(
    tmp_path: Path, monkeypatch
) -> None:
    """UserPromptSubmit blocking fires inside the engine send-message path
    (shared by TUI and server/GUI): the prompt never reaches the model and
    the reason surfaces as a StatusEvent."""
    from unittest.mock import AsyncMock

    from deepseek_tui.config.models import Config
    from deepseek_tui.engine.events import (
        StatusEvent,
        TurnCompleteEvent,
    )
    from deepseek_tui.engine.handle import EngineHandle, SendMessageOp
    from deepseek_tui.engine.orchestrator.core import Engine

    monkeypatch.setenv("DEEPSEEK_HOME", str(tmp_path / "home"))
    script = tmp_path / "block.py"
    script.write_text(
        "import sys\nprint('prompt rejected', file=sys.stderr)\nsys.exit(2)\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cfg = Config(features={"tasks": False, "subagents": False, "mcp": False})
    client = AsyncMock()
    handle = EngineHandle()
    engine = await Engine.create(
        handle, client, config=cfg, working_directory=workspace
    )
    try:
        engine.hook_executor = HookExecutor(
            HooksConfig(
                hooks=[
                    LifecycleHookEntry(
                        event="message_submit",
                        command=f"{sys.executable} {script}",
                        io_dialect="claude",
                    )
                ]
            ),
            workspace,
        )
        await engine._handle_send_message_inner(
            SendMessageOp(content="do something dangerous"), "turn-1"
        )
        # Blocked before the model or session history saw the prompt.
        assert engine.session_messages == []
        events = handle.drain_events()
        status = [e for e in events if isinstance(e, StatusEvent)]
        assert status and "prompt rejected" in status[0].message
        assert any(isinstance(e, TurnCompleteEvent) for e in events)
    finally:
        await engine.shutdown_session()


async def test_executor_native_hooks_still_get_env_vars(tmp_path: Path) -> None:
    """Backward compat: native hooks keep DEEPSEEK_* env vars and native
    names on stdin."""
    capture = tmp_path / "env_seen.txt"
    script = tmp_path / "env_check.py"
    script.write_text(
        "import json, os, sys\n"
        "data = json.load(sys.stdin)\n"
        f"open({str(capture)!r}, 'w').write(\n"
        "    os.environ.get('DEEPSEEK_TOOL_NAME', '') + '|' + data['tool_name'])\n",
        encoding="utf-8",
    )
    cfg = HooksConfig(
        hooks=[
            LifecycleHookEntry(
                event="tool_call_before",
                command=f"{sys.executable} {script}",
            )
        ]
    )
    executor = HookExecutor(cfg, tmp_path)
    ctx = HookContext(tool_name="exec_shell", tool_args="{}", workspace=tmp_path)
    results = await executor.execute("tool_call_before", ctx)
    assert results[0].success
    assert capture.read_text(encoding="utf-8") == "exec_shell|exec_shell"
