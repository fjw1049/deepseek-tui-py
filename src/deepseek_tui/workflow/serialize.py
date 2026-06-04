"""JSON-serializable views of workflow runtime state."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from deepseek_tui.workflow.models import WorkflowAgentRun, WorkflowSnapshot


def snapshot_to_dict(snapshot: WorkflowSnapshot) -> dict[str, Any]:
    """Convert a snapshot for SSE / ToolResult metadata."""
    data = asdict(snapshot)
    data["agents"] = [asdict(a) for a in snapshot.agents]
    return data


def agent_run_to_dict(run: WorkflowAgentRun) -> dict[str, Any]:
    return asdict(run)
