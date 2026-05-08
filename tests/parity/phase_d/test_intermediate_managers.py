"""Parity tests for P1 Intermediate Layer Managers.

Covers cycle_manager, seam_manager, and working_set.
Mirrors Rust test assertions from cycle_manager.rs and seam_manager.rs.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from deepseek_tui.engine.cycle_manager import (
    CycleBriefing,
    CycleConfig,
    ModelCycleConfig,
    StructuredState,
    archive_cycle,
    build_seed_messages,
    enforce_briefing_cap,
    estimate_briefing_tokens,
    extract_carry_forward,
    open_archive,
    should_advance_cycle,
)
from deepseek_tui.engine.seam_manager import (
    SeamConfig,
    SeamManager,
    SeamMetadata,
    seam_level_for_active_input,
    truncate_chars,
)
from deepseek_tui.engine.working_set import WorkingSet


class TestCycleConfig:
    def test_default_config(self):
        cfg = CycleConfig()
        assert cfg.enabled is True
        assert cfg.threshold_tokens == 768_000
        assert cfg.briefing_max_tokens == 3_000

    def test_per_model_override(self):
        cfg = CycleConfig(
            per_model={"gpt-4": ModelCycleConfig(threshold_tokens=500_000)}
        )
        assert cfg.threshold_for("gpt-4") == 500_000
        assert cfg.threshold_for("other") == 768_000

    def test_briefing_max_per_model(self):
        cfg = CycleConfig(
            per_model={"flash": ModelCycleConfig(briefing_max_tokens=2_000)}
        )
        assert cfg.briefing_max_for("flash") == 2_000
        assert cfg.briefing_max_for("other") == 3_000


class TestShouldAdvanceCycle:
    def test_disabled_never_fires(self):
        cfg = CycleConfig(enabled=False)
        assert should_advance_cycle(999_999, 0, "m", cfg, False) is False

    def test_in_flight_blocks(self):
        cfg = CycleConfig()
        assert should_advance_cycle(999_999, 0, "m", cfg, True) is False

    def test_below_threshold(self):
        cfg = CycleConfig()
        assert should_advance_cycle(100_000, 0, "m", cfg, False) is False

    def test_fires_at_threshold(self):
        cfg = CycleConfig(threshold_tokens=200_000)
        with patch(
            "deepseek_tui.engine.context.context_input_budget",
            return_value=None,
        ):
            result = should_advance_cycle(200_000, 0, "m", cfg, False)
            assert result is True

    def test_zero_threshold_never_fires(self):
        cfg = CycleConfig(threshold_tokens=0)
        assert should_advance_cycle(999_999, 0, "m", cfg, False) is False


class TestExtractCarryForward:
    def test_extracts_block(self):
        raw = "Some preamble\n<carry_forward>\nImportant state\n</carry_forward>\nEpilogue"
        assert extract_carry_forward(raw) == "Important state"

    def test_case_insensitive(self):
        raw = "<Carry_Forward>\nData here\n</Carry_Forward>"
        assert extract_carry_forward(raw) == "Data here"

    def test_no_close_tag(self):
        raw = "<carry_forward>\nTrailing content without close"
        assert extract_carry_forward(raw) == "Trailing content without close"

    def test_no_tags_returns_full_text(self):
        raw = "No tags here"
        assert extract_carry_forward(raw) == "No tags here"


class TestEnforceBriefingCap:
    def test_within_cap(self):
        text = "short"
        assert enforce_briefing_cap(text, 100) == "short"

    def test_exceeds_cap(self):
        text = "a" * 1000
        result = enforce_briefing_cap(text, 10)
        assert len(result) < 1000
        assert "truncated" in result

    def test_zero_cap(self):
        assert enforce_briefing_cap("anything", 0) == ""


class TestEstimateBriefingTokens:
    def test_estimate(self):
        text = "a" * 100
        tokens = estimate_briefing_tokens(text)
        assert tokens == 25  # 100 / 4


class TestStructuredState:
    def test_to_system_block_basic(self):
        state = StructuredState(mode_label="agent", workspace="/home/user/project")
        block = state.to_system_block()
        assert "Mode: `agent`" in block
        assert "Workspace: `/home/user/project`" in block

    def test_with_plan(self):
        state = StructuredState(
            mode_label="plan",
            workspace="/tmp",
            plan_snapshot=[
                {"step": "Write tests", "status": "completed"},
                {"step": "Implement", "status": "in_progress"},
            ],
        )
        block = state.to_system_block()
        assert "[x] Write tests" in block
        assert "[~] Implement" in block

    def test_with_todos(self):
        state = StructuredState(
            mode_label="agent",
            workspace="/tmp",
            todo_snapshot=[{"content": "Fix bug", "status": "pending"}],
        )
        block = state.to_system_block()
        assert "[ ] Fix bug" in block

    def test_with_subagents(self):
        state = StructuredState(
            mode_label="agent",
            workspace="/tmp",
            subagent_snapshots=[
                {"agent_id": "sa-1", "role": "coder", "objective": "Implement X"}
            ],
        )
        block = state.to_system_block()
        assert "sa-1" in block
        assert "coder" in block

    def test_with_working_set_summary(self):
        state = StructuredState(
            mode_label="agent",
            workspace="/tmp",
            working_set_summary="### Working Set\n- `src/main.py`",
        )
        block = state.to_system_block()
        assert "src/main.py" in block


class TestArchiveAndOpen:
    def test_archive_and_read_back(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(
            "deepseek_tui.engine.cycle_manager._archive_dir_for",
            lambda sid: tmp_path / "cycles",
        )
        from deepseek_tui.protocol.messages import Message

        msgs = [Message.user("hello"), Message.assistant("hi")]
        path = archive_cycle("sess-1", 0, msgs, "deepseek", int(time.time()))

        assert path.exists()
        header, records = open_archive(path)
        assert header.cycle == 0
        assert header.session_id == "sess-1"
        assert header.model == "deepseek"
        assert header.message_count == 2
        assert len(records) == 2

    def test_schema_version_check(self, tmp_path: Path):
        bad_file = tmp_path / "bad.jsonl"
        bad_file.write_text(json.dumps({"schema_version": 99}) + "\n")
        with pytest.raises(ValueError, match="newer than supported"):
            open_archive(bad_file)


class TestBuildSeedMessages:
    def test_empty_inputs(self):
        seeds = build_seed_messages(None, None, None)
        assert seeds == []

    def test_with_state_only(self):
        seeds = build_seed_messages("## State\n- foo", None, None)
        assert len(seeds) == 2
        assert "CYCLE STATE" in seeds[0]["content"]
        assert seeds[1]["role"] == "assistant"

    def test_with_briefing(self):
        briefing = CycleBriefing(
            cycle=1,
            timestamp=int(time.time()),
            briefing_text="Key decisions here",
            token_estimate=100,
        )
        seeds = build_seed_messages(None, briefing, None)
        assert len(seeds) == 2
        assert "CYCLE BRIEFING" in seeds[0]["content"]
        assert "Key decisions here" in seeds[0]["content"]

    def test_with_pending_message(self):
        seeds = build_seed_messages(None, None, "What next?")
        assert len(seeds) == 1
        assert seeds[0]["content"] == "What next?"

    def test_full_seed(self):
        briefing = CycleBriefing(
            cycle=2,
            timestamp=int(time.time()),
            briefing_text="All state",
            token_estimate=50,
        )
        seeds = build_seed_messages("mode: agent", briefing, "Continue")
        assert len(seeds) == 5


# ===========================================================================
# seam_manager tests
# ===========================================================================


class TestSeamConfig:
    def test_defaults(self):
        cfg = SeamConfig()
        assert cfg.enabled is True
        assert cfg.l1_threshold == 192_000
        assert cfg.l2_threshold == 384_000
        assert cfg.l3_threshold == 576_000
        assert cfg.cycle_threshold == 768_000
        assert cfg.verbatim_window_turns == 16


class TestSeamLevelForActiveInput:
    def test_below_l1_returns_none(self):
        cfg = SeamConfig()
        assert seam_level_for_active_input(cfg, 100_000) is None

    def test_fires_l1(self):
        cfg = SeamConfig()
        assert seam_level_for_active_input(cfg, 192_000, None) == 1

    def test_fires_l2_after_l1(self):
        cfg = SeamConfig()
        assert seam_level_for_active_input(cfg, 384_000, 1) == 2

    def test_fires_l3_after_l2(self):
        cfg = SeamConfig()
        assert seam_level_for_active_input(cfg, 576_000, 2) == 3

    def test_no_double_fire(self):
        cfg = SeamConfig()
        assert seam_level_for_active_input(cfg, 192_000, 1) is None

    def test_disabled_returns_none(self):
        cfg = SeamConfig(enabled=False)
        assert seam_level_for_active_input(cfg, 999_999) is None

    def test_uses_active_input_not_lifetime(self):
        """Mirrors Rust test: seam_trigger_uses_active_request_size_not_lifetime_usage."""
        cfg = SeamConfig()
        active_request_input = 120_000
        assert seam_level_for_active_input(cfg, active_request_input, None) is None


class TestSeamManagerLogic:
    def test_verbatim_window_start(self):
        mock_client = MagicMock()
        mgr = SeamManager(mock_client, SeamConfig(verbatim_window_turns=4))
        assert mgr.verbatim_window_start(20) == 12
        assert mgr.verbatim_window_start(8) == 0
        assert mgr.verbatim_window_start(4) == 0
        assert mgr.verbatim_window_start(0) == 0

    def test_should_cycle(self):
        mock_client = MagicMock()
        mgr = SeamManager(mock_client, SeamConfig())
        assert mgr.should_cycle(768_000) is True
        assert mgr.should_cycle(700_000) is False

    def test_should_cycle_disabled(self):
        mock_client = MagicMock()
        mgr = SeamManager(mock_client, SeamConfig(enabled=False))
        assert mgr.should_cycle(999_999) is False

    def test_seam_level_for_delegates(self):
        mock_client = MagicMock()
        mgr = SeamManager(mock_client, SeamConfig())
        assert mgr.seam_level_for(192_000) == 1
        assert mgr.seam_level_for(100_000) is None

    def test_collect_seam_texts(self):
        from deepseek_tui.protocol.messages import Message

        mock_client = MagicMock()
        mgr = SeamManager(mock_client)

        msgs = [
            Message.user("hello"),
            Message.assistant('<archived_context level="1">Summary</archived_context>'),
            Message.assistant("Normal response"),
        ]
        texts = mgr.collect_seam_texts(msgs)
        assert len(texts) == 1
        assert "archived_context" in texts[0]

    @pytest.mark.asyncio
    async def test_highest_level_empty(self):
        mock_client = MagicMock()
        mgr = SeamManager(mock_client)
        assert await mgr.highest_level() is None

    @pytest.mark.asyncio
    async def test_reset_clears_seams(self):
        mock_client = MagicMock()
        mgr = SeamManager(mock_client)
        mgr._active_seams.append(
            SeamMetadata(
                level=1, start_idx=0, end_idx=5,
                token_estimate=100, timestamp=0.0, model="m",
            )
        )
        assert mgr.seam_count == 1
        await mgr.reset()
        assert mgr.seam_count == 0


class TestTruncateChars:
    def test_within_limit(self):
        assert truncate_chars("abc", 10) == "abc"

    def test_truncates(self):
        assert truncate_chars("abcdef", 3) == "abc"

    def test_zero_limit(self):
        assert truncate_chars("abc", 0) == ""

    def test_unicode(self):
        assert len(truncate_chars("abc😀é", 4)) == 4


# ===========================================================================
# working_set tests
# ===========================================================================


class TestWorkingSet:
    def test_observe_user_message(self):
        ws = WorkingSet()
        ws.observe_user_message("Please edit ./src/main.py")
        assert ws.message_count == 1
        assert any("main.py" in p for p in ws.recent_paths)

    def test_observe_tool_call(self):
        ws = WorkingSet()
        ws.observe_tool_call("read_file", {"path": "/home/user/test.py"})
        assert "/home/user/test.py" in ws.recent_paths
        assert ws.recent_tool_uses == ["read_file"]

    def test_tool_use_limit(self):
        ws = WorkingSet()
        for i in range(25):
            ws.observe_tool_call(f"tool_{i}", None)
        assert len(ws.recent_tool_uses) == 20

    def test_top_paths_limit(self):
        ws = WorkingSet()
        for i in range(30):
            ws.recent_paths.add(f"/path/file{i}.py")
        top = ws.top_paths(limit=10)
        assert len(top) == 10

    def test_pinned_message_indices_keeps_recent(self):
        from deepseek_tui.protocol.messages import Message

        ws = WorkingSet()
        msgs = [Message.user(f"msg {i}") for i in range(10)]
        pinned = ws.pinned_message_indices(msgs)
        assert 6 in pinned
        assert 7 in pinned
        assert 8 in pinned
        assert 9 in pinned

    def test_pinned_empty_messages(self):
        ws = WorkingSet()
        assert ws.pinned_message_indices([]) == set()

    def test_summary_empty(self):
        ws = WorkingSet()
        assert ws.summary() == ""

    def test_summary_with_paths(self):
        ws = WorkingSet()
        ws.recent_paths.add("src/main.py")
        ws.recent_paths.add("tests/test_foo.py")
        s = ws.summary()
        assert "Working Set" in s
        assert "src/main.py" in s
