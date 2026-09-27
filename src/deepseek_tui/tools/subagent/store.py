"""Per-agent records, with read-only migration of the legacy registry."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from deepseek_tui.tools.subagent.agent import SubAgent
from deepseek_tui.tools.subagent.types import (
    SUBAGENT_RESTART_REASON,
    SUBAGENT_STATE_SCHEMA_VERSION,
    SubAgentAssignment,
    SubAgentStatus,
    SubAgentStatusKind,
    SubAgentType,
    _epoch_ms,
)
from deepseek_tui.utils import write_json_atomic

logger = logging.getLogger(__name__)


def agent_record(agent: SubAgent) -> dict[str, Any]:
    return {
        "schema_version": SUBAGENT_STATE_SCHEMA_VERSION,
        "id": agent.id,
        "agent_type": agent.agent_type.value,
        "prompt": agent.prompt,
        "assignment": {"objective": agent.assignment.objective, "role": agent.assignment.role},
        "model": agent.model,
        "nickname": agent.nickname,
        "status": agent.status.to_dict(),
        "result": agent.result,
        "structured_result": agent.structured_result,
        "structured_received": agent.structured_received,
        "steps_taken": agent.steps_taken,
        "max_steps_reached": agent.max_steps_reached,
        "started_at_ms": agent.started_at_ms,
        "ended_at_ms": agent.ended_at_ms,
        "duration_ms": agent.snapshot().duration_ms,
        "allowed_tools": agent.allowed_tools,
        "system_prompt": agent.system_prompt,
        "output_schema": agent.output_schema,
        "background": agent.background,
        "workspace": str(agent.workspace),
        "session_boot_id": agent.session_boot_id,
        "spawn_depth": agent.spawn_depth,
    }


def restore_agent(raw: dict[str, Any], workspace: Path, default_model: str) -> SubAgent:
    version = raw.get("schema_version", SUBAGENT_STATE_SCHEMA_VERSION)
    if version not in (1, SUBAGENT_STATE_SCHEMA_VERSION):
        raise RuntimeError(f"Unsupported sub-agent state schema {version}")
    agent_id = raw["id"]
    if (
        not isinstance(agent_id, str)
        or not agent_id.startswith("agent_")
        or not all(c.isalnum() or c == "_" for c in agent_id)
    ):
        raise ValueError("Invalid sub-agent id")
    agent = SubAgent(
        agent_type=SubAgentType(raw["agent_type"]),
        prompt=raw["prompt"],
        assignment=SubAgentAssignment(
            objective=raw["assignment"]["objective"], role=raw["assignment"].get("role")
        ),
        model=raw.get("model", default_model),
        nickname=raw.get("nickname"),
        allowed_tools=(raw.get("allowed_tools") or None)
        if version == 1
        else raw.get("allowed_tools"),
        session_boot_id=raw.get("session_boot_id", ""),
        workspace=Path(raw.get("workspace") or workspace),
        spawn_depth=int(raw.get("spawn_depth", 0) or 0),
        system_prompt=raw.get("system_prompt"),
        output_schema=raw.get("output_schema"),
        background=bool(raw.get("background", False)),
    )
    agent.id = agent_id
    agent.status = SubAgentStatus.from_dict(raw["status"])
    if agent.status.kind is SubAgentStatusKind.RUNNING:
        agent.status = SubAgentStatus.interrupted(SUBAGENT_RESTART_REASON)
    agent.result = raw.get("result")
    agent.structured_result = raw.get("structured_result")
    agent.structured_received = bool(
        raw.get("structured_received", agent.structured_result is not None)
    )
    agent.steps_taken = int(raw.get("steps_taken", 0))
    agent.max_steps_reached = bool(raw.get("max_steps_reached", False))
    duration = max(0, int(raw.get("duration_ms", 0)))
    agent.started_at_ms = int(raw.get("started_at_ms", _epoch_ms() - duration))
    agent.ended_at_ms = int(raw.get("ended_at_ms") or agent.started_at_ms + duration)
    return agent


class AgentStore:
    def __init__(self, legacy_path: Path) -> None:
        self.legacy_path = legacy_path
        self.directory = legacy_path.with_suffix(".agents")
        self.error: str | None = None

    def load(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        if self.legacy_path.exists():
            try:
                document = json.loads(self.legacy_path.read_text(encoding="utf-8"))
                version = document.get("schema_version")
                if version not in (1, SUBAGENT_STATE_SCHEMA_VERSION):
                    raise RuntimeError(f"Unsupported sub-agent state schema {version}")
                for raw in document["agents"]:
                    if isinstance(raw, dict) and isinstance(raw.get("id"), str):
                        records[raw["id"]] = dict(raw, schema_version=version)
            except (ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
                self.error = str(exc)
                logger.warning("Invalid sub-agent registry %s: %s", self.legacy_path, exc)
        for path in self.directory.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict) or raw.get("id") != path.stem:
                    raise ValueError("Sub-agent record id mismatch")
                if raw.get("deleted"):
                    records.pop(path.stem, None)
                else:
                    records[path.stem] = raw
            except (ValueError, OSError) as exc:
                self.error = str(exc)
                logger.warning("Invalid sub-agent record %s: %s", path, exc)
        return records

    def save(self, raw: dict[str, Any]) -> None:
        write_json_atomic(self.directory / f"{raw['id']}.json", raw)

    def remove(self, agent_id: str) -> None:
        # A tombstone also hides an entry from the read-only legacy registry.
        write_json_atomic(self.directory / f"{agent_id}.json", {"id": agent_id, "deleted": True})
