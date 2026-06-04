"""Background evolution review runner."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.evolution.prompts import (
    COMBINED_REVIEW_USER,
    EVOLUTION_REVIEW_SYSTEM,
    FLUSH_USER,
    MEMORY_REVIEW_USER,
    SKILL_REVIEW_USER,
)
from deepseek_tui.evolution.protocols import EvolutionBackend, ExperienceMutation
from deepseek_tui.post_turn.evidence import TurnEvidence
from deepseek_tui.post_turn.subagent_runner import run_bounded_tool_loop
from deepseek_tui.tools.context import ToolContext
from deepseek_tui.tools.memory_curate_tool import MemoryCurateTool
from deepseek_tui.tools.registry import ToolRegistry
from deepseek_tui.tools.skill_manage_tool import SkillManageTool


def build_review_user_prompt(
    evidence: TurnEvidence,
    *,
    review_memory: bool,
    review_skill: bool,
    flush_mode: bool = False,
) -> str:
    if flush_mode:
        header = FLUSH_USER
    elif review_memory and review_skill:
        header = COMBINED_REVIEW_USER
    elif review_memory:
        header = MEMORY_REVIEW_USER
    else:
        header = SKILL_REVIEW_USER
    transcript = _format_messages(evidence.messages)
    return (
        f"{header}\n\n"
        f"Thread: {evidence.thread_id}\n"
        f"User turn #{evidence.user_turn_index}\n"
        f"Workspace: {evidence.workspace}\n\n"
        f"## Transcript\n{transcript}"
    )


async def run_evolution_review(
    client: LLMClient,
    *,
    model: str,
    evidence: TurnEvidence,
    backends: list[EvolutionBackend],
    ledger: object | None,
    review_memory: bool,
    review_skill: bool,
    flush_mode: bool = False,
    max_steps: int = 8,
    workspace: Path | None = None,
    curated_store: object | None = None,
    skill_store: object | None = None,
) -> list[ExperienceMutation]:
    registry = ToolRegistry()
    if review_memory or flush_mode:
        registry.register(MemoryCurateTool())
    if review_skill or flush_mode:
        registry.register(SkillManageTool())

    ws = workspace or Path(evidence.workspace)
    context = ToolContext(working_directory=ws)
    context.metadata["evolution_review_mode"] = True
    from deepseek_tui.evolution.constants import (
        CURATED_MEMORY_STORE_KEY,
        EVOLUTION_LEDGER_KEY,
        SKILL_STORE_KEY,
        TURN_EVIDENCE_KEY,
    )

    if curated_store is not None:
        context.metadata[CURATED_MEMORY_STORE_KEY] = curated_store
    if skill_store is not None:
        context.metadata[SKILL_STORE_KEY] = skill_store
    if ledger is not None:
        context.metadata[EVOLUTION_LEDGER_KEY] = ledger
        context.metadata[TURN_EVIDENCE_KEY] = evidence

    user_prompt = build_review_user_prompt(
        evidence,
        review_memory=review_memory,
        review_skill=review_skill,
        flush_mode=flush_mode,
    )
    result = await run_bounded_tool_loop(
        client,
        model=model,
        system_prompt=EVOLUTION_REVIEW_SYSTEM,
        user_prompt=user_prompt,
        registry=registry,
        context=context,
        max_steps=max_steps,
    )
    tool_results = getattr(result, "tool_results", [])
    return collect_mutations_from_tool_results(tool_results, backends)


def collect_mutations_from_tool_results(
    tool_results: list[tuple[str, dict[str, Any], str]],
    backends: list[EvolutionBackend],
) -> list[ExperienceMutation]:
    successful = [
        (name, args, output)
        for name, args, output in tool_results
        if _tool_output_indicates_success(output)
    ]
    mutations: list[ExperienceMutation] = []
    for backend in backends:
        mutations.extend(backend.mutations_from_subagent_tool_results(successful))
    return mutations


def _tool_output_indicates_success(output: str) -> bool:
    if not output or output.startswith("Error:"):
        return False
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    return payload.get("ok") is True


def _format_messages(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for msg in copy.deepcopy(messages)[-40:]:
        role = msg.get("role", "?")
        content = str(msg.get("content", "") or "")
        if len(content) > 1200:
            content = content[:1200] + "…"
        lines.append(f"[{role}] {content}")
    return "\n".join(lines) if lines else "(empty)"
