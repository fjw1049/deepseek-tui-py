"""Unified context-pressure signal and ratio-tier policy.

All compaction layers (L0 prune, soft seams, rewrite, cycle) should read
:func:`measure_context_pressure` instead of inventing absolute thresholds
tuned to a single 1M window.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from deepseek_tui.config.providers import (
    DEFAULT_CONTEXT_WINDOW_TOKENS,
    context_window_for_model,
)
from deepseek_tui.protocol.messages import Message, MessageOrigin, Role, TextBlock

# Ratio ladder (confirmed product policy).
RATIO_SEAM_L1 = 0.20
RATIO_SEAM_L2 = 0.40
RATIO_L0_PRUNE = 0.50
RATIO_SEAM_L3 = 0.55
RATIO_REWRITE = 0.75
RATIO_CYCLE = 0.90
RATIO_AUTO_FLOOR = 0.20  # below this: ingress truncation only

COMPACTION_BRIDGE_PREFIX = (
    "The conversation history before this point was compacted into the "
    "following summary:\n"
)
ARCHIVED_CONTEXT_OPEN = "<archived_context>"
ARCHIVED_CONTEXT_CLOSE = "</archived_context>"
SYSTEM_REMINDER_OPEN = "<system-reminder>"
SYSTEM_REMINDER_CLOSE = "</system-reminder>"
USER_QUERY_OPEN = "<user_query>"
USER_QUERY_CLOSE = "</user_query>"
LOCAL_CONTEXT_OPEN = "<local_context>"
LOCAL_CONTEXT_CLOSE = "</local_context>"
PRIOR_REQUESTS_OPEN = "<prior_user_requests>"
PRIOR_REQUESTS_CLOSE = "</prior_user_requests>"

# Everything else a compaction discards is re-fetchable: code is on disk,
# tool output can be re-run, git state can be re-queried. What the human
# asked for exists nowhere else, so it is the one class that must survive
# verbatim. Cap the block so a very long session cannot crowd out the
# working context; on overflow drop the middle, since the earliest requests
# set the frame and the latest ones are the live ones.
PRIOR_REQUESTS_MAX_CHARS = 20_000
# One pasted log or stack trace must not be able to eat the whole budget and
# push out every other request. Trimming a single long entry loses less than
# dropping the short entries around it.
PRIOR_REQUESTS_MAX_ENTRY_CHARS = 2_000

_USER_QUERY_RE = re.compile(
    r"<user_query>\s*(.*?)\s*</user_query>",
    re.DOTALL | re.IGNORECASE,
)
_PRIOR_REQUESTS_RE = re.compile(
    r"<prior_user_requests>\s*(.*?)\s*</prior_user_requests>",
    re.DOTALL | re.IGNORECASE,
)
# Anchored at column 0, and every continuation line is indented on the way
# out, so a user request that itself contains "1. do the thing" cannot be
# mistaken for the start of the next entry when the block is read back.
_REQUEST_ENTRY_RE = re.compile(
    r"^\d+\. (.*?)(?=\n\d+\. |\n\[\.\.\. |\Z)",
    re.DOTALL | re.MULTILINE,
)
_ENTRY_INDENT = "   "

PressureSource = Literal["real", "estimate"]


@dataclass(frozen=True, slots=True)
class ContextPressure:
    """Snapshot of how full the model context is."""

    tokens: int
    window: int
    ratio: float
    source: PressureSource

    @property
    def at_or_above(self) -> float:
        return self.ratio


def measure_context_pressure(
    model: str,
    messages: list[Message],
    *,
    real_input_tokens: int = 0,
    system_prompt: str | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> ContextPressure:
    """Prefer provider ``input_tokens``; fall back to a char-based estimate."""
    window = max(1, int(context_window_for_model(model) or DEFAULT_CONTEXT_WINDOW_TOKENS))
    if real_input_tokens > 0:
        tokens = int(real_input_tokens)
        source: PressureSource = "real"
    else:
        from deepseek_tui.engine.context import estimate_tokens, estimated_input_tokens

        tokens = estimated_input_tokens(messages)
        if system_prompt:
            tokens += estimate_tokens(system_prompt)
        if tools:
            try:
                import json

                tokens += estimate_tokens(json.dumps(tools))
            except (TypeError, ValueError):
                pass
        source = "estimate"
    ratio = min(1.5, tokens / window)  # allow >1.0 under overflow
    return ContextPressure(tokens=tokens, window=window, ratio=ratio, source=source)


def thresholds_for_window(window: int) -> dict[str, int]:
    """Absolute token thresholds derived from a context window."""
    w = max(1, int(window))
    return {
        "seam_l1": int(w * RATIO_SEAM_L1),
        "seam_l2": int(w * RATIO_SEAM_L2),
        "l0_prune": int(w * RATIO_L0_PRUNE),
        "seam_l3": int(w * RATIO_SEAM_L3),
        "rewrite": int(w * RATIO_REWRITE),
        "cycle": int(w * RATIO_CYCLE),
        "auto_floor": int(w * RATIO_AUTO_FLOOR),
    }


def wrap_system_reminder(body: str) -> str:
    """Wrap injected runtime text in a Claude-Code-style reminder envelope."""
    trimmed = body.strip()
    if trimmed.startswith(SYSTEM_REMINDER_OPEN):
        return trimmed
    return f"{SYSTEM_REMINDER_OPEN}\n{trimmed}\n{SYSTEM_REMINDER_CLOSE}"


_FAKE_REMINDER_RE = re.compile(
    r"(</?)\s*(system-reminder)(?:\s[^<>]*)?\s*(/?>)",
    re.IGNORECASE,
)


def neutralize_fake_system_reminders(text: str) -> str:
    """Defuse ``<system-reminder>`` tags found in untrusted turn content.

    Engine-injected reminders travel as their own messages and never pass
    through user-input processing — so any reminder tag inside raw user
    text (typed, pasted, or inlined via @file expansion) is either a
    quote or an injection attempt. Rewriting the tag name keeps the
    content readable while stripping the authority our prompt grants to
    real reminders. Found by the golden scenario
    ``test_fake_system_reminder_does_not_leak_prompt``.
    """
    return _FAKE_REMINDER_RE.sub(r"\1user-quoted-reminder\3", text)


def format_user_query_message(query: str) -> str:
    """Format a real user goal for replay after compaction/cycle."""
    trimmed = query.strip()
    if not trimmed:
        return ""
    if trimmed.startswith(USER_QUERY_OPEN):
        return trimmed
    return f"{USER_QUERY_OPEN}\n{trimmed}\n{USER_QUERY_CLOSE}"


def extract_user_query_text(text: str) -> str:
    """Pull the inner ``<user_query>`` body, or fall back to the query portion."""
    if not text:
        return ""
    match = _USER_QUERY_RE.search(text)
    if match:
        return match.group(1).strip()
    # Drop structured attachments if present (new or legacy glue).
    cut = text
    for marker in (LOCAL_CONTEXT_OPEN, "\n\n---\n", "\n---\n"):
        idx = cut.find(marker)
        if idx >= 0:
            cut = cut[:idx]
            break
    return cut.strip()


def is_compaction_bridge_message(message: Message) -> bool:
    """True when *message* is our rewrite bridge carrier."""
    if message.origin is MessageOrigin.COMPACTION_BRIDGE:
        return True
    if message.role != Role.USER:
        return False
    text = message.text_content()
    return bool(text) and COMPACTION_BRIDGE_PREFIX in text and ARCHIVED_CONTEXT_OPEN in text


SYNTHETIC_ORIGINS = frozenset(
    {
        MessageOrigin.SYSTEM_REMINDER,
        MessageOrigin.COMPACTION_BRIDGE,
        MessageOrigin.SOFT_SEAM,
        MessageOrigin.CYCLE_SEED,
        # Carries the user's words but is not a fresh turn — treating it as
        # one would make the whole ledger read as "the current request".
        MessageOrigin.REQUEST_LEDGER,
    }
)


def is_synthetic_user_message(message: Message) -> bool:
    """True for injected user-role messages that are not the human's request.

    Provenance only. This used to fall back to sniffing text prefixes when
    ``origin`` was absent, which made the answer depend on what the human
    happened to type: paste a log starting with ``[System]`` and your request
    was classified as harness output, so compaction would replay the previous
    goal and the summarizer would attribute your words to the machine. The
    sniffing now runs once, at the deserialization boundary, where the only
    messages missing an origin are genuinely old ones — see
    :func:`infer_legacy_origin`.
    """
    if message.role != Role.USER:
        return True
    if message.origin in SYNTHETIC_ORIGINS:
        return True
    if message.origin is MessageOrigin.REAL_USER:
        return False
    # No origin: a live construction site that doesn't tag its messages, and
    # every one of those carries real user text. Empty is not a request.
    return not message.text_content().strip()


def infer_legacy_origin(message: Message) -> MessageOrigin | None:
    """Guess provenance for a message persisted before ``origin`` existed.

    These are the prefix heuristics that used to live in
    :func:`is_synthetic_user_message`, kept verbatim so old sessions keep
    classifying the way they always did. What changed is where they run: at
    the boundary where untagged data enters, once per message, instead of on
    every provenance question forever. A live message reaching here would be
    a bug in whichever construction site failed to tag it — hence the
    contract test that pins the loader as the sole entry point.
    """
    if message.role != Role.USER or message.origin is not None:
        return message.origin
    text = message.text_content().lstrip()
    if not text:
        return None
    if is_compaction_bridge_message(message):
        return MessageOrigin.COMPACTION_BRIDGE
    # Before the generic reminder check: seams ride inside a reminder
    # envelope, so testing for the envelope first would label every one of
    # them SYSTEM_REMINDER. The old rule looked for the bare
    # ``<archived_context>`` alongside ``level="``, which a real seam can
    # never satisfy — it always carries attributes, so the opening tag is
    # never bare. Matching the prefix is what ``seam.py`` itself does.
    if '<archived_context level="' in text:
        return MessageOrigin.SOFT_SEAM
    if text.startswith(SYSTEM_REMINDER_OPEN) or "<system-reminder>" in text[:80]:
        return MessageOrigin.SYSTEM_REMINDER
    # Both the current envelope and the bracket headers it wraps: seeds
    # written before the split ship inside a reminder and are caught above,
    # so these headers still have to be recognised on their own.
    if text.startswith("<cycle_carryover>"):
        return MessageOrigin.CYCLE_SEED
    if text.startswith("[CYCLE STATE") or text.startswith("[CYCLE BRIEFING"):
        return MessageOrigin.CYCLE_SEED
    if text.startswith("[System]"):
        return MessageOrigin.SYSTEM_REMINDER
    # Pre-ledger compaction replayed the goal in this shape. It is the user's
    # own words, so REQUEST_LEDGER is the honest label: synthetic carrier,
    # verbatim content that nothing may paraphrase away.
    if text.startswith("**Important**: The user asked"):
        return MessageOrigin.REQUEST_LEDGER
    return None


def messages_from_dicts(raw_messages: Iterable[Any]) -> list[Message]:
    """Rebuild persisted messages, backfilling provenance for legacy ones.

    The only sanctioned way to turn stored dicts back into ``Message``
    objects. Loading them directly would silently produce a transcript where
    every reminder, seam and bridge reads as something the human said.
    """
    out: list[Message] = []
    for item in raw_messages:
        message = item if isinstance(item, Message) else Message.model_validate(item)
        inferred = infer_legacy_origin(message)
        if inferred is not message.origin:
            message = message.model_copy(update={"origin": inferred})
        out.append(message)
    return out


def find_last_real_user_query(messages: list[Message]) -> str | None:
    """Return the latest real user goal text (without attachment bodies)."""
    for message in reversed(messages):
        if is_synthetic_user_message(message):
            continue
        query = extract_user_query_text(message.text_content())
        if query:
            return query
    return None


def parse_user_requests_block(text: str) -> list[str]:
    """Pull the numbered entries back out of a rendered ledger block."""
    match = _PRIOR_REQUESTS_RE.search(text or "")
    if not match:
        return []
    body = match.group(1)
    out: list[str] = []
    for raw in _REQUEST_ENTRY_RE.findall(body):
        lines = raw.split("\n")
        unindented = [lines[0]] + [
            line[len(_ENTRY_INDENT) :] if line.startswith(_ENTRY_INDENT) else line
            for line in lines[1:]
        ]
        entry = "\n".join(unindented).strip()
        if entry:
            out.append(entry)
    return out


def collect_user_requests(messages: list[Message]) -> list[str]:
    """Every request the human has made this session, oldest first.

    Reads both fresh ``REAL_USER`` turns and any ledger carrier left behind
    by an earlier compaction, so the list rebuilds itself from the transcript
    instead of relying on engine state that a restart or a sub-agent would
    not have. Duplicates collapse: the carrier and the replayed latest query
    overlap by construction.
    """
    requests: list[str] = []
    seen: set[str] = set()

    def _add(entry: str) -> None:
        trimmed = entry.strip()
        if trimmed and trimmed not in seen:
            seen.add(trimmed)
            requests.append(trimmed)

    for message in messages:
        if message.origin is MessageOrigin.REQUEST_LEDGER:
            for entry in parse_user_requests_block(message.text_content()):
                _add(entry)
            continue
        if is_synthetic_user_message(message):
            continue
        _add(extract_user_query_text(message.text_content()))
    return requests


_TRUNCATION_MARKER = "\n[... truncated ...]\n"


def _clip_request(entry: str) -> str:
    """Keep both ends of an over-long request: the ask and any closing caveat.

    Sized so the result is itself under the cap, which keeps the operation
    idempotent — a ledger that gets re-rendered on every compaction must not
    shave a little more off the same entry each time.
    """
    if len(entry) <= PRIOR_REQUESTS_MAX_ENTRY_CHARS:
        return entry
    half = (PRIOR_REQUESTS_MAX_ENTRY_CHARS - len(_TRUNCATION_MARKER)) // 2
    return f"{entry[:half]}{_TRUNCATION_MARKER}{entry[-half:]}"


def format_user_requests_block(
    requests: list[str], *, max_chars: int = PRIOR_REQUESTS_MAX_CHARS
) -> str:
    """Render the ledger, dropping middle entries if it grows too large."""
    entries = [
        _clip_request(r.strip()) for r in requests if r and r.strip()
    ]
    if not entries:
        return ""

    kept: list[str] = list(entries)
    dropped = 0
    # Trim from the middle: the first requests frame the task and the last
    # ones are live, so both ends outrank whatever sits between them.
    while len(kept) > 2 and sum(len(e) for e in kept) > max_chars:
        kept.pop(len(kept) // 2)
        dropped += 1

    lines = [
        PRIOR_REQUESTS_OPEN,
        "Everything the user has asked for in this session, in order. Their "
        "wording is the only record of it — earlier items stay binding unless "
        "the user withdrew them, and the last item is the current request.",
        "",
    ]
    gap_at = len(kept) // 2
    for i, entry in enumerate(kept):
        if dropped and i == gap_at:
            lines.append(f"[... {dropped} earlier request(s) omitted for length ...]")
        head, *tail = entry.split("\n")
        lines.append(f"{i + 1}. {head}")
        # Continuation lines are indented so a numbered list inside a request
        # cannot look like the next entry when this block is parsed back.
        lines.extend(f"{_ENTRY_INDENT}{line}" for line in tail)
    lines.append(PRIOR_REQUESTS_CLOSE)
    return "\n".join(lines)


def _messages_contain_real_query(messages: list[Message], query: str) -> bool:
    needle = query.strip()
    if not needle:
        return True
    for message in messages:
        if is_synthetic_user_message(message):
            continue
        text = message.text_content()
        if needle == extract_user_query_text(text) or needle in text:
            return True
    return False


def extract_compaction_bridge_text(messages: list[Message]) -> str | None:
    """Return the text of the first rewrite bridge message, if any."""
    for msg in messages:
        if not is_compaction_bridge_message(msg):
            continue
        text = msg.text_content()
        if text:
            return text
    return None


def build_compaction_bridge_text(
    summary: str,
    *,
    working_set_paths: list[str] | None = None,
) -> str:
    """Format a user-role bridge message body (cache-friendly composition)."""
    body = f"{COMPACTION_BRIDGE_PREFIX}{ARCHIVED_CONTEXT_OPEN}\n{summary.strip()}\n{ARCHIVED_CONTEXT_CLOSE}"
    if working_set_paths:
        body += "\n\n**Working Set Files:**\n"
        for path in working_set_paths[:10]:
            body += f"- {path}\n"
    return body


def prepend_compaction_bridge(
    messages: list[Message],
    bridge_text: str,
    *,
    last_real_query: str | None = None,
    prior_requests: list[str] | None = None,
) -> list[Message]:
    """Return messages with a leading bridge and the user's request history.

    The summary in *bridge_text* is a paraphrase and drifts a little further
    on every re-summarisation. *prior_requests* rides alongside it verbatim,
    so a constraint the user stated twenty turns ago does not depend on the
    summarizer having chosen to keep it.
    """
    from deepseek_tui.protocol.messages import Message as Msg

    # Drop any carrier from an earlier compaction: the one we are about to
    # render already absorbed its entries, so keeping it would stack a second
    # copy of the same list on every pass.
    rest = [
        m
        for m in messages
        if not is_compaction_bridge_message(m)
        and m.origin is not MessageOrigin.REQUEST_LEDGER
    ]
    out: list[Message] = [
        Msg.user(bridge_text, origin=MessageOrigin.COMPACTION_BRIDGE),
    ]
    ledger_block = format_user_requests_block(prior_requests or [])
    if ledger_block:
        out.append(Msg.user(ledger_block, origin=MessageOrigin.REQUEST_LEDGER))
    query = (last_real_query or "").strip()
    if query and not _messages_contain_real_query(rest, query):
        out.append(
            Msg.user(
                format_user_query_message(query),
                origin=MessageOrigin.REAL_USER,
            )
        )
    out.extend(rest)
    return out
