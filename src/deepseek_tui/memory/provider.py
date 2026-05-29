"""Memory provider protocol — mirrors TencentDB ``MemoryProvider`` surface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

InjectPosition = Literal["user", "system_volatile"]


@dataclass(slots=True)
class RecallResult:
    """Structured recall payload for prompt assembly."""

    l1_context: str = ""
    append_system: str = ""
    inject_position: InjectPosition = "user"


@dataclass(slots=True)
class CaptureInput:
    thread_id: str
    user_text: str
    workspace: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    had_tool_calls: bool = False
    success: bool = True


@runtime_checkable
class MemoryProvider(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def recall(
        self,
        thread_id: str,
        query: str,
        *,
        workspace: str | None = None,
    ) -> RecallResult: ...

    async def capture(self, inp: CaptureInput) -> None: ...

    async def flush_session(self, thread_id: str) -> None: ...

    async def search_memories(
        self,
        query: str,
        *,
        workspace: str | None = None,
        limit: int = 5,
        mem_type: str | None = None,
    ) -> str: ...

    async def search_conversations(
        self,
        query: str,
        *,
        workspace: str | None = None,
        thread_id: str | None = None,
        limit: int = 5,
    ) -> str: ...
