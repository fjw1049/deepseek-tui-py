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
    return client.request.messages[0].text_content()


@pytest.mark.asyncio
async def test_synthetic_user_messages_are_labelled_harness() -> None:
    reminder = Message.user(
        "<system-reminder>Keep the checklist current.</system-reminder>"
    )
    reminder.origin = MessageOrigin.SYSTEM_REMINDER
    real = Message.user("Rename getCwd to getCurrentWorkingDirectory")
    real.origin = MessageOrigin.REAL_USER

    client = _CapturingClient()
    await _create_summary(client, [reminder, real], "deepseek-chat")  # type: ignore[arg-type]

    prompt = _summary_prompt(client)
    assert "Harness: <system-reminder>Keep the checklist current." in prompt
    assert "User: Rename getCwd to getCurrentWorkingDirectory" in prompt
    assert "User: <system-reminder>" not in prompt


@pytest.mark.asyncio
async def test_summarizer_is_told_what_harness_means() -> None:
    real = Message.user("Ship the release")
    real.origin = MessageOrigin.REAL_USER

    client = _CapturingClient()
    await _create_summary(client, [real], "deepseek-chat")  # type: ignore[arg-type]

    system_prompt = client.request.system_prompt
    assert "Harness:" in system_prompt
    assert "not the human" in system_prompt


@pytest.mark.asyncio
async def test_assistant_messages_keep_their_label() -> None:
    client = _CapturingClient()
    await _create_summary(  # type: ignore[arg-type]
        client, [Message.assistant("I renamed the helper")], "deepseek-chat"
    )

    assert "Assistant: I renamed the helper" in _summary_prompt(client)
