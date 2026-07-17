"""Last-query survival, seam role, cycle seeds, and user_query split."""

from __future__ import annotations

from pathlib import Path

from deepseek_tui.engine.context_pressure import (
    build_compaction_bridge_text,
    find_last_real_user_query,
    is_compaction_bridge_message,
    is_synthetic_user_message,
    prepend_compaction_bridge,
    wrap_system_reminder,
)
from deepseek_tui.engine.cycle import CycleBriefing, build_seed_messages
from deepseek_tui.protocol.messages import Message, MessageOrigin, Role
from deepseek_tui.state.context import UserTurnInput, process_turn_input


def test_prepend_bridge_replays_last_query_when_outside_window() -> None:
    bridge = build_compaction_bridge_text(
        "### Goal\nShip it.\n\n### Next step\nTest.\n"
    )
    recent = [Message.assistant("working"), Message.tool_result("t1", "ok")]
    out = prepend_compaction_bridge(
        recent,
        bridge,
        last_real_query="fix the login bug",
    )
    assert is_compaction_bridge_message(out[0])
    assert out[0].origin is MessageOrigin.COMPACTION_BRIDGE
    assert out[1].origin is MessageOrigin.REAL_USER
    assert "<user_query>" in out[1].text_content()
    assert "fix the login bug" in out[1].text_content()
    assert out[1].role is Role.USER


def test_prepend_bridge_skips_replay_when_query_already_present() -> None:
    bridge = build_compaction_bridge_text("### Goal\nG\n\n### Next step\nN\n")
    kept = [
        Message.user(
            "<user_query>\nfix login\n</user_query>",
            origin=MessageOrigin.REAL_USER,
        ),
        Message.assistant("ok"),
    ]
    out = prepend_compaction_bridge(
        kept, bridge, last_real_query="fix login"
    )
    real_users = [
        m for m in out if m.origin is MessageOrigin.REAL_USER
    ]
    assert len(real_users) == 1


def test_find_last_real_user_skips_reminders_and_bridge() -> None:
    msgs = [
        Message.user(
            "<user_query>\ngoal A\n</user_query>",
            origin=MessageOrigin.REAL_USER,
        ),
        Message.user(
            wrap_system_reminder("LSP noise"),
            origin=MessageOrigin.SYSTEM_REMINDER,
        ),
        Message.user(
            build_compaction_bridge_text("### Goal\nX\n\n### Next step\nY\n"),
            origin=MessageOrigin.COMPACTION_BRIDGE,
        ),
        Message.assistant("tooling"),
    ]
    assert find_last_real_user_query(msgs) == "goal A"
    assert is_synthetic_user_message(msgs[1])
    assert is_synthetic_user_message(msgs[2])


def test_cycle_seed_has_no_fake_assistant_ack() -> None:
    seeds = build_seed_messages(
        structured_state_block="mode: agent",
        briefing=CycleBriefing(
            cycle=1,
            timestamp=1_700_000_000,
            briefing_text="continue the auth work",
            token_estimate=10,
        ),
        pending_user_message="fix the login bug",
    )
    assert all(s["role"] == "user" for s in seeds)
    joined = "\n".join(s["content"] for s in seeds)
    assert "Acknowledged" not in joined
    assert "Briefing absorbed" not in joined
    assert "<system-reminder>" in seeds[0]["content"]
    assert seeds[-1]["origin"] == "real_user"
    assert "fix the login bug" in seeds[-1]["content"]


def test_user_query_local_context_split(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("print(1)\n", encoding="utf-8")
    out = process_turn_input(
        UserTurnInput(raw_text="fix login @a.py"),
        workspace=tmp_path,
        cwd=tmp_path,
    )
    assert out.model_text.startswith("<user_query>")
    assert "fix login @a.py" in out.model_text
    assert "<local_context>" in out.model_text
    assert "print(1)" in out.model_text
    # Display stays human-facing raw text.
    assert out.display_text == "fix login @a.py"


def test_soft_seam_message_is_user_reminder() -> None:
    from deepseek_tui.engine.context_pressure import wrap_system_reminder

    seam_body = (
        '<archived_context level="1" range="msg 0-2">'
        "old work"
        "</archived_context>"
    )
    msg = Message.user(
        wrap_system_reminder(seam_body),
        origin=MessageOrigin.SOFT_SEAM,
    )
    assert msg.role is Role.USER
    assert not is_compaction_bridge_message(msg)
    assert is_synthetic_user_message(msg)
