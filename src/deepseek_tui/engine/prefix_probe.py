"""Attribute prefix-cache misses to whatever rewrote the request.

``prefix_cache round=… ratio=…`` reports that the provider's cache dropped; it
never says why. Because the provider matches from the start of the payload, a
drop means some unit the previous request already sent came back different —
the static prefix, or a message that history rewriting touched. Digesting each
unit per round turns that into an answer: the first mismatch names the culprit.

System text and tool schemas are fingerprinted separately so diagnostics can
name which static component moved. Only ``role`` and ``content`` feed a message
digest. ``origin`` is session-local and never reaches the wire, so folding it
in would report breaks the provider cannot see — but it makes an excellent
label once a break is found.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from deepseek_tui.protocol.messages import Message

FingerprintUnit = tuple[str, object]


def fingerprint_units(units: list[FingerprintUnit]) -> list[str]:
    """Digest provider-rendered cache units without logging their contents."""
    return [_digest(payload) for _, payload in units]


def unit_token_weights(units: list[FingerprintUnit]) -> list[int]:
    """Estimate token weight for provider-rendered cache units."""
    from deepseek_tui.engine.context import estimate_tokens

    return [estimate_tokens(_encode(payload)) for _, payload in units]


def fingerprint_request(
    system_prompt: str | None,
    messages: list[Message],
    tools: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Digest each conceptual cacheable unit.

    Slots 0 and 1 are system text and tool schemas. One digest per message
    follows. Providers may serialise the two static components in different
    orders, so callers conservatively treat a change in either as zero reuse.
    """
    units: list[FingerprintUnit] = [
        ("system_prompt", system_prompt or ""),
        ("tools", tools or []),
    ]
    units.extend(
        (
            f"message[{index}]",
            [message.role.value, [block.model_dump() for block in message.content]],
        )
        for index, message in enumerate(messages)
    )
    return fingerprint_units(units)


def request_token_weights(
    system_prompt: str | None,
    messages: list[Message],
    tools: list[dict[str, Any]] | None = None,
) -> list[int]:
    """Estimate each fingerprint unit's token weight for useful percentages."""
    units: list[FingerprintUnit] = [
        ("system_prompt", system_prompt or ""),
        ("tools", tools or []),
    ]
    units.extend(
        (
            f"message[{index}]",
            [message.role.value, [block.model_dump() for block in message.content]],
        )
        for index, message in enumerate(messages)
    )
    return unit_token_weights(units)


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
        return "system_prompt"
    if index == 1:
        return "tools"
    position = index - 2
    if position >= len(messages):
        return f"message[{position}] (dropped)"
    message = messages[position]
    origin = message.origin.value if message.origin else "-"
    return f"message[{position}] role={message.role.value} origin={origin}"


def _digest(payload: object) -> str:
    # Deliberately not ``sort_keys``: the provider sees whatever key order the
    # serializer emits, so normalising it here would hide real instability in,
    # say, tool-schema construction.
    encoded = _encode(payload)
    return hashlib.blake2b(encoded.encode("utf-8"), digest_size=8).hexdigest()


def _encode(payload: object) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False)
