"""General regressions from the browser/CUA pipeline audit (no task/site fixtures)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deepseek_tui.client.base import MeteredLLMClient, _media_ledger_context
from deepseek_tui.engine.completion import TurnFacts
from deepseek_tui.engine.orchestrator.tooling import ToolExecutionMixin
from deepseek_tui.engine.usage_ledger import TurnUsageLedger
from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import Usage
from deepseek_tui.tools.browser import BrowserUseTool
from deepseek_tui.tools.registry import ToolContext
from tests.test_usage_ledger import _UsageClient


async def test_metered_stream_can_close_in_another_task_without_losing_usage():
    ledger = TurnUsageLedger()
    stream = MeteredLLMClient(
        _UsageClient(Usage(input_tokens=10, output_tokens=7)), ledger
    ).stream_chat_completion(MessageRequest(model="test", messages=[]))
    await anext(stream)
    assert _media_ledger_context.get() is None
    await asyncio.create_task(stream.aclose())
    assert ledger.totals()["output_tokens"] == 7
    await stream.aclose()
    assert len(ledger.items) == 1


def test_unrelated_navigation_does_not_erase_failed_navigation():
    f = TurnFacts()
    f.record(
        "browser_use", {"action": "open", "url": "https://a.test"}, success=False, error="closed"
    )
    f.record("browser_use", {"action": "open", "url": "https://b.test"}, success=True)
    assert f.outcome([], [])["status"] == "partial"


def test_ui_observation_is_not_task_verification():
    f = TurnFacts()
    f.record("browser_use", {"action": "status"}, success=True)
    assert f.outcome([], [])["status"] == "completed_unverified"


def test_paging_schema_only_advertises_accepted_input_names():
    props = BrowserUseTool().input_schema()["properties"]
    for key in ("text_offset", "element_offset", "shadow_path"):
        assert "scope_selector" not in props[key]["description"]
        assert "scope_shadow_path" not in props[key]["description"]
    assert "scope_ref" in props["text_offset"]["description"]


@pytest.mark.parametrize("alias", [False, True])
async def test_unattended_help_is_preserved_without_waiting(alias, tmp_path):
    facts = TurnFacts()
    request = AsyncMock(return_value={"success": True, "content": "waiting"})
    context = ToolContext(
        working_directory=tmp_path,
        metadata={
            "unattended": True,
            "turn_facts": facts,
            "runtime_thread_id": "t",
            "browser_service": SimpleNamespace(),
            "request_browser_assistance": request,
        },
    )
    if alias:
        result = await BrowserUseTool().execute(
            {"action": "request_assistance", "reason": "captcha"}, context
        )
    else:
        engine = SimpleNamespace(tool_context=context)
        result = await ToolExecutionMixin._await_user_input(
            engine, "q", {"kind": "action", "surface": "browser", "reason": "captcha"}
        )
    assert result.metadata["needs_assistance"]["reason"] == "captcha"
    assert facts.outcome([], [])["status"] == "needs_assistance"
    assert facts.outcome([], [])["requests"][0]["reason"] == "captcha"
    request.assert_not_awaited()


async def test_summary_truncation_increases_budget_and_closes_each_stream():
    from deepseek_tui.engine.capacity import CompactionConfig, compact_messages_safe
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.responses import StreamDone, StreamTextDelta

    budgets, closed = [], []

    class Client:
        async def stream_chat_completion(self, request):
            budgets.append(request.max_tokens)
            try:
                yield StreamTextDelta(
                    text=("### Goal\nPreserve user requirements.\n"
                          "### Next step\nContinue verification.")
                )
                yield StreamDone(truncated=len(budgets) == 1)
            finally:
                closed.append(request.max_tokens)

    messages = [Message.user("Requirement " + str(i) + " x" * 3000) for i in range(20)]
    result = await compact_messages_safe(Client(), messages, CompactionConfig(keep_recent_tokens=0))
    assert result.success
    assert budgets[1] == 2 * budgets[0]
    assert closed == budgets


@pytest.mark.parametrize("provider_overflow", [False, True])
async def test_unchanged_compaction_is_not_repeated(provider_overflow):
    from deepseek_tui.engine.turn import TurnLoop, TurnOutcomeStatus
    from deepseek_tui.protocol.messages import Message
    from deepseek_tui.protocol.responses import StreamError
    from tests.engine.test_midstream_resample import _ScriptedClient

    client = _ScriptedClient(
        [[StreamError(message="maximum context length exceeded", retryable=False)]]
    )
    compact = AsyncMock(side_effect=lambda messages: messages)
    request = MessageRequest(
        model="deepseek-chat",
        messages=[Message.user("x " * (100000 if not provider_overflow else 1))],
    )
    result = await TurnLoop(client, compact_fn=compact).run(
        request=request, emit=AsyncMock(), cancel_event=asyncio.Event(), tools=None
    )
    assert result.outcome is TurnOutcomeStatus.CONTEXT_OVERFLOW
    assert "no progress" in result.error_message
    assert compact.await_count == 1


def test_retry_with_explicit_operation_id_clears_only_that_operation():
    facts = TurnFacts()
    facts.record(
        "browser_use", {"action": "click", "operation_id": "one", "ref": "a"}, success=False
    )
    facts.record(
        "browser_use", {"action": "click", "operation_id": "two", "ref": "b"}, success=False
    )
    facts.record(
        "browser_use", {"action": "click", "operation_id": "one", "ref": "c"}, success=True
    )
    assert len(facts.failures) == 1
