"""``rlm`` tool declaration."""

from __future__ import annotations

from typing import Any

from deepseek_tui.capabilities.rlm import (
    DEFAULT_CHILD_MODEL,
    DEFAULT_MAX_DEPTH,
)
from deepseek_tui.client.base import LLMClient
from deepseek_tui.tools.base import (
    ApprovalRequirement,
    ToolCapability,
    ToolResult,
    ToolSpec,
)
from deepseek_tui.tools.context import ToolContext


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
            "synthesized answer. \n\n"
            "Use this tool when the input is genuinely large or when a Python "
            "map-reduce pass plus child LLM calls is the right shape: whole "
            "files, long transcripts, multi-document corpora, bulk semantic "
            "classification, or decomposition/critique work. For exact counts "
            "or structured aggregates, compute them directly in Python inside "
            "the REPL and report the deterministic result instead of asking a "
            "child LLM to guess. For whole-input map-reduce, use the REPL "
            "helpers `chunk_context()` and `chunk_coverage()` so the result "
            "states what was covered. \n\n"
            "Provide `task` (what to do) plus exactly one of `file_path` "
            "(workspace-relative, preferred — keeps the long input out of "
            "your context entirely) or `content` (inline, capped at 200k "
            "chars). The Python helpers (`llm_query`, `rlm_query`, etc.) live "
            "INSIDE the REPL — they are not separately-callable tools. \n\n"
            "Returns the final synthesized answer plus an RLM report showing "
            "input size, iterations, duration, sub-LLM calls, and trace summary."
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
        from deepseek_tui.capabilities.rlm import execute_rlm_tool

        return await execute_rlm_tool(
            client=self._client,
            root_model=self._root_model,
            input_data=input_data,
            context=context,
        )


__all__ = ["DEFAULT_CHILD_MODEL", "DEFAULT_MAX_DEPTH", "RlmTool"]
