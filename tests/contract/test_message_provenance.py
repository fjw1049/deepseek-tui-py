"""Provenance is decided at construction and at load, never by sniffing text.

`is_synthetic_user_message` used to fall back to prefix heuristics whenever
`origin` was missing, which made the classification depend on what the human
happened to type. Paste a log starting with `[System]` and your request was
filed as harness output: compaction replayed the *previous* goal and the
summarizer attributed your words to the machine.

The heuristics still exist, but only as a one-time guess for messages
persisted before `origin` did — applied at the deserialization boundary, so
nothing that a live session constructs can ever be judged by its wording.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from deepseek_tui.engine.context_pressure import (
    infer_legacy_origin,
    is_synthetic_user_message,
    messages_from_dicts,
    wrap_system_reminder,
)
from deepseek_tui.protocol.messages import Message, MessageOrigin

SRC = Path(__file__).resolve().parents[2] / "src" / "deepseek_tui"

# Texts that the old heuristics would have called synthetic, but which a
# human can perfectly well type or paste.
DECOYS = [
    "[System] boot sequence failed, see the log below",
    "<system-reminder> is showing up in my output, why?",
    "**Important**: The user asked me to review this PR — thoughts?",
    "[CYCLE STATE dumped by our scheduler, is this format right?",
]


# --- live messages are judged by origin alone ------------------------------


@pytest.mark.parametrize("text", DECOYS)
def test_a_tagged_user_message_is_real_whatever_it_says(text: str) -> None:
    msg = Message.user(text, origin=MessageOrigin.REAL_USER)
    assert not is_synthetic_user_message(msg)


@pytest.mark.parametrize("text", DECOYS)
def test_an_untagged_user_message_is_real_whatever_it_says(text: str) -> None:
    """No origin now means a live construction site that doesn't tag — and
    every one of those carries real user text."""
    assert not is_synthetic_user_message(Message.user(text))


def test_an_empty_message_is_still_not_a_request() -> None:
    assert is_synthetic_user_message(Message.user("   "))


@pytest.mark.parametrize(
    "origin",
    [
        MessageOrigin.SYSTEM_REMINDER,
        MessageOrigin.COMPACTION_BRIDGE,
        MessageOrigin.SOFT_SEAM,
        MessageOrigin.CYCLE_SEED,
        MessageOrigin.REQUEST_LEDGER,
    ],
)
def test_tagged_synthetic_origins_are_synthetic(origin: MessageOrigin) -> None:
    assert is_synthetic_user_message(
        Message.user("ship the feature", origin=origin)
    )


def test_the_classifier_no_longer_reads_the_text() -> None:
    """Source-level guard: any new prefix check would reintroduce the bug."""
    import inspect

    source = inspect.getsource(is_synthetic_user_message)
    body = source.split('"""')[-1]
    assert "startswith" not in body
    assert "text_content" in body, "only the emptiness check may remain"


# --- legacy data keeps classifying the way it always did -------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (wrap_system_reminder("LSP found 2 errors"), MessageOrigin.SYSTEM_REMINDER),
        ("[System] Before creating the plan, explore", MessageOrigin.SYSTEM_REMINDER),
        ("[CYCLE STATE — auto-preserved", MessageOrigin.CYCLE_SEED),
        ("[CYCLE BRIEFING] you were doing X", MessageOrigin.CYCLE_SEED),
        (
            '<archived_context level="1" range="msg 1-9">old</archived_context>',
            MessageOrigin.SOFT_SEAM,
        ),
        # A real seam ships inside a reminder envelope; the seam shape still
        # has to win, or every archived block comes back as a plain reminder.
        (
            wrap_system_reminder(
                '<archived_context level="2" range="msg 1-9">old</archived_context>'
            ),
            MessageOrigin.SOFT_SEAM,
        ),
        (
            "**Important**: The user asked you to add retries",
            MessageOrigin.REQUEST_LEDGER,
        ),
    ],
)
def test_legacy_shapes_are_recovered_on_load(
    text: str, expected: MessageOrigin
) -> None:
    (restored,) = messages_from_dicts([{"role": "user", "content": [
        {"type": "text", "text": text}
    ]}])
    assert restored.origin is expected
    assert is_synthetic_user_message(restored)


def test_a_legacy_real_request_survives_as_real() -> None:
    (restored,) = messages_from_dicts([{"role": "user", "content": [
        {"type": "text", "text": "add retries to the upload path"}
    ]}])
    assert restored.origin is None
    assert not is_synthetic_user_message(restored)


def test_an_explicit_origin_is_never_second_guessed() -> None:
    """A stored REAL_USER message whose text happens to look synthetic must
    come back exactly as it was stored."""
    stored = Message.user(
        "[System] the deploy log said this", origin=MessageOrigin.REAL_USER
    ).model_dump(mode="json")
    (restored,) = messages_from_dicts([stored])
    assert restored.origin is MessageOrigin.REAL_USER
    assert not is_synthetic_user_message(restored)


def test_inference_is_idempotent() -> None:
    (once,) = messages_from_dicts([{"role": "user", "content": [
        {"type": "text", "text": wrap_system_reminder("git status")}
    ]}])
    (twice,) = messages_from_dicts([once.model_dump(mode="json")])
    assert twice.origin is once.origin


def test_non_user_roles_are_left_alone() -> None:
    assert infer_legacy_origin(Message.assistant("done")) is None


# --- the loader is the only door -------------------------------------------


def _direct_validate_sites() -> list[str]:
    """Files calling ``Message.model_validate`` outside the sanctioned loader."""
    hits: list[str] = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "Message.model_validate" not in text:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if "Message.model_validate" in line:
                hits.append(f"{path.relative_to(SRC)}:{lineno}")
    return hits


def test_only_the_loader_deserializes_messages() -> None:
    """Every restore path must go through `messages_from_dicts`.

    A loader that calls `Message.model_validate` directly produces a
    transcript where reminders, seams and bridges all read as things the
    human said — and nothing downstream can tell, because the heuristics
    that used to cover for it are gone from the query path.
    """
    allowed = {"engine/context_pressure.py"}
    offenders = [
        hit for hit in _direct_validate_sites()
        if hit.rsplit(":", 1)[0] not in allowed
    ]
    assert not offenders, (
        "these must call messages_from_dicts instead: " + ", ".join(offenders)
    )


def test_synthetic_injections_declare_an_origin() -> None:
    """Every `Message.user(...)` built from a reminder envelope must tag
    itself; an untagged one now reads as a real request."""
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "wrap_system_reminder" not in source:
            continue
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "user"):
                continue
            call_src = ast.get_source_segment(source, node) or ""
            if "wrap_system_reminder" not in call_src:
                continue
            if "origin=" not in call_src:
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not offenders, "reminder built without an origin: " + ", ".join(offenders)


def test_no_hand_rolled_reminder_envelopes() -> None:
    """The literal tag outside the envelope helper means a site that can
    drift out of step with neutralization and tagging."""
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        if path.relative_to(SRC).as_posix() == "engine/context_pressure.py":
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if re.search(r'["\']<system-reminder>', line):
                offenders.append(f"{path.relative_to(SRC)}:{lineno}")
    assert not offenders, "use wrap_system_reminder: " + ", ".join(offenders)
