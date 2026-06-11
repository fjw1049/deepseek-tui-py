from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.capabilities import rlm as rlm_capability
from deepseek_tui.capabilities.rlm import execute_rlm_tool
from deepseek_tui.tools.base import ToolError
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.rlm.turn import (
    RlmRoundTrace,
    RlmTermination,
    RlmTurnResult,
    RlmUsage,
)


@pytest.mark.asyncio
async def test_rlm_capability_requires_client(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)

    with pytest.raises(ToolError, match="requires an active DeepSeek client"):
        await execute_rlm_tool(
            client=None,
            root_model="deepseek-chat",
            input_data={"task": "summarize", "content": "hello"},
            context=context,
        )


@pytest.mark.asyncio
async def test_rlm_capability_rejects_large_inline_content(tmp_path: Path) -> None:
    context = ToolContext(working_directory=tmp_path)

    with pytest.raises(ToolError, match="inline `content` is"):
        await execute_rlm_tool(
            client=object(),  # type: ignore[arg-type]
            root_model="deepseek-chat",
            input_data={
                "task": "summarize",
                "content": "x" * (rlm_capability.MAX_INLINE_CONTENT_CHARS + 1),
            },
            context=context,
        )


@pytest.mark.asyncio
async def test_rlm_capability_executes_and_formats_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    async def _fake_run_rlm_turn(**kwargs: object) -> RlmTurnResult:
        calls.append(kwargs)
        return RlmTurnResult(
            answer="done",
            iterations=2,
            duration_secs=0.123,
            error=None,
            termination=RlmTermination.FINAL,
            total_rpcs=1,
            usage=RlmUsage(input_tokens=10, output_tokens=5),
            trace=[
                RlmRoundTrace(
                    round=1,
                    code_summary="print('hi')",
                    stdout_preview="hi",
                    had_error=False,
                    rpc_count=1,
                    elapsed_ms=7,
                )
            ],
        )

    monkeypatch.setattr(rlm_capability, "run_rlm_turn", _fake_run_rlm_turn)
    progress: list[tuple[int, str, int]] = []
    context = ToolContext(
        working_directory=tmp_path,
        metadata={"rlm_progress_cb": lambda *args: progress.append(args)},
    )

    result = await execute_rlm_tool(
        client=object(),  # type: ignore[arg-type]
        root_model="deepseek-chat",
        input_data={"task": "summarize", "content": "hello\nworld", "max_depth": 0},
        context=context,
    )

    assert result.success is True
    assert "RLM report:" in result.content
    assert "Answer:\ndone" in result.content
    assert result.metadata["iterations"] == 2
    assert result.metadata["child_model"] == rlm_capability.DEFAULT_CHILD_MODEL
    assert result.metadata["context_lines"] == 2
    assert calls[0]["root_prompt"] == "summarize"
    assert calls[0]["max_depth"] == 0
    assert callable(calls[0]["on_progress"])
