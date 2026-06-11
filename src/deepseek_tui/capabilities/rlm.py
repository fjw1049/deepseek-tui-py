"""RLM capability runtime wiring and tool execution helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.engine.events import RlmProgressEvent
from deepseek_tui.host.tool_execution import (
    RlmToolExecution,
    clear_tool_execution_if_empty,
    ensure_tool_execution,
    resolve_rlm_progress_cb,
)
from deepseek_tui.tools.base import ToolError, ToolResult
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.rlm.turn import RlmTermination, run_rlm_turn

DEFAULT_CHILD_MODEL: str = "deepseek-v4-flash"
DEFAULT_MAX_DEPTH: int = 1
MAX_INLINE_CONTENT_CHARS: int = 200_000


@contextmanager
def rlm_tool_bindings(
    context: ToolContext,
    *,
    emit: Callable[[object], bool],
) -> Iterator[None]:
    def _rlm_progress(iteration: int, summary: str, rpc_count: int = 0) -> None:
        emit(
            RlmProgressEvent(
                iteration=iteration,
                summary=summary,
                rpc_count=rpc_count,
            )
        )

    exec_ctx = ensure_tool_execution(context)
    prior_rlm = exec_ctx.rlm
    exec_ctx.rlm = RlmToolExecution(on_progress=_rlm_progress)
    try:
        yield
    finally:
        exec_ctx.rlm = prior_rlm
        clear_tool_execution_if_empty(context)


async def execute_rlm_tool(
    *,
    client: LLMClient | None,
    root_model: str,
    input_data: dict[str, Any],
    context: ToolContext,
) -> ToolResult:
    if client is None:
        raise ToolError("rlm_process requires an active DeepSeek client")

    task = (input_data.get("task") or "").strip()
    if not task:
        raise ToolError("rlm: `task` is empty")

    file_path = input_data.get("file_path")
    content = input_data.get("content")
    if file_path and content:
        raise ToolError("rlm: pass `file_path` OR `content`, not both")
    if not file_path and not content:
        raise ToolError("rlm: requires `file_path` (preferred) or `content`")

    if file_path:
        resolved = context.resolve_path(str(file_path))
        try:
            body = resolved.read_text(encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"rlm: read {resolved}: {exc}") from exc
    else:
        body_str = str(content)
        char_count = sum(1 for _ in body_str)
        if char_count > MAX_INLINE_CONTENT_CHARS:
            raise ToolError(
                f"rlm: inline `content` is {char_count} chars "
                f"(cap {MAX_INLINE_CONTENT_CHARS}). Pass `file_path` "
                "for larger inputs."
            )
        body = body_str

    if not body.strip():
        raise ToolError("rlm: input is empty after loading")

    input_chars = sum(1 for _ in body)
    input_lines = len(body.splitlines()) if body else 0

    # Pin child calls to Flash — model-generated args must not escalate cost.
    child_model = DEFAULT_CHILD_MODEL
    max_depth = int(input_data.get("max_depth", DEFAULT_MAX_DEPTH))

    progress_cb = resolve_rlm_progress_cb(context)
    result = await run_rlm_turn(
        client=client,
        model=root_model,
        prompt=body,
        root_prompt=task,
        child_model=child_model,
        max_depth=max_depth,
        on_progress=progress_cb,
    )

    if result.error:
        raise ToolError(
            f"rlm: {result.error} (iterations={result.iterations}, "
            f"termination={result.termination.value})"
        )
    if not result.answer.strip():
        raise ToolError(
            f"rlm: empty answer (termination={result.termination.value}, "
            f"iterations={result.iterations})"
        )

    footer = _termination_footer(result.termination, result.iterations)
    trace_summary = _trace_summary(result.trace)
    report = (
        "RLM report:\n"
        f"- input: {input_lines} line(s), {input_chars} char(s)\n"
        f"- iterations: {result.iterations}\n"
        f"- duration: {int(result.duration_secs * 1000)}ms\n"
        f"- sub-LLM RPCs: {result.total_rpcs}\n"
        f"- termination: {result.termination.value}\n\n"
        "Answer:\n"
    )
    text = f"{report}{result.answer}{footer}{trace_summary}"

    usage = result.usage
    metadata = {
        "iterations": result.iterations,
        "duration_ms": int(result.duration_secs * 1000),
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "child_input_tokens": usage.input_tokens,
        "child_output_tokens": usage.output_tokens,
        "child_prompt_cache_hit_tokens": usage.cache_read_input_tokens,
        "child_prompt_cache_miss_tokens": usage.cache_creation_input_tokens,
        "child_model": child_model,
        "termination": result.termination.value,
        "max_depth": max_depth,
        "context_chars": input_chars,
        "context_lines": input_lines,
        "total_rpcs": result.total_rpcs,
        "trace": [
            {
                "round": t.round,
                "rpc_count": t.rpc_count,
                "elapsed_ms": t.elapsed_ms,
                "had_error": t.had_error,
                "code_summary": t.code_summary,
                "stdout_preview": t.stdout_preview,
            }
            for t in result.trace
        ],
    }
    return ToolResult(success=True, content=text, metadata=metadata)


def _termination_footer(termination: RlmTermination, iterations: int) -> str:
    if termination == RlmTermination.FINAL:
        return ""
    if termination == RlmTermination.NO_CODE:
        return (
            f"\n\n[warning: sub-agent failed to engage the REPL after "
            f"{iterations} iterations — answer is the model's last raw response]"
        )
    if termination == RlmTermination.EXHAUSTED:
        return (
            f"\n\n[warning: sub-agent hit the {iterations}-iteration cap "
            "without FINAL()]"
        )
    return ""


def _trace_summary(trace: list[Any]) -> str:
    if not trace:
        return "\n\n[trace: no REPL rounds executed]"
    lines = ["\n\n[RLM trace]"]
    for r in trace:
        head = r.code_summary.splitlines()[0] if r.code_summary else ""
        head = head[:80]
        err_marker = " (error)" if r.had_error else ""
        lines.append(
            f"\n  round {r.round}: {r.rpc_count} sub-LLM call(s), "
            f"{r.elapsed_ms}ms{err_marker} — {head}"
        )
    return "".join(lines)
