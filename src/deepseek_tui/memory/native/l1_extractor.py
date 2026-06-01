"""L1 memory extraction via LLM."""

from __future__ import annotations

import inspect
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.memory.formatting import sanitize_memory_text
from deepseek_tui.memory.native.l1_dedup import PendingMemory, batch_dedup
from deepseek_tui.memory.native.store import MemoryStore
from deepseek_tui.memory.prompts.l1_extraction import (
    EXTRACT_MEMORIES_SYSTEM_PROMPT,
    format_extraction_user_prompt,
)
from deepseek_tui.protocol.messages import Message
from deepseek_tui.protocol.requests import MessageRequest
from deepseek_tui.protocol.responses import StreamTextDelta

logger = logging.getLogger(__name__)

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")
_SYMBOL_ONLY_RE = re.compile(r"^[^\w\s\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]{1,5}$")
_QUESTION_ONLY_RE = re.compile(r"^[?？]+$")


def _parse_extraction_response(raw: str) -> list[dict[str, Any]]:
    text = raw.strip()
    if not text:
        return []
    match = _JSON_ARRAY_RE.search(text)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def _priority_to_confidence(priority: Any) -> float:
    try:
        p = float(priority)
    except (TypeError, ValueError):
        return 0.0
    if p < 0:
        return 1.0
    return max(0.0, min(1.0, p / 100.0))


def should_extract_l1(text: str) -> bool:
    """Strict L1 quality gate; L0 remains the permissive evidence archive."""
    cleaned = sanitize_memory_text(text)
    if not cleaned:
        return False
    if cleaned.startswith("/"):
        return False
    if _SYMBOL_ONLY_RE.match(cleaned):
        return False
    if _QUESTION_ONLY_RE.match(cleaned):
        return False
    return True


def _clean_message_for_l1(message: dict[str, Any]) -> dict[str, Any] | None:
    content = sanitize_memory_text(str(message.get("content", "") or ""))
    if not should_extract_l1(content):
        return None
    cleaned = dict(message)
    cleaned["content"] = content
    return cleaned


@dataclass(slots=True)
class ExtractionResult:
    inserted: int = 0
    scenes: list[dict[str, Any]] | None = None
    committed_scenes: list[dict[str, Any]] | None = None
    last_scene_name: str | None = None


class L1Extractor:
    def __init__(
        self,
        client: LLMClient,
        store: MemoryStore,
        *,
        model: str,
        confidence_min: float,
        max_per_session: int,
        insert_memory: Callable[..., Awaitable[str | None]] | None = None,
    ) -> None:
        self._client = client
        self._store = store
        self._model = model
        self._confidence_min = confidence_min
        self._max_per_session = max_per_session
        self._insert_memory = insert_memory

    async def extract_and_store(
        self,
        thread_id: str,
        new_messages: list[dict[str, Any]],
        *,
        workspace: str,
        background_messages: list[dict[str, Any]] | None = None,
        previous_scene_name: str = "无",
    ) -> ExtractionResult:
        if not new_messages:
            return ExtractionResult()

        qualified_messages = [
            cleaned
            for msg in new_messages
            if (cleaned := _clean_message_for_l1(msg)) is not None
        ]
        if not qualified_messages:
            logger.debug("l1_extraction_skipped_quality_gate thread_id=%s", thread_id)
            return ExtractionResult()
        qualified_background = [
            cleaned
            for msg in (background_messages or [])
            if (cleaned := _clean_message_for_l1(msg)) is not None
        ]

        user_prompt = format_extraction_user_prompt(
            qualified_messages,
            background_messages=qualified_background,
            previous_scene_name=previous_scene_name,
        )
        request = MessageRequest(
            model=self._model,
            messages=[Message.user(user_prompt)],
            system_prompt=EXTRACT_MEMORIES_SYSTEM_PROMPT,
            max_tokens=2048,
        )
        chunks: list[str] = []
        try:
            stream = self._client.stream_with_retry(request)
            if not hasattr(stream, "__aiter__"):
                if inspect.isawaitable(stream):
                    await stream
                return ExtractionResult()
            async for event in stream:
                if isinstance(event, StreamTextDelta):
                    chunks.append(event.text)
        except Exception:
            logger.exception("l1_extraction_llm_failed thread_id=%s", thread_id)
            return ExtractionResult()

        scenes = _parse_extraction_response("".join(chunks))
        scene_names: list[str] = []
        pending: list[PendingMemory] = []
        for scene in scenes:
            scene_name = str(scene.get("scene_name", "") or "").strip()
            if scene_name:
                scene_names.append(scene_name)
            memories = scene.get("memories") or []
            if not isinstance(memories, list):
                continue
            for mem in memories:
                if not isinstance(mem, dict):
                    continue
                content = str(mem.get("content", "") or "").strip()
                mem_type = str(mem.get("type", "episodic") or "episodic")
                if mem_type not in ("persona", "episodic", "instruction"):
                    mem_type = "episodic"
                raw_priority = mem.get("priority")
                confidence = _priority_to_confidence(raw_priority)
                if confidence < self._confidence_min:
                    continue
                try:
                    priority = int(float(raw_priority))
                except (TypeError, ValueError):
                    priority = int(round(confidence * 100))
                source_ids_raw = mem.get("source_message_ids") or []
                source_message_ids = (
                    [str(x) for x in source_ids_raw]
                    if isinstance(source_ids_raw, list)
                    else []
                )
                metadata_raw = mem.get("metadata") or {}
                metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
                timestamps: list[str] = []
                for key in ("activity_start_time", "activity_end_time"):
                    value = metadata.get(key)
                    if value:
                        timestamps.append(str(value))
                pending.append(
                    PendingMemory(
                        record_id=f"new_{len(pending)}",
                        content=content,
                        type=mem_type,
                        priority=priority,
                        scene_name=scene_name,
                        source_message_ids=source_message_ids,
                        metadata=metadata,
                        timestamps=timestamps,
                        confidence=confidence,
                    )
                )
                if len(pending) >= self._max_per_session:
                    break
            if len(pending) >= self._max_per_session:
                break

        decisions = await batch_dedup(
            self._client,
            model=self._model,
            store=self._store,
            memories=pending,
            workspace=workspace,
        )
        inserted = 0
        committed_scene_names: set[str] = set()
        for memory in pending:
            decision = decisions.get(memory.record_id)
            if decision and decision.action == "skip":
                continue
            final_content = (
                decision.merged_content
                if decision and decision.action in ("update", "merge") and decision.merged_content
                else memory.content
            )
            final_type = (
                decision.merged_type
                if decision and decision.action in ("update", "merge") and decision.merged_type
                else memory.type
            )
            final_priority = (
                decision.merged_priority
                if decision and decision.action in ("update", "merge")
                and decision.merged_priority is not None
                else memory.priority
            )
            final_timestamps = (
                decision.merged_timestamps
                if decision and decision.action in ("update", "merge")
                and decision.merged_timestamps is not None
                else memory.timestamps
            )
            action = decision.action if decision else "store"
            target_ids = decision.target_ids if decision else []
            if self._insert_memory is not None:
                mem_id = await self._insert_memory(
                    content=final_content,
                    mem_type=final_type,
                    workspace=workspace,
                    thread_id=thread_id,
                    confidence=_priority_to_confidence(final_priority),
                    priority=final_priority,
                    scene_name=memory.scene_name,
                    source_message_ids=memory.source_message_ids,
                    metadata=memory.metadata,
                    timestamps=final_timestamps,
                    session_key=thread_id,
                    session_id="",
                    action=action,
                    target_ids=target_ids,
                )
            else:
                if action in ("update", "merge") and target_ids:
                    self._store.delete_memories(target_ids)
                mem_id = self._store.insert_memory(
                    content=final_content,
                    mem_type=final_type,
                    workspace=workspace,
                    thread_id=thread_id,
                    confidence=_priority_to_confidence(final_priority),
                    priority=final_priority,
                    scene_name=memory.scene_name,
                    source_message_ids=memory.source_message_ids,
                    metadata=memory.metadata,
                    timestamps=final_timestamps,
                    session_key=thread_id,
                    session_id="",
                    allow_duplicate=action in ("update", "merge"),
                )
            if mem_id:
                inserted += 1
                if memory.scene_name:
                    committed_scene_names.add(memory.scene_name)
        committed = [
            s for s in scenes
            if str(s.get("scene_name", "") or "").strip() in committed_scene_names
        ] if committed_scene_names else None
        return ExtractionResult(
            inserted=inserted,
            scenes=scenes,
            committed_scenes=committed,
            last_scene_name=scene_names[-1] if scene_names else None,
        )
