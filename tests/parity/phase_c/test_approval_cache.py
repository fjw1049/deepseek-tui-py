"""Parity tests for approval cache + Engine integration (Stage 3.next.1).

Mirror of Rust ``crates/tui/src/tools/approval_cache.rs`` (280 lines)
plus Engine integration that re-uses cached session grants.

Layered tests:

- TestApprovalKey: 8 Rust ``#[test]`` parities + 2 host-edge cases
- TestApprovalCache: insert/check/clear/len behavior
- TestEngineUsesCache: APPROVED_SESSION grant skips the second prompt
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.approval import ApprovalHandler
from deepseek_tui.engine.engine import Engine
from deepseek_tui.engine.events import (
    ApprovalResolvedEvent,
    EngineEvent,
    SandboxDeniedEvent,
    TurnCompleteEvent,
)
from deepseek_tui.engine.handle import EngineHandle
from deepseek_tui.execpolicy.approval_cache import (
    ApprovalCache,
    ApprovalCacheStatus,
    ApprovalKey,
    build_approval_key,
)
from deepseek_tui.execpolicy.models import (
    ApprovalDecision,
    ApprovalRequest,
)
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamToolCallComplete,
    ToolCall,
    Usage,
)
from deepseek_tui.tools.base import ToolCapability, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.registry import ToolRegistry

# --- Fingerprint parity ---------------------------------------------------


class TestApprovalKey:
    def test_shell_drops_flags(self) -> None:
        a = build_approval_key("exec_shell", {"command": "cargo build"})
        b = build_approval_key("exec_shell", {"command": "cargo build --release"})
        assert a == b

    def test_shell_different_commands(self) -> None:
        a = build_approval_key("exec_shell", {"command": "ls"})
        b = build_approval_key("exec_shell", {"command": "rm -rf /tmp"})
        assert a != b

    def test_shell_same_input_same_key(self) -> None:
        a = build_approval_key(
            "exec_shell", {"command": "cargo build --release"}
        )
        b = build_approval_key(
            "exec_shell", {"command": "cargo build --release"}
        )
        assert a == b

    def test_shell_empty_command(self) -> None:
        key = build_approval_key("exec_shell", {"command": ""})
        assert key.value == "shell:<empty>"

    def test_apply_patch_changes_path_diff(self) -> None:
        a = build_approval_key(
            "apply_patch", {"changes": [{"path": "a.rs", "content": "x"}]}
        )
        b = build_approval_key(
            "apply_patch", {"changes": [{"path": "b.rs", "content": "x"}]}
        )
        assert a != b

    def test_apply_patch_path_set_normalized(self) -> None:
        """Path order doesn't matter; duplicates collapse."""
        a = build_approval_key(
            "apply_patch",
            {"changes": [{"path": "a.rs"}, {"path": "b.rs"}]},
        )
        b = build_approval_key(
            "apply_patch",
            {"changes": [{"path": "b.rs"}, {"path": "a.rs"}, {"path": "a.rs"}]},
        )
        assert a == b

    def test_apply_patch_diff_text_fallback(self) -> None:
        patch_text = (
            "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"
        )
        key = build_approval_key("apply_patch", {"patch": patch_text})
        assert key.value.startswith("patch:")
        assert key.value != "patch:no_files"

    def test_apply_patch_no_files(self) -> None:
        assert (
            build_approval_key("apply_patch", {}).value
            == "patch:no_files"
        )

    def test_fetch_url_host(self) -> None:
        a = build_approval_key("fetch_url", {"url": "https://example.com/foo"})
        b = build_approval_key("fetch_url", {"url": "https://example.com/bar"})
        c = build_approval_key("fetch_url", {"url": "https://other.org"})
        assert a == b
        assert a != c
        assert a.value == "net:example.com"

    def test_generic_uses_tool_name(self) -> None:
        a = build_approval_key("read_file", {"path": "a.txt"})
        b = build_approval_key("read_file", {"path": "b.txt"})
        assert a == b
        assert a.value == "tool:read_file"


# --- Cache state ----------------------------------------------------------


class TestApprovalCache:
    def test_unknown_when_empty(self) -> None:
        cache = ApprovalCache()
        key = ApprovalKey("tool:foo")
        assert cache.check(key) is ApprovalCacheStatus.UNKNOWN

    def test_session_grant_returns_approved(self) -> None:
        cache = ApprovalCache()
        key = ApprovalKey("shell:cargo build")
        cache.insert(key, approved_for_session=True)
        assert cache.check(key) is ApprovalCacheStatus.APPROVED

    def test_one_shot_grant_returns_denied(self) -> None:
        cache = ApprovalCache()
        key = ApprovalKey("shell:rm -rf /")
        cache.insert(key, approved_for_session=False)
        assert cache.check(key) is ApprovalCacheStatus.DENIED

    def test_clear(self) -> None:
        cache = ApprovalCache()
        cache.insert(ApprovalKey("k"), approved_for_session=True)
        assert len(cache) == 1
        cache.clear()
        assert cache.is_empty()


# --- Engine integration ---------------------------------------------------


class _SilentClient(LLMClient):
    """LLM that emits one tool call, then DONE on every turn."""

    def __init__(self, tool_name: str = "do_thing") -> None:
        super().__init__()
        self._tool_name = tool_name
        self.calls = 0

    def stream_chat_completion(
        self, _request: MessageRequest
    ) -> AsyncIterator[object]:
        return self._stream()

    async def _stream(self) -> AsyncIterator[object]:
        self.calls += 1
        # Only emit a tool call on the first turn; on subsequent turns
        # (after the tool result is fed back in) terminate cleanly.
        if self.calls == 1:
            yield StreamToolCallComplete(
                tool_call=ToolCall(
                    id=f"call-{self.calls}",
                    name=self._tool_name,
                    arguments={},
                ),
            )
        yield StreamDone(usage=Usage(input_tokens=1, output_tokens=1))


class _CountingHandler(ApprovalHandler):
    """Approval handler that records every prompt and grants by script."""

    def __init__(self, decisions: list[ApprovalDecision]) -> None:
        self.decisions = decisions
        self.prompted: list[str] = []

    async def request_approval(
        self, tool_call_id: str, _request: ApprovalRequest
    ) -> ApprovalDecision:
        self.prompted.append(tool_call_id)
        return self.decisions.pop(0)


class _NoopTool(ToolSpec):
    """Tool that needs approval and just succeeds when run."""

    def __init__(self, name: str = "do_thing") -> None:
        self._name = name

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return "needs approval"

    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES, ToolCapability.REQUIRES_APPROVAL]

    async def execute(
        self, _input: dict[str, Any], _ctx: ToolContext
    ) -> ToolResult:
        return ToolResult(success=True, content="ok")


async def _drain(handle: EngineHandle) -> list[EngineEvent]:
    out: list[EngineEvent] = []
    async for ev in handle.events():
        out.append(ev)
        if isinstance(ev, TurnCompleteEvent):
            break
    return out


class TestEngineUsesCache:
    async def test_session_grant_skips_second_prompt(
        self, tmp_path: Path
    ) -> None:
        registry = ToolRegistry()
        registry.register(_NoopTool())
        ctx = ToolContext(working_directory=tmp_path)
        handler = _CountingHandler(
            decisions=[ApprovalDecision.APPROVED_SESSION]
        )

        # Turn 1 — model emits a tool call, handler is prompted once.
        client = _SilentClient()
        handle1 = EngineHandle()
        engine = Engine(
            handle=handle1,
            client=client,
            tool_registry=registry,
            tool_context=ctx,
            approval_handler=handler,
            max_tool_round_trips=2,
        )
        engine_task = __import__("asyncio").create_task(engine.run())
        try:
            await handle1.send_message(content="run it")
            await _drain(handle1)
        finally:
            await handle1.cancel()
            engine_task.cancel()
            try:
                await engine_task
            except BaseException:  # noqa: BLE001
                pass

        assert len(handler.prompted) == 1
        cache_key = build_approval_key("do_thing", {})
        assert engine.approval_cache.check(cache_key) is (
            ApprovalCacheStatus.APPROVED
        )

        # Turn 2 — same tool call. Handler should NOT be prompted again.
        client2 = _SilentClient()
        handle2 = EngineHandle()
        engine.client = client2  # reuse the same engine + cache
        engine.handle = handle2
        engine.turn_loop.client = client2
        engine_task = __import__("asyncio").create_task(engine.run())
        try:
            await handle2.send_message(content="again")
            await _drain(handle2)
        finally:
            await handle2.cancel()
            engine_task.cancel()
            try:
                await engine_task
            except BaseException:  # noqa: BLE001
                pass

        # Same number of prompts as before — the fingerprint cache
        # (and the exec_policy's own session cache) both prevent the
        # re-prompt. That's the whole point of the Stage 3.next.1 grant.
        assert len(handler.prompted) == 1

    async def test_cache_short_circuits_prompt(self, tmp_path: Path) -> None:
        """Directly prime ApprovalCache and verify the handler is bypassed.

        Uses a non-session tool decision to prove the *fingerprint* cache
        (not the exec_policy session cache) is what prevents the prompt.
        """
        registry = ToolRegistry()
        registry.register(_NoopTool())
        ctx = ToolContext(working_directory=tmp_path)
        handler = _CountingHandler(decisions=[ApprovalDecision.APPROVED])

        handle = EngineHandle()
        engine = Engine(
            handle=handle,
            client=_SilentClient(),
            tool_registry=registry,
            tool_context=ctx,
            approval_handler=handler,
        )
        # Pre-seed the fingerprint cache with a session grant.
        cache_key = build_approval_key("do_thing", {})
        engine.approval_cache.insert(cache_key, approved_for_session=True)

        task = __import__("asyncio").create_task(engine.run())
        try:
            await handle.send_message(content="go")
            events = await _drain(handle)
        finally:
            await handle.cancel()
            task.cancel()
            try:
                await task
            except BaseException:  # noqa: BLE001
                pass

        # Handler must not have been prompted.
        assert handler.prompted == []
        # ApprovalResolvedEvent carries reason="cached_session".
        resolved = [e for e in events if isinstance(e, ApprovalResolvedEvent)]
        assert any(e.reason == "cached_session" for e in resolved), events

    async def test_one_shot_grant_re_prompts(self, tmp_path: Path) -> None:
        registry = ToolRegistry()
        registry.register(_NoopTool())
        ctx = ToolContext(working_directory=tmp_path)
        # First call grants APPROVED (one-shot), second call denies.
        handler = _CountingHandler(
            decisions=[ApprovalDecision.APPROVED, ApprovalDecision.DENIED]
        )
        engine = Engine(
            handle=EngineHandle(),
            client=_SilentClient(),
            tool_registry=registry,
            tool_context=ctx,
            approval_handler=handler,
        )

        # Round 1: APPROVED → cache.insert(session=False)
        engine.handle = EngineHandle()
        engine.turn_loop.client = engine.client = _SilentClient()
        task1 = __import__("asyncio").create_task(engine.run())
        try:
            await engine.handle.send_message(content="x")
            await _drain(engine.handle)
        finally:
            await engine.handle.cancel()
            task1.cancel()
            try:
                await task1
            except BaseException:  # noqa: BLE001
                pass

        # Round 2: cache says DENIED (one-shot consumed) → handler runs again
        # and this time denies the call.
        engine.handle = EngineHandle()
        engine.turn_loop.client = engine.client = _SilentClient()
        task2 = __import__("asyncio").create_task(engine.run())
        try:
            await engine.handle.send_message(content="x")
            events = await _drain(engine.handle)
        finally:
            await engine.handle.cancel()
            task2.cancel()
            try:
                await task2
            except BaseException:  # noqa: BLE001
                pass

        assert len(handler.prompted) == 2
        denied = [e for e in events if isinstance(e, SandboxDeniedEvent)]
        assert denied, "second round should have denied the tool call"
