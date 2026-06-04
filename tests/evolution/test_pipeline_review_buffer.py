from collections import defaultdict
from dataclasses import replace

from deepseek_tui.evolution.pipeline import EvolutionPipeline, _truncate_messages
from deepseek_tui.post_turn.evidence import TurnEvidence


def _evidence(thread_id: str, text: str, turn: int = 0) -> TurnEvidence:
    return TurnEvidence(
        thread_id=thread_id,
        user_text=text,
        workspace="/tmp",
        messages=[{"role": "user", "content": text}],
        had_tool_calls=False,
        success=True,
        user_turn_index=turn,
        turn_id=f"turn-{turn}",
    )


def test_review_buffer_merges_prior_turns() -> None:
    pipeline = EvolutionPipeline.__new__(EvolutionPipeline)
    pipeline._review_turn_buffers = defaultdict(list)
    e1 = _evidence("t1", "turn one", 1)
    e2 = _evidence("t1", "turn two", 2)
    pipeline._append_review_buffer(e1)
    pipeline._append_review_buffer(e2)
    merged = pipeline._review_evidence(e2)
    contents = [m["content"] for m in merged.messages]
    assert "turn one" in contents
    assert "turn two" in contents


def test_truncate_messages_caps_length() -> None:
    long = "x" * 5000
    out = _truncate_messages([{"role": "user", "content": long}], 100)
    assert len(out[0]["content"]) <= 100


def test_skill_tool_rounds_accumulate() -> None:
    pipeline = EvolutionPipeline.__new__(EvolutionPipeline)
    pipeline._skill_tool_rounds = {}
    pipeline._skill_nudge_tool_rounds = 5
    e1 = replace(_evidence("t1", "a"), tool_rounds=3)
    e2 = replace(_evidence("t1", "b"), tool_rounds=3)
    pipeline._skill_tool_rounds["t1"] = 0
    pipeline._skill_tool_rounds["t1"] += e1.tool_rounds
    assert pipeline._skill_tool_rounds["t1"] == 3
    pipeline._skill_tool_rounds["t1"] += e2.tool_rounds
    assert pipeline._skill_tool_rounds["t1"] >= 5
