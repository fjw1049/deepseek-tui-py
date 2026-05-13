"""Parity tests for the prompts module.

Mirrors Rust `crates/tui/src/prompts.rs` tests — verifies layered composition,
deterministic ordering, and all 17 template files load correctly.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from deepseek_tui.engine.prompts import _load_handoff_block, build_system_prompt
from deepseek_tui.prompts import (
    AGENT_MODE,
    AGENT_PROMPT,
    AUTO_APPROVAL,
    BASE_PROMPT,
    CALM_PERSONALITY,
    COMPACT_TEMPLATE,
    CYCLE_HANDOFF,
    NEVER_APPROVAL,
    PLAN_MODE,
    PLAYFUL_PERSONALITY,
    SUBAGENT_OUTPUT_FORMAT,
    SUGGEST_APPROVAL,
    YOLO_MODE,
    AppMode,
    Personality,
    compose_prompt,
)


class TestPromptFilesLoad:
    """All 17 prompt files load without error and are non-empty."""

    def test_base_md(self) -> None:
        assert len(BASE_PROMPT()) > 100

    def test_calm_personality(self) -> None:
        assert "Calm" in CALM_PERSONALITY()

    def test_playful_personality(self) -> None:
        assert "Playful" in PLAYFUL_PERSONALITY()

    def test_agent_mode(self) -> None:
        assert "Agent" in AGENT_MODE()

    def test_plan_mode(self) -> None:
        assert "Plan" in PLAN_MODE()

    def test_yolo_mode(self) -> None:
        assert "YOLO" in YOLO_MODE() or "Yolo" in YOLO_MODE()

    def test_auto_approval(self) -> None:
        assert "Auto" in AUTO_APPROVAL()

    def test_suggest_approval(self) -> None:
        assert "Suggest" in SUGGEST_APPROVAL()

    def test_never_approval(self) -> None:
        assert "Never" in NEVER_APPROVAL()

    def test_compact_template(self) -> None:
        assert "Compaction" in COMPACT_TEMPLATE() or "compact" in COMPACT_TEMPLATE().lower()

    def test_cycle_handoff(self) -> None:
        assert len(CYCLE_HANDOFF()) > 50

    def test_subagent_output_format(self) -> None:
        assert len(SUBAGENT_OUTPUT_FORMAT()) > 50

    def test_legacy_agent_txt(self) -> None:
        assert len(AGENT_PROMPT()) > 10


class TestComposition:
    """Mirror of Rust compose_prompt tests."""

    def test_compose_prompt_includes_all_layers(self) -> None:
        """Mirror of Rust `compose_prompt_includes_all_layers`."""
        prompt = compose_prompt(AppMode.AGENT, Personality.CALM)
        assert "You are DeepSeek TUI" in prompt
        assert "Personality: Calm" in prompt
        assert "Mode: Agent" in prompt
        assert "Approval Policy: Suggest" in prompt

    def test_compose_prompt_deterministic_order(self) -> None:
        """Mirror of Rust `compose_prompt_deterministic_order`."""
        prompt = compose_prompt(AppMode.YOLO, Personality.CALM)
        base_pos = prompt.find("You are DeepSeek TUI")
        personality_pos = prompt.find("Personality: Calm")
        mode_pos = prompt.find("Mode: YOLO")
        approval_pos = prompt.find("Approval Policy: Auto")

        assert base_pos < personality_pos
        assert personality_pos < mode_pos
        assert mode_pos < approval_pos

    def test_each_mode_gets_correct_approval(self) -> None:
        """Mirror of Rust `each_mode_gets_correct_approval`."""
        assert "Approval Policy: Suggest" in compose_prompt(AppMode.AGENT, Personality.CALM)
        assert "Approval Policy: Auto" in compose_prompt(AppMode.YOLO, Personality.CALM)
        assert "Approval Policy: Never" in compose_prompt(AppMode.PLAN, Personality.CALM)

    def test_personality_switches_correctly(self) -> None:
        """Mirror of Rust `personality_switches_correctly`."""
        calm = compose_prompt(AppMode.AGENT, Personality.CALM)
        playful = compose_prompt(AppMode.AGENT, Personality.PLAYFUL)
        assert "Personality: Calm" in calm
        assert "Personality: Playful" in playful
        assert "Personality: Playful" not in calm

    def test_compose_prompt_is_byte_stable(self) -> None:
        """Mirror of Rust `compose_prompt_is_byte_stable_across_calls`."""
        for mode in AppMode:
            for personality in Personality:
                a = compose_prompt(mode, personality)
                b = compose_prompt(mode, personality)
                assert a == b, f"Non-deterministic for {mode}/{personality}"

    def test_legacy_constants_non_empty(self) -> None:
        """Mirror of Rust `legacy_constants_still_available`."""
        assert AGENT_PROMPT()


class TestBuildSystemPrompt:
    """Tests for the engine-level build_system_prompt."""

    def test_override_returns_verbatim(self) -> None:
        assert build_system_prompt("custom") == "custom"

    def test_empty_override_uses_default(self) -> None:
        p = build_system_prompt("")
        assert "DeepSeek TUI" in p

    def test_none_override_uses_default(self) -> None:
        p = build_system_prompt(None)
        assert "DeepSeek TUI" in p

    def test_default_includes_context_management(self) -> None:
        p = build_system_prompt()
        assert "Context Management" in p

    def test_default_includes_compact_template(self) -> None:
        p = build_system_prompt()
        assert "Compaction" in p.lower() or "compact" in p.lower()

    def test_plan_mode_no_context_management(self) -> None:
        p = build_system_prompt(mode=AppMode.PLAN)
        assert "Context Management" not in p


class TestHandoff:
    """Mirror of Rust handoff tests."""

    def test_handoff_loaded_when_present(self) -> None:
        """Mirror of Rust `handoff_artifact_is_prepended_to_system_prompt_when_present`."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            handoff_dir = workspace / ".deepseek"
            handoff_dir.mkdir()
            (handoff_dir / "handoff.md").write_text(
                "# Session handoff\n\n## Active task\nFinish #32.\n"
            )
            block = _load_handoff_block(workspace)
            assert block is not None
            assert "Finish #32." in block
            assert "left a handoff" in block

    def test_missing_handoff_returns_none(self) -> None:
        """Mirror of Rust `missing_handoff_does_not_inject_block`."""
        with tempfile.TemporaryDirectory() as tmp:
            assert _load_handoff_block(Path(tmp)) is None

    def test_empty_handoff_returns_none(self) -> None:
        """Mirror of Rust `empty_handoff_file_does_not_inject_block`."""
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            handoff_dir = workspace / ".deepseek"
            handoff_dir.mkdir()
            (handoff_dir / "handoff.md").write_text("   \n\n  ")
            assert _load_handoff_block(workspace) is None

    def test_handoff_in_full_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            handoff_dir = workspace / ".deepseek"
            handoff_dir.mkdir()
            (handoff_dir / "handoff.md").write_text("# handoff\nDo X next.\n")
            p = build_system_prompt(workspace=workspace)
            assert "Do X next." in p

    def test_working_set_summary_appended(self) -> None:
        p = build_system_prompt(working_set_summary="## Working Set\n- src/main.py\n")
        assert "## Working Set" in p
        assert "src/main.py" in p
