"""L1 memory extraction via LLM."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Any

from deepseek_tui.client.base import LLMClient
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


@dataclass(slots=True)
class ExtractionResult:
    inserted: int = 0
    scenes: list[dict[str, Any]] | None = None


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
    ) -> ExtractionResult:
        if not new_messages:
            return ExtractionResult()

        user_prompt = format_extraction_user_prompt(
            new_messages,
            background_messages=background_messages,
        )
        request = MessageRequest(
            model=self._model,
            messages=[Message.user(user_prompt)],
            system_prompt=EXTRACT_MEMORIES_SYSTEM_PROMPT,
            max_tokens=2048,
        )
        chunks: list[str] = []
        try:
            async for event in self._client.stream_with_retry(request):
                if isinstance(event, StreamTextDelta):
                    chunks.append(event.text)
        except Exception:
            logger.exception("l1_extraction_llm_failed thread_id=%s", thread_id)
            return ExtractionResult()

        scenes = _parse_extraction_response("".join(chunks))
        inserted = 0
        for scene in scenes:
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
                confidence = _priority_to_confidence(mem.get("priority"))
                if confidence < self._confidence_min:
                    continue
                if self._insert_memory is not None:
                    mem_id = await self._insert_memory(
                        content=content,
                        mem_type=mem_type,
                        workspace=workspace,
                        thread_id=thread_id,
                        confidence=confidence,
                    )
                else:
                    mem_id = self._store.insert_memory(
                        content=content,
                        mem_type=mem_type,
                        workspace=workspace,
                        thread_id=thread_id,
                        confidence=confidence,
                    )
                if mem_id:
                    inserted += 1
                    if inserted >= self._max_per_session:
                        return ExtractionResult(inserted=inserted, scenes=scenes)
        return ExtractionResult(inserted=inserted, scenes=scenes)
