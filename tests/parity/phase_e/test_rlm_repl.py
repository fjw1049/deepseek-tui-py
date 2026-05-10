"""RLM in-process REPL parity tests.

Mirror behaviour-level tests from ``crates/tui/src/repl/runtime.rs`` and
``crates/tui/src/rlm/turn.rs`` — namespace persistence, FINAL detection,
helper exposure, error capture, and round-trip prompt parsing.
"""

from __future__ import annotations

import asyncio

import pytest

from deepseek_tui.tools.rlm import (
    RlmTermination,
    extract_repl_code,
    parse_text_final,
    rlm_system_prompt,
    run_rlm_turn,
)
from deepseek_tui.tools.rlm.repl import ReplRuntime, build_sub_llm_helpers

# ---------------------------------------------------------------------------
# REPL runtime
# ---------------------------------------------------------------------------


def _spawn(context: str = "hello world") -> ReplRuntime:
    runtime_ref: list[ReplRuntime] = [None]  # type: ignore[list-item]

    async def _llm(_p: str, _m: str | None, _mt: int | None, _s: str | None) -> str:
        return "child-answer"

    async def _llm_batch(prompts: list[str], _m: str | None) -> list[str]:
        return [f"child-{i}" for i in range(len(prompts))]

    async def _rlm(_p: str, _m: str | None) -> str:
        return "rlm-answer"

    async def _rlm_batch(prompts: list[str], _m: str | None) -> list[str]:
        return [f"rlm-{i}" for i in range(len(prompts))]

    helpers = build_sub_llm_helpers(
        runtime_ref,
        sync_run=lambda coro: asyncio.run(coro),  # type: ignore[arg-type]
        llm_one=_llm,
        llm_batch=_llm_batch,
        rlm_one=_rlm,
        rlm_batch=_rlm_batch,
    )
    runtime = ReplRuntime.spawn(context, helpers)
    runtime_ref[0] = runtime
    return runtime


def test_context_is_available_in_repl() -> None:
    runtime = _spawn(context="hello world")
    round_ = runtime.run("print(context)")
    assert round_.full_stdout.strip() == "hello world"
    assert not round_.has_error


def test_ctx_alias_available() -> None:
    runtime = _spawn(context="abc")
    round_ = runtime.run("print(ctx)")
    assert round_.full_stdout.strip() == "abc"


def test_namespace_persists_across_rounds() -> None:
    runtime = _spawn()
    runtime.run("x = 41")
    second = runtime.run("print(x + 1)")
    assert second.full_stdout.strip() == "42"


def test_final_breaks_loop_with_string() -> None:
    runtime = _spawn()
    round_ = runtime.run('FINAL("done")')
    assert round_.final_value == "done"
    assert not round_.has_error


def test_final_var_breaks_loop_with_named_value() -> None:
    runtime = _spawn()
    runtime.run("answer = 'hi'")
    round_ = runtime.run("FINAL_VAR('answer')")
    assert round_.final_value == "hi"


def test_unhandled_exception_marks_error() -> None:
    runtime = _spawn()
    round_ = runtime.run("raise RuntimeError('boom')")
    assert round_.has_error
    assert "boom" in round_.stderr


def test_forbidden_builtins_are_removed() -> None:
    runtime = _spawn()
    round_ = runtime.run("eval('1+1')")
    assert round_.has_error
    assert "eval" in round_.stderr.lower()


def test_show_vars_lists_user_state() -> None:
    runtime = _spawn()
    runtime.run("x = 1\ny = 'hello'")
    round_ = runtime.run("print(SHOW_VARS())")
    assert "x" in round_.full_stdout
    assert "y" in round_.full_stdout


def test_repl_set_get_round_trip() -> None:
    runtime = _spawn()
    runtime.run("repl_set('z', 99)")
    round_ = runtime.run("print(repl_get('z'))")
    assert round_.full_stdout.strip() == "99"


def test_helpers_bump_rpc_count() -> None:
    runtime = _spawn()
    round_ = runtime.run('out = llm_query("ping"); print(out)')
    assert round_.rpc_count == 1
    assert "child-answer" in round_.full_stdout
    runtime2 = _spawn()
    round2 = runtime2.run("llm_query_batched(['a', 'b', 'c'])")
    assert round2.rpc_count == 3


def test_stdout_truncation_keeps_full_in_full_stdout() -> None:
    runtime = _spawn()
    runtime.stdout_limit = 32
    round_ = runtime.run("print('x' * 200)")
    assert len(round_.stdout) <= 32 + len("\n…[truncated]")
    assert len(round_.full_stdout) >= 200


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def test_extract_repl_block_basic() -> None:
    text = "preamble\n```repl\nprint(1)\n```\ntrailer"
    assert extract_repl_code(text) == "print(1)"


def test_extract_repl_falls_back_to_python_fence() -> None:
    text = "```python\nprint(2)\n```"
    assert extract_repl_code(text) == "print(2)"


def test_extract_repl_returns_none_when_missing() -> None:
    assert extract_repl_code("just prose") is None


def test_parse_text_final_double_quoted() -> None:
    assert parse_text_final('FINAL("answer")') == "answer"


def test_parse_text_final_single_quoted() -> None:
    assert parse_text_final("FINAL('answer')") == "answer"


def test_parse_text_final_unquoted_returns_none() -> None:
    assert parse_text_final("FINAL(answer_var)") is None


def test_parse_text_final_no_match() -> None:
    assert parse_text_final("nothing here") is None


# ---------------------------------------------------------------------------
# System prompt invariants (matches Rust prompt.rs::tests)
# ---------------------------------------------------------------------------


def test_system_prompt_is_not_empty() -> None:
    assert rlm_system_prompt().strip()


def test_system_prompt_uses_repl_fence() -> None:
    assert "```repl" in rlm_system_prompt()


def test_system_prompt_mentions_context_variable() -> None:
    assert "`context`" in rlm_system_prompt()


def test_system_prompt_mentions_ctx_alias() -> None:
    assert "`ctx`" in rlm_system_prompt()


def test_system_prompt_lists_all_helpers() -> None:
    body = rlm_system_prompt()
    for name in (
        "llm_query",
        "llm_query_batched",
        "rlm_query",
        "rlm_query_batched",
        "SHOW_VARS",
        "FINAL",
        "FINAL_VAR",
    ):
        assert name in body, f"missing helper: {name}"


def test_system_prompt_forbids_prose_shortcut() -> None:
    body = rlm_system_prompt().lower()
    assert "rejected" in body


# ---------------------------------------------------------------------------
# Turn loop (driver)
# ---------------------------------------------------------------------------


class _StubClient:
    """Minimal LLMClient stub for driver tests.

    Returns a queued sequence of responses so we can simulate the Rust
    behaviour rounds: NoCode → CodeWithRpc → FINAL.
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    async def stream_with_retry(self, _request):  # type: ignore[no-untyped-def]
        from deepseek_tui.protocol.responses import StreamTextDelta

        body = self._responses.pop(0) if self._responses else ""
        yield StreamTextDelta(text=body)


@pytest.mark.asyncio
async def test_turn_loop_terminates_on_final_after_rpc() -> None:
    responses = [
        # Round 1: root LLM emits repl block calling llm_query.
        "```repl\nresult = llm_query('ping')\nprint(result)\n```",
        # Sub-LLM call dispatched from inside the repl block.
        "child-answer",
        # Round 2: root LLM emits FINAL.
        "```repl\nFINAL('all done')\n```",
    ]
    client = _StubClient(responses)
    result = await run_rlm_turn(
        client=client,  # type: ignore[arg-type]
        model="root",
        prompt="big body of text",
        root_prompt="summarise",
        child_model="child",
        max_depth=0,
    )
    assert result.termination == RlmTermination.FINAL
    assert result.answer == "all done"
    assert result.total_rpcs >= 1


@pytest.mark.asyncio
async def test_turn_loop_rejects_final_without_rpc() -> None:
    # Three rounds of plain FINAL — no repl block, no rpc — should
    # eventually return NoCode after MAX_CONSECUTIVE_NO_CODE.
    responses = ['FINAL("guess")', 'FINAL("guess")', 'FINAL("guess")']
    client = _StubClient(responses)
    result = await run_rlm_turn(
        client=client,  # type: ignore[arg-type]
        model="root",
        prompt="body",
        root_prompt=None,
        child_model="child",
        max_depth=0,
    )
    assert result.termination == RlmTermination.NO_CODE
    assert result.total_rpcs == 0
