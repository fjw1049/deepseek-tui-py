"""Memory coordinator — orchestration, provider, gates, formatting.

Consolidates coordinator.py, provider.py, factory.py, gates.py, formatting.py, user_memory.py.
"""

from __future__ import annotations



# ======================================================================
# From coordinator.py
# ======================================================================

"""Memory coordinator — gates, recall timeout, provider dispatch."""


import asyncio
import logging
from typing import TYPE_CHECKING


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
        if not self.enabled:
            return
        timeout_s = self._smart.flush_timeout_ms / 1000.0
        try:
            await asyncio.wait_for(
                self._provider.flush_session(thread_id),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "memory_flush_timeout thread_id=%s timeout_ms=%d "
                "(pending work resumes via checkpoint)",
                thread_id,
                self._smart.flush_timeout_ms,
            )
        except Exception:
            logger.exception("memory_flush_failed thread_id=%s", thread_id)

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
        exclude_thread_id: str | None = None,
        limit: int = 5,
        summarize: bool = True,
    ) -> str:
        if not self.enabled:
            return "Smart memory is disabled. Enable [memory.smart] in config."
        return await self._provider.search_conversations(
            query,
            workspace=workspace,
            thread_id=thread_id,
            exclude_thread_id=exclude_thread_id,
            limit=limit,
            summarize=summarize,
        )


# ======================================================================
# From provider.py
# ======================================================================

"""Memory provider protocol — mirrors TencentDB ``MemoryProvider`` surface."""


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
        exclude_thread_id: str | None = None,
        limit: int = 5,
        summarize: bool = True,
    ) -> str: ...


# ======================================================================
# From factory.py
# ======================================================================

"""Create the native smart-memory provider."""


from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.config.models import Config


def create_smart_memory_provider(config: "Config", client: "LLMClient") -> "MemoryProvider":
    """Instantiate ``NativeMemoryProvider`` (L0+L1+FTS, local ``memory_data``)."""
    from deepseek_tui.memory.seed import NativeMemoryProvider
    if not config.smart_memory_enabled():
        raise ValueError("smart memory is disabled in config")
    return NativeMemoryProvider(config, client)


# ======================================================================
# From gates.py
# ======================================================================

"""Turn capture quality gates for memory."""


_CONFIRMATION_PATTERNS = frozenset({"y", "yes", "ok", "sure", "go ahead", "do it", "proceed"})


def should_capture_turn(
    user_text: str,
    *,
    had_tool_calls: bool,
    success: bool,
    min_chars: int = 20,
    skip_slash: bool = True,
    skip_confirmations: bool = True,
) -> bool:
    """Decide whether a turn is worth capturing to memory."""
    if not success:
        return False
    text = user_text.strip()
    if not text:
        return False
    if skip_slash and text.startswith("/"):
        return False
    if skip_confirmations and text.lower() in _CONFIRMATION_PATTERNS:
        return False
    if len(text) < min_chars and not had_tool_calls:
        return False
    return True


__all__ = ["should_capture_turn"]


# ======================================================================
# From formatting.py
# ======================================================================

"""``<relevant-memories>`` block formatting — TencentDB parity."""


import re
import time

_RELEVANT_MEMORIES_OPEN = "<relevant-memories>"
_RELEVANT_MEMORIES_CLOSE = "</relevant-memories>"
_STRIP_PATTERN = re.compile(
    r"<relevant-memories>[\s\S]*?</relevant-memories>\s*",
    re.IGNORECASE,
)
_INJECTED_CONTEXT_PATTERNS = [
    re.compile(r"<relevant-memories>[\s\S]*?</relevant-memories>\s*", re.IGNORECASE),
    re.compile(r"<user-persona>[\s\S]*?</user-persona>\s*", re.IGNORECASE),
    re.compile(r"<persona>[\s\S]*?</persona>\s*", re.IGNORECASE),
    re.compile(r"<scene-navigation>[\s\S]*?</scene-navigation>\s*", re.IGNORECASE),
    re.compile(r"<relevant-scenes>[\s\S]*?</relevant-scenes>\s*", re.IGNORECASE),
    re.compile(r"<memory-tools-guide>[\s\S]*?</memory-tools-guide>\s*", re.IGNORECASE),
    re.compile(r"<current_task_context>[\s\S]*?</current_task_context>\s*", re.IGNORECASE),
    re.compile(r"<history_task_context[\s\S]*?</history_task_context>\s*", re.IGNORECASE),
]
_BASE64_IMAGE_RE = re.compile(
    r"data:image/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]+",
    re.IGNORECASE,
)
_MEDIA_MARKER_RE = re.compile(r"\[media attached:[^\]]*\]\s*", re.IGNORECASE)
_TIMESTAMP_PREFIX_RE = re.compile(r"^\[[\w\d\-:+ ]+\]\s*", re.MULTILINE)
_REPLY_DIRECTIVE_RE = re.compile(r"\[\[reply_to[^\]]*\]\]\s*", re.IGNORECASE)
_CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.DOTALL)


def wrap_relevant_memories(user_text: str, l1_context: str) -> str:
    """Prepend recall block to the user message (inject_position=user)."""
    body = l1_context.strip()
    if not body:
        return user_text
    block = f"{_RELEVANT_MEMORIES_OPEN}\n{body}\n{_RELEVANT_MEMORIES_CLOSE}"
    if not user_text.strip():
        return block
    return f"{block}\n\n{user_text}"


def wrap_relevant_memories_system_block(l1_context: str) -> str:
    """Volatile system-layer injection (inject_position=system_volatile)."""
    body = l1_context.strip()
    if not body:
        return ""
    return f"{_RELEVANT_MEMORIES_OPEN}\n{body}\n{_RELEVANT_MEMORIES_CLOSE}"


def strip_relevant_memories(text: str) -> str:
    """Remove recall blocks before durable persistence."""
    if _RELEVANT_MEMORIES_OPEN not in text:
        return text
    return _STRIP_PATTERN.sub("", text).strip()


def strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks from assistant text before L1 extraction."""
    return _CODE_BLOCK_RE.sub("", text).strip()


def sanitize_memory_text(text: str) -> str:
    """Clean framework-injected context and media noise before memory persistence."""
    cleaned = text
    for pattern in _INJECTED_CONTEXT_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    cleaned = _BASE64_IMAGE_RE.sub("", cleaned)
    cleaned = _MEDIA_MARKER_RE.sub("", cleaned)
    cleaned = _REPLY_DIRECTIVE_RE.sub("", cleaned)
    cleaned = _TIMESTAMP_PREFIX_RE.sub("", cleaned)
    cleaned = cleaned.replace("\0", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def format_activity_time(created_at_ms: int) -> str:
    """Human-readable relative time for recall injection."""
    elapsed = int(time.time() * 1000) - created_at_ms
    if elapsed < 0:
        return "刚刚"
    minutes = elapsed // 60_000
    if minutes < 1:
        return "刚刚"
    if minutes < 60:
        return f"{minutes}分钟前"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}小时前"
    days = hours // 24
    if days < 30:
        return f"{days}天前"
    months = days // 30
    return f"{months}个月前"


def escape_memory_xml_tags(text: str) -> str:
    """Escape tags that could break out of memory injection wrappers."""
    return re.sub(
        r"</?(?:user-persona|persona|relevant-memories|scene-navigation|"
        r"relevant-scenes|memory-tools-guide|system|assistant)>",
        lambda m: m.group(0).replace("<", "&lt;").replace(">", "&gt;"),
        text,
        flags=re.IGNORECASE,
    )


# ======================================================================
# From user_memory.py
# ======================================================================

"""User-level memory file — mirrors ``crates/tui/src/memory.rs``."""


import os
from datetime import datetime, timezone
from pathlib import Path

MAX_MEMORY_SIZE = 100 * 1024

_TRUTHY = frozenset({"1", "on", "true", "yes", "y", "enabled"})
_FALSY = frozenset({"0", "off", "false", "no", "n", "disabled"})


def memory_enabled_from_env() -> bool | None:
    raw = os.getenv("DEEPSEEK_MEMORY", "").strip().lower()
    if not raw:
        return None
    if raw in _TRUTHY:
        return True
    if raw in _FALSY:
        return False
    return None


def load(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not content.strip():
        return None
    return content


def as_system_block(content: str, source: Path) -> str | None:
    trimmed = content.strip()
    if not trimmed:
        return None
    display = str(source.expanduser())
    if len(content) > MAX_MEMORY_SIZE:
        omitted = len(content) - MAX_MEMORY_SIZE
        payload = content[:MAX_MEMORY_SIZE]
        payload += f'\n<truncated bytes={omitted} source="{display}">'
    else:
        payload = trimmed
    return f'<user_memory source="{display}">\n{payload}\n</user_memory>'


def compose_block(enabled: bool, path: Path) -> str | None:
    if not enabled:
        return None
    content = load(path)
    if content is None:
        return None
    return as_system_block(content, path)


def append_entry(path: Path, entry: str) -> None:
    """Append a timestamped bullet; strips leading ``#`` from quick-add."""
    text = entry.strip()
    if text.startswith("#"):
        text = text[1:].strip()
    if not text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    line = f"- ({stamp}) {text}\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
