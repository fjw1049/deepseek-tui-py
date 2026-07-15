"""Durable turn-session transcripts for SubAgent / Task true resume.

Checkpoint boundary: a completed tool-round (assistant + all tool_results).
Never resume mid-tool.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TRANSCRIPT_SCHEMA_VERSION = 1
CONTINUE_NUDGE = (
    "Continue from the checkpoint above. Do not repeat tool calls whose "
    "results are already in the conversation; finish the original objective."
)


@dataclass
class DurableTranscript:
    schema_version: int = TRANSCRIPT_SCHEMA_VERSION
    owner_kind: str = ""
    owner_id: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    steps_taken: int = 0
    force_summary: bool = False
    round_complete: bool = True
    checkpoint_reason: str = "round"
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "owner_kind": self.owner_kind,
            "owner_id": self.owner_id,
            "messages": list(self.messages),
            "cursor": {
                "steps_taken": self.steps_taken,
                "force_summary": self.force_summary,
                "round_complete": self.round_complete,
            },
            "checkpoint_reason": self.checkpoint_reason,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DurableTranscript:
        cursor = raw.get("cursor") or {}
        return cls(
            schema_version=int(raw.get("schema_version") or TRANSCRIPT_SCHEMA_VERSION),
            owner_kind=str(raw.get("owner_kind") or ""),
            owner_id=str(raw.get("owner_id") or ""),
            messages=list(raw.get("messages") or []),
            steps_taken=int(cursor.get("steps_taken") or 0),
            force_summary=bool(cursor.get("force_summary") or False),
            round_complete=bool(cursor.get("round_complete", True)),
            checkpoint_reason=str(raw.get("checkpoint_reason") or "round"),
            updated_at=str(raw.get("updated_at") or ""),
        )


def subagent_transcript_path(workspace: Path, agent_id: str) -> Path:
    return workspace / ".deepseek" / "subagent-runs" / agent_id / "transcript.json"


def task_transcript_path(data_dir: Path, task_id: str) -> Path:
    return data_dir / "transcripts" / f"{task_id}.json"


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    try:
        tmp.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def save_transcript(path: Path, transcript: DurableTranscript) -> None:
    transcript.updated_at = _utc_now_iso()
    _write_json_atomic(path, transcript.to_dict())


def load_transcript(path: Path) -> DurableTranscript | None:
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return DurableTranscript.from_dict(raw)


def clear_transcript(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def messages_to_dicts(messages: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        dump = getattr(msg, "model_dump", None)
        if callable(dump):
            out.append(dump(mode="json"))
        elif isinstance(msg, dict):
            out.append(msg)
    return out


def dicts_to_messages(raw_messages: list[dict[str, Any]]) -> list[Any]:
    from deepseek_tui.protocol.messages import Message

    out: list[Any] = []
    for item in raw_messages:
        try:
            out.append(Message.model_validate(item))
        except Exception:  # noqa: BLE001
            continue
    return out
