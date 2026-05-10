"""``rlm`` tool adapter.

Mirror Rust ``crates/tui/src/tools/rlm.rs`` (406 LOC). Validates input,
loads ``file_path`` (preferred) or ``content`` into ``context``, then
dispatches to :func:`run_rlm_turn`. Returns the synthesized answer +
trace summary as the tool result.
"""

from __future__ import annotations

from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.tools.base import (
    ApprovalRequirement,
    ToolCapability,
    ToolError,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.rlm.turn import RlmTermination, run_rlm_turn

DEFAULT_CHILD_MODEL: str = "deepseek-v4-flash"
DEFAULT_MAX_DEPTH: int = 1
MAX_INLINE_CONTENT_CHARS: int = 200_000


class RlmTool(ToolSpec):
    """The ``rlm`` tool — recursive language model over a long input.

    Mirror Rust ``RlmTool`` (rlm.rs:35).
    """

    def __init__(self, client: LLMClient | None, root_model: str) -> None:
        self._client = client
        self._root_model = root_model

    def name(self) -> str:
        return "rlm"

    def description(self) -> str:
        return (
            "Specialty tool for processing long inputs that don't fit in your "
            "own context window. Loads the input into a sandboxed Python REPL "
            "as `PROMPT`; a sub-agent writes Python that chunks the input and "
            "calls in-REPL helpers (`llm_query`, `llm_query_batched`, "
            "`rlm_query`, `rlm_query_batched`) to process it, then returns a "
            "synthesized answer.\n\n"
            "DO NOT use this tool when: the input fits in your context (just "
            "use `read_file` and reason directly); a `grep_files` / "
            "`exec_shell` pipeline would answer the question; the task is a "
            "short classification or extraction; you need interactive "
            "iterative exploration (rlm is one-shot batch).\n\n"
            "Use this tool only when the input is genuinely too large to load "
            "(a whole file > 50K tokens, a long transcript, a multi-document "
            "corpus). It is slower and more expensive than direct reasoning.\n\n"
            "Provide `task` (what to do) plus exactly one of `file_path` "
            "(workspace-relative, preferred — keeps the long input out of "
            "your context entirely) or `content` (inline, capped at 200k "
            "chars). The Python helpers (`llm_query`, `rlm_query`, etc.) live "
            "INSIDE the REPL — they are not separately-callable tools.\n\n"
            "Returns the final synthesized answer as a string."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["task"],
            "properties": {
                "task": {
                    "type": "string",
                    "description": (
                        'What to do with the input (e.g. "Summarize the security '
                        'model", "Extract all API endpoints", "Categorize each '
                        'row by sentiment"). The sub-agent uses this as its '
                        "objective."
                    ),
                },
                "file_path": {
                    "type": "string",
                    "description": (
                        "Workspace-relative path to a file to load as PROMPT. "
                        "Preferred — keeps the long input out of your context. "
                        "Mutually exclusive with `content`."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Inline content to load as PROMPT. Use only when the "
                        "input isn't a file you can point at. Capped at 200k "
                        "chars."
                    ),
                },
                "child_model": {
                    "type": "string",
                    "description": (
                        "Model for sub-LLM (`llm_query`) calls inside the REPL. "
                        f"Default: {DEFAULT_CHILD_MODEL}."
                    ),
                },
                "max_depth": {
                    "type": "integer",
                    "description": (
                        "Recursion budget for `sub_rlm()` calls. 0 disables "
                        "recursion; default 1 matches paper experiments."
                    ),
                },
            },
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.NETWORK, ToolCapability.EXECUTES_CODE]

    def approval_requirement(self) -> ApprovalRequirement:
        return ApprovalRequirement.AUTO

    def supports_parallel(self) -> bool:
        return True

    async def execute(
        self, input_data: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        if self._client is None:
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
            if len(body_str) > MAX_INLINE_CONTENT_CHARS:
                raise ToolError(
                    f"rlm: inline `content` is {len(body_str)} chars "
                    f"(cap {MAX_INLINE_CONTENT_CHARS}). Pass `file_path` "
                    "for larger inputs."
                )
            body = body_str

        if not body.strip():
            raise ToolError("rlm: input is empty after loading")

        child_model = (
            str(input_data.get("child_model") or "").strip() or DEFAULT_CHILD_MODEL
        )
        max_depth = int(input_data.get("max_depth", DEFAULT_MAX_DEPTH))

        result = await run_rlm_turn(
            client=self._client,
            model=self._root_model,
            prompt=body,
            root_prompt=task,
            child_model=child_model,
            max_depth=max_depth,
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
        text = f"{result.answer}{footer}{trace_summary}"

        metadata = {
            "iterations": result.iterations,
            "duration_ms": int(result.duration_secs * 1000),
            "termination": result.termination.value,
            "child_model": child_model,
            "max_depth": max_depth,
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


__all__ = ["DEFAULT_CHILD_MODEL", "DEFAULT_MAX_DEPTH", "RlmTool"]
