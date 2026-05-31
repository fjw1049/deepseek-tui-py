"""Memory coordinator — gates, recall timeout, provider dispatch."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from deepseek_tui.memory.gates import should_capture_turn
from deepseek_tui.memory.provider import CaptureInput, MemoryProvider, RecallResult

if TYPE_CHECKING:
    from deepseek_tui.config.models import Config

logger = logging.getLogger(__name__)


class MemoryCoordinator:
    def __init__(self, config: Config, provider: MemoryProvider) -> None:
        self._config = config
        self._provider = provider
        self._smart = config.memory.smart

    @property
    def enabled(self) -> bool:
        return self._smart.enabled

    def _effective_memory_mode(self, thread_memory_mode: str | None) -> str:
        if thread_memory_mode and thread_memory_mode.strip():
            return thread_memory_mode.strip().lower()
        return self._config.memory.mode.strip().lower()

    def memory_md_enabled(self, thread_memory_mode: str | None = None) -> bool:
        """Whether ``memory.md`` should be injected (hybrid/manual)."""
        if not self._config.memory_enabled():
            return False
        mode = self._effective_memory_mode(thread_memory_mode)
        if self.enabled and mode == "auto":
            return False
        return mode in ("hybrid", "manual")

    def recall_enabled_for_turn(self, thread_memory_mode: str | None = None) -> bool:
        if not self.enabled or not self._smart.recall_enabled:
            return False
        mode = self._effective_memory_mode(thread_memory_mode)
        return mode in ("auto", "hybrid")

    async def start(self) -> None:
        if self.enabled:
            await self._provider.start()

    async def stop(self) -> None:
        if self.enabled:
            await self._provider.stop()

    async def recall_for_turn(
        self,
        thread_id: str,
        user_text: str,
        *,
        workspace: str,
        thread_memory_mode: str | None = None,
    ) -> RecallResult | None:
        if not self.recall_enabled_for_turn(thread_memory_mode):
            return None
        timeout_s = self._smart.recall_timeout_ms / 1000.0
        try:
            return await asyncio.wait_for(
                self._provider.recall(thread_id, user_text, workspace=workspace),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "memory_recall_timeout thread_id=%s timeout_ms=%d",
                thread_id,
                self._smart.recall_timeout_ms,
            )
            return None
        except Exception:
            logger.exception("memory_recall_failed thread_id=%s", thread_id)
            return None

    def should_capture_turn(
        self,
        user_text: str,
        *,
        had_tool_calls: bool,
        success: bool,
    ) -> bool:
        if not self.enabled or not self._smart.capture_enabled:
            return False
        return should_capture_turn(
            user_text,
            had_tool_calls=had_tool_calls,
            success=success,
            min_chars=self._smart.capture_min_user_chars,
            skip_slash=self._smart.capture_skip_slash_commands,
        )

    async def capture_after_turn(
        self,
        *,
        thread_id: str,
        user_text: str,
        workspace: str,
        messages: list[dict],
        had_tool_calls: bool,
        success: bool,
    ) -> None:
        if not self.should_capture_turn(
            user_text, had_tool_calls=had_tool_calls, success=success
        ):
            return
        try:
            await self._provider.capture(
                CaptureInput(
                    thread_id=thread_id,
                    user_text=user_text,
                    workspace=workspace,
                    messages=messages,
                    had_tool_calls=had_tool_calls,
                    success=success,
                )
            )
        except Exception:
            logger.exception("memory_capture_failed thread_id=%s", thread_id)

    async def flush_session(self, thread_id: str) -> None:
        if self.enabled:
            await self._provider.flush_session(thread_id)

    @property
    def provider(self) -> MemoryProvider:
        return self._provider

    async def search_memories(
        self,
        query: str,
        *,
        workspace: str,
        limit: int = 5,
        mem_type: str | None = None,
    ) -> str:
        if not self.enabled:
            return "Smart memory is disabled. Enable [memory.smart] in config."
        return await self._provider.search_memories(
            query, workspace=workspace, limit=limit, mem_type=mem_type
        )

    async def search_conversations(
        self,
        query: str,
        *,
        workspace: str,
        thread_id: str | None = None,
        limit: int = 5,
    ) -> str:
        if not self.enabled:
            return "Smart memory is disabled. Enable [memory.smart] in config."
        return await self._provider.search_conversations(
            query,
            workspace=workspace,
            thread_id=thread_id,
            limit=limit,
        )
