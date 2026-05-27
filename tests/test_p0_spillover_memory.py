"""P0 parity: spillover, retrieve_tool_result, memory, checkpoint."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deepseek_tui.config.models import Config
from deepseek_tui.engine.prompts import _load_user_memory
from deepseek_tui.memory.user_memory import append_entry, compose_block
from deepseek_tui.state.checkpoint import (
    clear_checkpoint,
    load_checkpoint,
    save_checkpoint,
)
from deepseek_tui.tools.base import ToolResult
from deepseek_tui.tools.deprecation import DeprecatingAliasTool, attach_deprecation
from deepseek_tui.tools.retrieve_tool_result import resolve_spillover_reference
from deepseek_tui.tools.spillover import (
    apply_spillover,
    prune_older_than,
    sanitise_id,
    set_test_spillover_root,
    write_spillover,
)
from deepseek_tui.tools.subagent_tools import AgentSpawnTool


def test_sanitise_id_strips_unsafe_chars() -> None:
    """Mirror Rust: keep alnum/-/_ only; empty after strip → None."""
    assert sanitise_id("call-abc12") == "call-abc12"
    assert sanitise_id("../evil") == "evil"
    assert sanitise_id("...") is None
    assert sanitise_id("") is None


def test_apply_spillover_writes_and_truncates(tmp_path: Path) -> None:
    prev = set_test_spillover_root(tmp_path)
    try:
        big = "x" * (100 * 1024 + 1)
        result = ToolResult(success=True, content=big)
        out = apply_spillover(result, "call-big")
        assert "retrieve_tool_result" in out.content
        assert out.metadata.get("spillover_path")
        path = resolve_spillover_reference("call-big")
        assert path.read_text(encoding="utf-8") == big
    finally:
        set_test_spillover_root(prev)


def test_memory_compose_block_opt_in(tmp_path: Path) -> None:
    path = tmp_path / "memory.md"
    path.write_text("- prefer pytest\n", encoding="utf-8")
    assert compose_block(False, path) is None
    block = compose_block(True, path)
    assert block is not None
    assert "<user_memory" in block
    assert "pytest" in block


def test_config_memory_enabled_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_MEMORY", "on")
    cfg = Config()
    assert cfg.memory_enabled() is True


def test_checkpoint_round_trip() -> None:
    clear_checkpoint()
    save_checkpoint({"messages": [{"role": "user", "content": "hi"}]})
    loaded = load_checkpoint()
    assert loaded is not None
    assert loaded["messages"][0]["content"] == "hi"
    clear_checkpoint()
    assert load_checkpoint() is None


def test_deprecating_alias_name() -> None:
    alias = DeprecatingAliasTool(AgentSpawnTool(), "spawn_agent", "agent_spawn")
    assert alias.name() == "spawn_agent"
    stamped = attach_deprecation(
        ToolResult(success=True, content="ok"), "spawn_agent", "agent_spawn"
    )
    assert stamped.metadata["_deprecation"]["use_instead"] == "agent_spawn"


def test_load_user_memory_uses_compose(tmp_path: Path) -> None:
    path = tmp_path / "memory.md"
    path.write_text("note", encoding="utf-8")
    block = _load_user_memory(True, path)
    assert block and "note" in block


def test_append_entry_strips_hash(tmp_path: Path) -> None:
    path = tmp_path / "memory.md"
    append_entry(path, "# use ruff")
    text = path.read_text(encoding="utf-8")
    assert "use ruff" in text
    assert "# use ruff" not in text
