"""Ratio-tier compaction + bridge composition + L0 prune."""

from __future__ import annotations

from deepseek_tui.engine.capacity import (
    CompactionConfig,
    ToolPruneConfig,
    plan_compaction,
    prune_old_tool_results,
    should_compact,
    should_l0_prune,
)
from deepseek_tui.engine.context_pressure import (
    COMPACTION_BRIDGE_PREFIX,
    build_compaction_bridge_text,
    extract_compaction_bridge_text,
    is_compaction_bridge_message,
    measure_context_pressure,
    prepend_compaction_bridge,
    thresholds_for_window,
)
from deepseek_tui.engine.turn import _apply_compact_result
from deepseek_tui.protocol.messages import Message, MessageRequest, Role


def test_thresholds_scale_with_window():
    t1m = thresholds_for_window(1_000_000)
    assert t1m["seam_l1"] == 200_000
    assert t1m["l0_prune"] == 500_000
    assert t1m["rewrite"] == 750_000
    assert t1m["cycle"] == 900_000

    t128 = thresholds_for_window(128_000)
    assert t128["rewrite"] == int(128_000 * 0.75)
    assert t128["seam_l1"] < t1m["seam_l1"]


def test_should_compact_uses_rewrite_ratio():
    # Enough early bulk that keep_recent_tokens leaves ≥6 messages to summarize.
    msgs = [Message.user("EARLY " + ("x" * 200)) for _ in range(30)]
    msgs += [Message.user(f"recent-{i}") for i in range(4)]
    cfg = CompactionConfig(
        rewrite_ratio=0.75,
        auto_floor_ratio=0.20,
        keep_recent_tokens=50,  # message-floor (4) dominates; leave bulk to summarize
    )

    # 40% of 1M — seams/L0 band, not rewrite.
    assert not should_compact(
        msgs, cfg, real_input_tokens=400_000, model="deepseek-v4-pro"
    )
    # 80% — rewrite.
    assert should_compact(
        msgs, cfg, real_input_tokens=800_000, model="deepseek-v4-pro"
    )
    # Below floor.
    assert not should_compact(
        msgs, cfg, real_input_tokens=100_000, model="deepseek-v4-pro"
    )


def test_bridge_composition_is_user_message_not_system():
    summary = (
        "### Goal\nShip it.\n\n"
        "### Constraints\nNone\n\n"
        "### Progress\n#### Done\nA\n#### In Progress\nNone\n#### Blocked\nNone\n\n"
        "### Key Decisions\nUse bridge.\n\n"
        "### Next step\nTest.\n"
    )
    bridge = build_compaction_bridge_text(summary, working_set_paths=["a.py"])
    assert COMPACTION_BRIDGE_PREFIX in bridge
    assert "<archived_context>" in bridge
    assert "a.py" in bridge

    kept = [Message.user("recent"), Message.assistant("ok")]
    out = prepend_compaction_bridge(kept, bridge)
    assert len(out) == 3
    assert out[0].role == Role.USER
    assert is_compaction_bridge_message(out[0])
    assert extract_compaction_bridge_text(out) == bridge

    # Soft seam (assistant + level=) is NOT a rewrite bridge.
    seam = Message.assistant(
        '<archived_context level="1" range="msg 0-2">old</archived_context>'
    )
    assert not is_compaction_bridge_message(seam)


def test_apply_compact_result_does_not_mutate_system():
    req = MessageRequest(
        model="deepseek-chat",
        messages=[Message.user("old")],
        system_prompt="STABLE SYSTEM",
    )
    bridge = build_compaction_bridge_text(
        "### Goal\nG\n\n### Next step\nN\n" + ("x" * 40)
    )
    new_msgs = prepend_compaction_bridge([Message.user("tail")], bridge)
    _apply_compact_result(req, (new_msgs, bridge))
    assert req.system_prompt == "STABLE SYSTEM"
    assert is_compaction_bridge_message(req.messages[0])


def test_l0_prune_soft_and_hard():
    # Build: user/assistant/tool × 12 turns with a fat early tool result.
    messages: list[Message] = []
    for i in range(12):
        messages.append(Message.user(f"u{i}"))
        messages.append(Message.assistant(f"a{i}"))
        body = ("Z" * 8000) if i < 2 else "short"
        messages.append(Message.tool_result(f"call-{i}", body))

    # Hard-clear the oldest (age >= 10 turns from end).
    changed = prune_old_tool_results(
        messages,
        config=ToolPruneConfig(
            keep_last_n_turns=3,
            soft_trim_threshold=4000,
            soft_trim_head=100,
            soft_trim_tail=100,
            hard_clear_age_turns=10,
        ),
    )
    assert changed >= 1
    first_tool = messages[2]
    content = first_tool.content[0].content  # type: ignore[attr-defined]
    assert "omitted" in content or "pruned" in content or len(content) < 8000


def test_should_l0_prune_ratio():
    msgs = [Message.user("hi")]
    assert not should_l0_prune(
        model="deepseek-v4-pro",
        messages=msgs,
        real_input_tokens=100_000,
    )
    assert should_l0_prune(
        model="deepseek-v4-pro",
        messages=msgs,
        real_input_tokens=600_000,
    )


def test_plan_compaction_token_window():
    # One huge message + many tiny ones — keep window should expand past 4 msgs.
    messages = [Message.user("tiny")] * 8 + [Message.user("X" * 80_000)]
    plan = plan_compaction(messages, keep_recent_tokens=20_000)
    assert len(plan.pinned_indices) >= 1
    assert (len(messages) - 1) in plan.pinned_indices


def test_measure_context_pressure_prefers_real():
    msgs = [Message.user("hello")]
    p = measure_context_pressure(
        "deepseek-v4-pro", msgs, real_input_tokens=250_000
    )
    assert p.source == "real"
    assert p.tokens == 250_000
    assert 0.2 <= p.ratio <= 0.3
