"""Attribute prefix-cache misses to whatever rewrote the request.

``prefix_cache round=… ratio=…`` reports that the provider's cache dropped; it
never says why. Because the provider matches from the start of the payload, a
drop means some unit the previous request already sent came back different —
the static prefix, or a message that history rewriting touched. Digesting each
unit per round turns that into an answer: the first mismatch names the culprit.

Only ``role`` and ``content`` feed a message digest. ``origin`` is session-local
and never reaches the wire, so folding it in would report breaks the provider
cannot see — but it makes an excellent label once a break is found.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from deepseek_tui.protocol.messages import Message


def fingerprint_request(
    system_prompt: str | None,
    messages: list[Message],
    tools: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Digest each cacheable unit, in the order the provider reads them.

    Slot 0 is the static prefix — the system prompt plus the tool schemas, which
    sit ahead of every message and share their cache lifetime. One digest per
    message follows.
    """
    units = [_digest([system_prompt or "", tools or []])]
    units.extend(
        _digest([message.role.value, [block.model_dump() for block in message.content]])
        for message in messages
    )
    return units


def first_divergence(previous: list[str], current: list[str]) -> int | None:
    """Index of the first unit that changed, or ``None`` when nothing did.

    ``None`` covers both the pure-append case and an unchanged request, which is
    what a cache can serve in full. Trailing units that only exist in one of the
    two are not a break: a prefix still matches as a prefix.
    """
    for index, (before, after) in enumerate(zip(previous, current, strict=False)):
        if before != after:
            return index
    return None


def describe_break(index: int, messages: list[Message]) -> str:
    """Name the unit at *index* so a log line points at something actionable."""
    if index == 0:
        return "static_prefix(system_prompt|tools)"
    position = index - 1
    if position >= len(messages):
        return f"message[{position}] (dropped)"
    message = messages[position]
    origin = message.origin.value if message.origin else "-"
    return f"message[{position}] role={message.role.value} origin={origin}"


def _digest(payload: object) -> str:
    # Deliberately not ``sort_keys``: the provider sees whatever key order the
    # serializer emits, so normalising it here would hide real instability in,
    # say, tool-schema construction.
    encoded = json.dumps(payload, default=str, ensure_ascii=False)
    return hashlib.blake2b(encoded.encode("utf-8"), digest_size=8).hexdigest()
