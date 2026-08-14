"""Soft-resume reminder text for interrupted/failed Workbench turns.

Builds a structured ``CONTINUE_NUDGE`` that lists resumable sub-agents
and tasks so the parent model prefers resume over re-spawn.
"""

from __future__ import annotations

from typing import Any

from deepseek_tui.tools.durable_transcript import CONTINUE_NUDGE

_SUMMARY_LIMIT = 80

_RESUMABLE_AGENT_KINDS = frozenset({"failed", "cancelled", "interrupted"})


def _clip(text: str, limit: int = _SUMMARY_LIMIT) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def _agent_status_kind(agent: Any) -> str:
    status = getattr(agent, "status", None)
    kind = getattr(status, "kind", None)
    if kind is None:
        return ""
    return str(getattr(kind, "value", kind) or "")


def _agent_objective(agent: Any) -> str:
    assignment = getattr(agent, "assignment", None)
    objective = getattr(assignment, "objective", None)
    if isinstance(objective, str) and objective.strip():
        return objective.strip()
    return ""


def is_resumable_agent(agent: Any) -> bool:
    return _agent_status_kind(agent) in _RESUMABLE_AGENT_KINDS


def is_resumable_task(task: Any) -> bool:
    status = getattr(task, "status", None)
    checker = getattr(status, "is_resumable", None)
    if callable(checker):
        return bool(checker())
    value = getattr(status, "value", status)
    return str(value or "") in {"failed", "canceled", "timed_out"}


def build_soft_resume_reminder(
    agents: list[Any] | None = None,
    tasks: list[Any] | None = None,
) -> str:
    """Return reminder body (without ``<system-reminder>`` wrapper).

    When no resumable entities are present, falls back to the generic
    ``CONTINUE_NUDGE`` so soft-resume behavior does not regress.
    """
    lines: list[str] = [CONTINUE_NUDGE]
    agent_lines: list[str] = []
    for agent in agents or []:
        if not is_resumable_agent(agent):
            continue
        agent_id = str(getattr(agent, "agent_id", "") or "").strip()
        if not agent_id:
            continue
        kind = _agent_status_kind(agent)
        objective = _clip(_agent_objective(agent))
        steps = getattr(agent, "steps_taken", None)
        parts = [f"- subagent {agent_id} ({kind}"]
        if isinstance(steps, int) and steps > 0:
            parts[0] += f", steps={steps}"
        parts[0] += ")"
        if objective:
            parts.append(f" objective={objective}")
        agent_lines.append("".join(parts))

    task_lines: list[str] = []
    for task in tasks or []:
        if not is_resumable_task(task):
            continue
        task_id = str(getattr(task, "id", "") or "").strip()
        if not task_id:
            continue
        status = getattr(task, "status", None)
        status_s = str(getattr(status, "value", status) or "")
        summary = getattr(task, "prompt_summary", None)
        if not isinstance(summary, str) or not summary.strip():
            summary = getattr(task, "prompt", None)
        summary_s = _clip(summary if isinstance(summary, str) else "")
        line = f"- task {task_id} ({status_s})"
        if summary_s:
            line += f" prompt={summary_s}"
        task_lines.append(line)

    if not agent_lines and not task_lines:
        return CONTINUE_NUDGE

    lines.append("")
    lines.append(
        "The previous turn was cut short. The following entities can be "
        "resumed from durable checkpoints — prefer resume; do not spawn a "
        "new sub-agent or create a new task for the same objective:"
    )
    lines.extend(agent_lines)
    lines.extend(task_lines)
    if agent_lines:
        lines.append(
            'For each listed subagent, call agent with only resume="<id>" '
            "(no action). Do not use action=\"spawn\" for the same work."
        )
    if task_lines:
        lines.append(
            'For each listed task, call task_create with only resume="<id>" '
            "(no prompt). Do not create a new task with a fresh prompt."
        )
    return "\n".join(lines)
