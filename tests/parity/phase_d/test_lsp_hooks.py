"""Parity tests for LSP post-edit hook + engine integration (Stage 4.4).

Mirrors ``crates/tui/src/core/engine/lsp_hooks.rs`` (128 lines).

Covers:

- edited_paths_for_tool for edit_file / write_file / apply_patch
- parse_patch_paths fallback on raw unified diffs
- ToolRuntime constructs an LspManager when Config.lsp.enabled
- Engine._run_post_edit_lsp_hook queues diagnostics on pending_lsp_blocks
- Engine._flush_pending_lsp_diagnostics injects a synthetic user message
- Silent-failure: a crashed LspManager doesn't break the turn loop
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deepseek_tui.config.models import Config
from deepseek_tui.lsp import (
    LSP_MANAGER_KEY,
    Diagnostic,
    DiagnosticBlock,
    Severity,
    edited_paths_for_tool,
    parse_patch_paths,
)
from deepseek_tui.lsp.manager import LspConfig, LspManager
from deepseek_tui.protocol.messages import Message
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.runtime import create_tool_runtime


class TestEditedPathsForTool:
    def test_edit_file(self) -> None:
        assert edited_paths_for_tool(
            "edit_file", {"path": "src/main.py", "content": "x"}
        ) == [Path("src/main.py")]

    def test_write_file(self) -> None:
        assert edited_paths_for_tool(
            "write_file", {"path": "a/b.py"}
        ) == [Path("a/b.py")]

    def test_apply_patch_with_path(self) -> None:
        assert edited_paths_for_tool(
            "apply_patch", {"path": "x.py", "patch": "..."}
        ) == [Path("x.py")]

    def test_apply_patch_with_files_list(self) -> None:
        paths = edited_paths_for_tool(
            "apply_patch",
            {"files": [{"path": "a.py", "content": "x"}, {"path": "b.py"}]},
        )
        assert paths == [Path("a.py"), Path("b.py")]

    def test_apply_patch_with_changes_list(self) -> None:
        paths = edited_paths_for_tool(
            "apply_patch",
            {"changes": [{"path": "c.py", "content": "y"}]},
        )
        assert paths == [Path("c.py")]

    def test_apply_patch_fallback_to_diff_headers(self) -> None:
        patch = (
            "--- a/old.py\n"
            "+++ b/new.py\n"
            "@@ -1 +1 @@\n-a\n+b\n"
        )
        paths = edited_paths_for_tool("apply_patch", {"patch": patch})
        assert paths == [Path("new.py")]

    def test_non_edit_tool_returns_empty(self) -> None:
        assert edited_paths_for_tool("read_file", {"path": "x.py"}) == []

    def test_invalid_input_returns_empty(self) -> None:
        assert edited_paths_for_tool("edit_file", "not a dict") == []


class TestParsePatchPaths:
    def test_strips_b_prefix(self) -> None:
        assert parse_patch_paths("+++ b/x.py\n") == [Path("x.py")]

    def test_keeps_plain_paths(self) -> None:
        assert parse_patch_paths("+++ x.py\n") == [Path("x.py")]

    def test_skips_dev_null(self) -> None:
        assert parse_patch_paths("+++ /dev/null\n") == []

    def test_multi_file(self) -> None:
        patch = "+++ b/a.py\n+++ b/b.py\n"
        assert parse_patch_paths(patch) == [Path("a.py"), Path("b.py")]


class TestToolRuntimeLspWiring:
    async def test_disabled_by_default(self, tmp_path: Path) -> None:
        cfg = Config()
        runtime = await create_tool_runtime(
            config=cfg,
            working_directory=tmp_path,
            task_data_dir=tmp_path / "tasks",
            subagent_state_path=tmp_path / "sub.json",
        )
        try:
            assert runtime.lsp_manager is None
            assert LSP_MANAGER_KEY not in runtime.context.metadata
        finally:
            await runtime.shutdown()

    async def test_enabled_attaches_manager(self, tmp_path: Path) -> None:
        cfg = Config()
        cfg.lsp.enabled = True
        cfg.lsp.poll_after_edit_ms = 10
        cfg.lsp.servers = {"python": ["noop-lsp"]}
        runtime = await create_tool_runtime(
            config=cfg,
            working_directory=tmp_path,
            task_data_dir=tmp_path / "tasks",
            subagent_state_path=tmp_path / "sub.json",
        )
        try:
            assert isinstance(runtime.lsp_manager, LspManager)
            assert runtime.lsp_manager.config.enabled is True
            assert runtime.lsp_manager.config.poll_after_edit_ms == 10
            assert runtime.lsp_manager.config.servers["python"] == ["noop-lsp"]
            attached = runtime.context.metadata[LSP_MANAGER_KEY]
            assert attached is runtime.lsp_manager
        finally:
            await runtime.shutdown()


class _EngineShim:
    """Minimal Engine-shaped object exposing just the LSP hook methods.

    Building a real Engine requires an LLMClient and approval handler;
    the hook logic only touches tool_context + pending_lsp_blocks +
    turn_counter, so we test those in isolation.
    """

    def __init__(self, ctx: ToolContext) -> None:
        self.tool_context = ctx
        self.pending_lsp_blocks: list[DiagnosticBlock] = []
        self.turn_counter = 1

    # Bind the real methods off Engine via descriptor access so we test
    # the production implementations unchanged.
    from deepseek_tui.engine.engine import Engine

    _get_lsp_manager = Engine._get_lsp_manager
    _run_post_edit_lsp_hook = Engine._run_post_edit_lsp_hook
    _flush_pending_lsp_diagnostics = Engine._flush_pending_lsp_diagnostics


class _StubLspManager:
    """LspManager stand-in that returns scripted blocks."""

    def __init__(
        self,
        enabled: bool = True,
        blocks: list[DiagnosticBlock] | None = None,
        raise_exc: Exception | None = None,
    ) -> None:
        self.config = LspConfig(enabled=enabled)
        self._blocks = blocks or []
        self._raise = raise_exc
        self.calls: list[tuple[Path, int]] = []

    async def diagnostics_for(
        self, path: Path, _content: str, seq: int
    ) -> list[DiagnosticBlock]:
        self.calls.append((path, seq))
        if self._raise is not None:
            raise self._raise
        return self._blocks


class TestEnginePostEditHook:
    async def test_queues_diagnostics_for_edited_file(self, tmp_path: Path) -> None:
        target = tmp_path / "x.py"
        target.write_text("print('hi')\n")
        block = DiagnosticBlock(
            path=str(target),
            diagnostics=[
                Diagnostic(Severity.ERROR, 1, 1, "bad thing", "pyright"),
            ],
        )
        stub = _StubLspManager(blocks=[block])
        ctx = ToolContext(
            working_directory=tmp_path,
            metadata={LSP_MANAGER_KEY: stub},
        )
        engine = _EngineShim(ctx)

        await engine._run_post_edit_lsp_hook(
            "edit_file", {"path": "x.py"}
        )

        assert len(engine.pending_lsp_blocks) == 1
        assert engine.pending_lsp_blocks[0].path == str(target)
        # turn_counter routed through to the manager
        assert stub.calls == [(target, 1)]

    async def test_no_hook_when_disabled(self, tmp_path: Path) -> None:
        stub = _StubLspManager(enabled=False)
        ctx = ToolContext(
            working_directory=tmp_path,
            metadata={LSP_MANAGER_KEY: stub},
        )
        engine = _EngineShim(ctx)
        await engine._run_post_edit_lsp_hook("edit_file", {"path": "x.py"})
        assert stub.calls == []
        assert engine.pending_lsp_blocks == []

    async def test_no_hook_for_non_edit_tool(self, tmp_path: Path) -> None:
        stub = _StubLspManager()
        ctx = ToolContext(
            working_directory=tmp_path,
            metadata={LSP_MANAGER_KEY: stub},
        )
        engine = _EngineShim(ctx)
        await engine._run_post_edit_lsp_hook(
            "read_file", {"path": "x.py"}
        )
        assert stub.calls == []

    async def test_missing_file_is_silently_skipped(self, tmp_path: Path) -> None:
        stub = _StubLspManager()
        ctx = ToolContext(
            working_directory=tmp_path,
            metadata={LSP_MANAGER_KEY: stub},
        )
        engine = _EngineShim(ctx)
        await engine._run_post_edit_lsp_hook(
            "edit_file", {"path": "does_not_exist.py"}
        )
        assert stub.calls == []
        assert engine.pending_lsp_blocks == []

    async def test_manager_failure_is_silent(self, tmp_path: Path) -> None:
        target = tmp_path / "x.py"
        target.write_text("y\n")
        stub = _StubLspManager(raise_exc=RuntimeError("lsp dead"))
        ctx = ToolContext(
            working_directory=tmp_path,
            metadata={LSP_MANAGER_KEY: stub},
        )
        engine = _EngineShim(ctx)
        await engine._run_post_edit_lsp_hook("edit_file", {"path": "x.py"})
        # Hook swallowed the error per Rust parity ("must never block the agent").
        assert engine.pending_lsp_blocks == []

    async def test_apply_patch_routes_multiple_paths(self, tmp_path: Path) -> None:
        for name in ("a.py", "b.py"):
            (tmp_path / name).write_text("x\n")
        stub = _StubLspManager(
            blocks=[DiagnosticBlock(path="p", diagnostics=[])]
        )
        ctx = ToolContext(
            working_directory=tmp_path,
            metadata={LSP_MANAGER_KEY: stub},
        )
        engine = _EngineShim(ctx)
        await engine._run_post_edit_lsp_hook(
            "apply_patch",
            {"changes": [{"path": "a.py"}, {"path": "b.py"}]},
        )
        assert [call[0].name for call in stub.calls] == ["a.py", "b.py"]


class TestEngineFlush:
    async def test_flush_injects_user_message(self, tmp_path: Path) -> None:
        stub = _StubLspManager()
        ctx = ToolContext(
            working_directory=tmp_path,
            metadata={LSP_MANAGER_KEY: stub},
        )
        engine = _EngineShim(ctx)
        engine.pending_lsp_blocks = [
            DiagnosticBlock(
                path="x.py",
                diagnostics=[
                    Diagnostic(Severity.ERROR, 2, 3, "bad", "pyright"),
                ],
            )
        ]
        messages: list[Message] = []
        engine._flush_pending_lsp_diagnostics(messages)
        assert len(messages) == 1
        # Queue drained
        assert engine.pending_lsp_blocks == []
        assert messages[0].role == "user"
        rendered = _message_text(messages[0])
        assert "x.py" in rendered
        assert "bad" in rendered

    async def test_flush_noop_when_empty(self, tmp_path: Path) -> None:
        ctx = ToolContext(working_directory=tmp_path)
        engine = _EngineShim(ctx)
        messages: list[Message] = []
        engine._flush_pending_lsp_diagnostics(messages)
        assert messages == []


def _message_text(message: Message) -> str:
    """Pull plain text out of a Message for assertion convenience."""
    raw: Any = getattr(message, "content", "")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, dict):
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
            elif hasattr(block, "text"):
                t2 = getattr(block, "text", None)
                if isinstance(t2, str):
                    parts.append(t2)
        return "\n".join(parts)
    return str(raw)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
