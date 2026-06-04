"""Thin wrapper around the memory subagent loop."""

from __future__ import annotations

from deepseek_tui.client.base import LLMClient
from deepseek_tui.memory.native.agent_loop import (
    MemorySubagentLoopResult,
    run_memory_subagent_loop,
)
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.registry import ToolRegistry


async def run_bounded_tool_loop(
    client: LLMClient,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    registry: ToolRegistry,
    context: ToolContext,
    max_steps: int = 8,
    max_tokens: int = 4096,
) -> MemorySubagentLoopResult:
    return await run_memory_subagent_loop(
        client,
        model=model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        registry=registry,
        context=context,
        max_steps=max_steps,
        max_tokens=max_tokens,
    )
