"""Durable checkpoint state for the native memory pipeline."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RunnerThreadState:
    l0_last_timestamp_ms: int = 0
    l0_last_message_count: int = 0
    last_l1_cursor: str = ""
    last_scene_name: str = ""


@dataclass(slots=True)
class PipelineThreadState:
    conversation_count: int = 0
    warmup_threshold: int = 1
    l2_cursor: str = ""
    last_l1_at: int = 0
    last_l2_at: int = 0
    last_active_at: int = 0


@dataclass(slots=True)
class MemoryCheckpoint:
    total_processed: int = 0
    memories_since_last_persona: int = 0
    scenes_processed: int = 0
    last_persona_at: int = 0
    request_persona_update: bool = False
    persona_update_reason: str = ""
    runner_states: dict[str, RunnerThreadState] = field(default_factory=dict)
    pipeline_states: dict[str, PipelineThreadState] = field(default_factory=dict)


def _now_ms() -> int:
    return int(time.time() * 1000)


class CheckpointManager:
    """Read/write ``.metadata/recall_checkpoint.json`` atomically."""

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / ".metadata" / "recall_checkpoint.json"

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> MemoryCheckpoint:
        if not self._path.is_file():
            return MemoryCheckpoint()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return MemoryCheckpoint()
        if not isinstance(raw, dict):
            return MemoryCheckpoint()
        runner_states: dict[str, RunnerThreadState] = {}
        raw_runner_states = raw.get("runner_states") or {}
        if isinstance(raw_runner_states, dict):
            for thread_id, state in raw_runner_states.items():
                if not isinstance(state, dict):
                    continue
                runner_states[str(thread_id)] = RunnerThreadState(
                    l0_last_timestamp_ms=int(state.get("l0_last_timestamp_ms", 0) or 0),
                    l0_last_message_count=int(state.get("l0_last_message_count", 0) or 0),
                    last_l1_cursor=str(state.get("last_l1_cursor", "") or ""),
                    last_scene_name=str(state.get("last_scene_name", "") or ""),
                )
        states: dict[str, PipelineThreadState] = {}
        raw_states = raw.get("pipeline_states") or {}
        if isinstance(raw_states, dict):
            for thread_id, state in raw_states.items():
                if not isinstance(state, dict):
                    continue
                states[str(thread_id)] = PipelineThreadState(
                    conversation_count=int(state.get("conversation_count", 0) or 0),
                    warmup_threshold=int(state.get("warmup_threshold", 1) or 1),
                    l2_cursor=str(state.get("l2_cursor", "") or ""),
                    last_l1_at=int(state.get("last_l1_at", 0) or 0),
                    last_l2_at=int(state.get("last_l2_at", 0) or 0),
                    last_active_at=int(state.get("last_active_at", 0) or 0),
                )
        return MemoryCheckpoint(
            total_processed=int(raw.get("total_processed", 0) or 0),
            memories_since_last_persona=int(
                raw.get("memories_since_last_persona", 0) or 0
            ),
            scenes_processed=int(raw.get("scenes_processed", 0) or 0),
            last_persona_at=int(raw.get("last_persona_at", 0) or 0),
            request_persona_update=bool(raw.get("request_persona_update", False)),
            persona_update_reason=str(raw.get("persona_update_reason", "") or ""),
            runner_states=runner_states,
            pipeline_states=states,
        )

    def write(self, checkpoint: MemoryCheckpoint) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = asdict(checkpoint)
        tmp_path = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self._path)

    def update_runner_state(
        self,
        thread_id: str,
        *,
        l0_last_timestamp_ms: int | None = None,
        l0_last_message_count: int | None = None,
        last_l1_cursor: str | None = None,
        last_scene_name: str | None = None,
    ) -> MemoryCheckpoint:
        checkpoint = self.read()
        state = checkpoint.runner_states.get(thread_id, RunnerThreadState())
        if l0_last_timestamp_ms is not None:
            state.l0_last_timestamp_ms = l0_last_timestamp_ms
        if l0_last_message_count is not None:
            state.l0_last_message_count = l0_last_message_count
        if last_l1_cursor is not None:
            state.last_l1_cursor = last_l1_cursor
        if last_scene_name is not None:
            state.last_scene_name = last_scene_name
        checkpoint.runner_states[thread_id] = state
        self.write(checkpoint)
        return checkpoint

    def update_thread(
        self,
        thread_id: str,
        *,
        l1_processed: int = 0,
        l2_cursor: str | None = None,
        l2_completed: bool = False,
    ) -> MemoryCheckpoint:
        checkpoint = self.read()
        state = checkpoint.pipeline_states.get(thread_id, PipelineThreadState())
        now = _now_ms()
        state.last_active_at = now
        if l1_processed:
            state.last_l1_at = now
            checkpoint.total_processed += l1_processed
            checkpoint.memories_since_last_persona += l1_processed
        if l2_cursor is not None:
            state.l2_cursor = l2_cursor
        if l2_completed:
            state.last_l2_at = now
        checkpoint.pipeline_states[thread_id] = state
        self.write(checkpoint)
        return checkpoint

    def mark_l2_completed(
        self,
        thread_id: str,
        *,
        scenes_processed: int,
        latest_cursor: str = "",
        persona_update_reason: str = "",
    ) -> MemoryCheckpoint:
        checkpoint = self.read()
        state = checkpoint.pipeline_states.get(thread_id, PipelineThreadState())
        now = _now_ms()
        state.last_l2_at = now
        state.last_active_at = now
        if latest_cursor:
            state.l2_cursor = latest_cursor
        checkpoint.scenes_processed += scenes_processed
        if persona_update_reason:
            checkpoint.request_persona_update = True
            checkpoint.persona_update_reason = persona_update_reason
        checkpoint.pipeline_states[thread_id] = state
        self.write(checkpoint)
        return checkpoint

    def mark_persona_generated(self) -> MemoryCheckpoint:
        checkpoint = self.read()
        checkpoint.last_persona_at = _now_ms()
        checkpoint.memories_since_last_persona = 0
        checkpoint.request_persona_update = False
        checkpoint.persona_update_reason = ""
        self.write(checkpoint)
        return checkpoint
