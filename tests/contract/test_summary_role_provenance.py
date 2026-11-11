"""Compaction summaries must not attribute harness text to the human.

System reminders, soft-seam summaries, compaction bridges and cycle seeds all
ride the ``user`` role so the provider accepts them. The summarizer used to
label every ``user`` message "User:", so injected harness wording could be
recorded as a user request and then replayed as a user constraint after
compaction — the model would chase an instruction nobody gave.
"""

from __future__ import annotations

from typing import Any

import pytest

from deepseek_tui.engine.capacity import _create_summary
from deepseek_tui.protocol.messages import Message, MessageOrigin


class _CapturingClient:
    """Minimal ``LLMClient`` stand-in that records the summarizer request."""

    def __init__(self) -> None:
        self.request: Any = None

    def stream_chat_completion(self, request: Any) -> Any:
        self.request = request

        async def _events() -> Any:
            return
            yield  # pragma: no cover — empty async generator

        return _events()


def _summary_prompt(client: _CapturingClient) -> str:
    return client.request.messages[-1].text_content()


@pytest.mark.asyncio
async def test_synthetic_user_messages_are_excluded_from_authoritative_ledger() -> None:
    reminder = Message.user(
        "<system-reminder>Keep the checklist current.</system-reminder>"
    )
    reminder.origin = MessageOrigin.SYSTEM_REMINDER
    real = Message.user("Rename getCwd to getCurrentWorkingDirectory")
    real.origin = MessageOrigin.REAL_USER

    client = _CapturingClient()
    await _create_summary(client, [reminder, real], "deepseek-chat")  # type: ignore[arg-type]

    prompt = _summary_prompt(client)
    assert client.request.messages[:-1] == [reminder, real]
    assert "Rename getCwd to getCurrentWorkingDirectory" in prompt
    assert "Keep the checklist current" not in prompt


@pytest.mark.asyncio
async def test_summarizer_is_told_what_harness_means() -> None:
    real = Message.user("Ship the release")
    real.origin = MessageOrigin.REAL_USER

    client = _CapturingClient()
    await _create_summary(client, [real], "deepseek-chat")  # type: ignore[arg-type]

    assert client.request.system_prompt is None
    assert "runtime injections are not human requests" in _summary_prompt(client)


@pytest.mark.asyncio
async def test_assistant_messages_keep_their_label() -> None:
    client = _CapturingClient()
    await _create_summary(  # type: ignore[arg-type]
        client, [Message.assistant("I renamed the helper")], "deepseek-chat"
    )

    assert client.request.messages[0].role == "assistant"
    assert client.request.messages[0].text_content() == "I renamed the helper"
    assert "I renamed the helper" not in _summary_prompt(client)
