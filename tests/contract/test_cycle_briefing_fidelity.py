"""Contract: the cycle briefing carries what the archive cannot reconstruct.

A cycle boundary is the lossiest transition in the system — the entire
transcript leaves context and only the briefing, the structured state, and the
verbatim request ledger cross over. The archive on disk makes *facts*
recoverable, but two classes of information are not in it in any usable form:

  - what an earlier turn *claimed* versus what it actually verified, and
  - what the cycle never established at all (a path referenced but never read,
    a schema assumed but never inspected).

Both look identical to a confident assertion once the transcript is gone, so the
briefing has to mark them explicitly. These tests pin the instructions that ask
for that, and the read-side note that stops the next cycle from treating the
briefing as evidence.
"""

from __future__ import annotations

from deepseek_tui.engine.cycle import (
    CycleBriefing,
    build_seed_messages,
    extract_carry_forward,
)
from deepseek_tui.engine.prompts import CYCLE_HANDOFF


def _unwrapped(text: str) -> str:
    """Collapse newlines so assertions test wording, not hand-wrapping."""
    return " ".join(text.split())


# --- what the briefing is asked to carry ----------------------------------


def test_briefing_asks_for_unverified_claims_to_be_marked() -> None:
    contract = _unwrapped(CYCLE_HANDOFF())
    assert "unverified" in contract
    # The reason has to be stated, or the rule reads as bookkeeping.
    assert "becomes fact" in contract


def test_briefing_asks_what_the_cycle_never_established() -> None:
    contract = _unwrapped(CYCLE_HANDOFF())
    assert "never established" in contract
    assert "assumed but not inspected" in contract


def test_briefing_asks_for_an_anchored_next_action() -> None:
    """"Continue the refactor" costs the next cycle a re-derivation."""
    contract = _unwrapped(CYCLE_HANDOFF())
    assert "next concrete action, anchored" in contract
    assert "copied exactly" in contract


def test_briefing_asks_for_the_remaining_sequence_not_just_one_step() -> None:
    contract = _unwrapped(CYCLE_HANDOFF())
    assert "remaining sequence" in contract
    assert "does not reopen them" in contract


def test_briefing_still_names_the_carry_forward_envelope() -> None:
    """The extractor keys on this tag; losing it from the prompt breaks parsing."""
    contract = CYCLE_HANDOFF()
    assert "<carry_forward>" in contract
    assert "</carry_forward>" in contract


# --- what the next cycle is told about the briefing ------------------------


def _seed_body(briefing_text: str, archive: str | None = None) -> str:
    briefing = CycleBriefing(
        cycle=3,
        timestamp=1_700_000_000,
        briefing_text=briefing_text,
        token_estimate=20,
    )
    seeds = build_seed_messages(
        structured_state_block=None,
        briefing=briefing,
        pending_user_message="继续",
        archive_path=archive,
        prior_requests=None,
    )
    return seeds[0]["content"]


def test_seed_tells_the_next_cycle_to_verify_before_building() -> None:
    body = _seed_body("Decided X because Y.")
    assert "notes, not proof" in body
    assert "verify it yourself" in body


def test_verification_caveat_is_not_captured_as_briefing_content() -> None:
    """It sits outside the tags, so a re-extraction must not absorb it.

    Otherwise every boundary would fold the previous caveat into the next
    briefing's text and stack one copy per cycle.
    """
    body = _seed_body("Decided X because Y. Failed: approach Z (API rejects null).")
    extracted = extract_carry_forward(body)

    assert extracted == "Decided X because Y. Failed: approach Z (API rejects null)."
    assert "notes, not proof" not in extracted


def test_archive_pointer_and_caveat_are_different_advice() -> None:
    """One says where to look; the other says what not to trust.

    A briefing that omits a detail sends you to the archive; a briefing that
    asserts an unverified one does not, which is why both notes are present.
    """
    body = _seed_body("Decided X.", archive="/tmp/cycles/3.jsonl")
    assert "/tmp/cycles/3.jsonl" in body
    assert "lossy summary" in body
    assert "notes, not proof" in body
