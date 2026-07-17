"""Seam manager — append-only layered context management with Flash.

Produces `<archived_context>` blocks using a cheap/fast summarization model,
preserving the prefix cache by appending summaries rather than replacing messages.
"""

from __future__ import annotations



import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepseek_tui.client.base import LLMClient
    from deepseek_tui.protocol.messages import Message

# --- Defaults ----------------------------------------------------------------

DEFAULT_SEAM_MODEL = "deepseek-v4-flash"
VERBATIM_WINDOW_TURNS = 5

L1_MAX_TOKENS = 3_200
L2_MAX_TOKENS = 2_400
L3_MAX_TOKENS = 1_600


@dataclass(slots=True)
class SeamConfig:
    """Flash seam manager config — ratios of the live model window."""

    enabled: bool = True
    verbatim_window_turns: int = VERBATIM_WINDOW_TURNS
    l1_ratio: float = 0.20
    l2_ratio: float = 0.40
    l3_ratio: float = 0.55
    seam_model: str = DEFAULT_SEAM_MODEL
    # Absolute thresholds filled by :meth:`apply_window` before each check.
    l1_threshold: int = 0
    l2_threshold: int = 0
    l3_threshold: int = 0

    def apply_window(self, window: int) -> None:
        """Derive absolute token thresholds from *window* × ratios."""
        w = max(1, int(window))
        self.l1_threshold = int(w * self.l1_ratio)
        self.l2_threshold = int(w * self.l2_ratio)
        self.l3_threshold = int(w * self.l3_ratio)


@dataclass(slots=True)
class SeamMetadata:
    """Metadata for a single soft seam block."""

    level: int
    start_idx: int
    end_idx: int
    token_estimate: int
    timestamp: float  # Unix epoch
    model: str


class SeamManager:
    """Flash seam manager — produces `<archived_context>` summary blocks."""

    def __init__(self, flash_client: LLMClient, config: SeamConfig | None = None) -> None:
        self._flash_client = flash_client
        self.config = config or SeamConfig()
        self._active_seams: list[SeamMetadata] = []
        self._lock = asyncio.Lock()

    @property
    def seam_count(self) -> int:
        return len(self._active_seams)

    def seam_level_for(
        self, active_input_tokens: int, highest_existing_level: int | None = None
    ) -> int | None:
        """Determine which seam level (if any) should fire."""
        return seam_level_for_active_input(
            self.config, active_input_tokens, highest_existing_level
        )

    def verbatim_window_start(self, message_count: int) -> int:
        """Compute start index of the verbatim window (never summarized)."""
        turn_count = message_count // 2
        verbatim_turns = min(self.config.verbatim_window_turns, turn_count)
        verbatim_messages = min(verbatim_turns * 2, message_count)
        return max(0, message_count - verbatim_messages)

    async def produce_soft_seam(
        self,
        messages: list[Message],
        level: int,
        start_idx: int,
        end_idx: int,
        pinned_indices: list[int] | None = None,
    ) -> str:
        """Produce an `<archived_context>` block for the given range.

        Returns the XML block as a string, ready to be appended.
        """
        if not messages or start_idx >= end_idx:
            return ""

        end_idx = min(end_idx, len(messages))
        msg_range = messages[start_idx:end_idx]
        if not msg_range:
            return ""

        to_summarize = _filter_unpinned(msg_range, pinned_indices, start_idx)
        if not to_summarize:
            return ""

        summary = await self._summarize_messages(to_summarize, level, start_idx, end_idx)

        import time

        from deepseek_tui.engine.context import estimate_tokens

        timestamp = time.time()
        token_estimate = estimate_tokens(summary)

        async with self._lock:
            self._active_seams.append(
                SeamMetadata(
                    level=level,
                    start_idx=start_idx,
                    end_idx=end_idx,
                    token_estimate=token_estimate,
                    timestamp=timestamp,
                    model=self.config.seam_model,
                )
            )

        from datetime import datetime, timezone

        ts_iso = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        return (
            f'<archived_context level="{level}" range="msg {start_idx}-{end_idx}" '
            f'tokens="~{token_estimate}" model="{self.config.seam_model}" '
            f'timestamp="{ts_iso}">\n'
            f"{summary}\n"
            f"</archived_context>"
        )

    async def recompact(
        self,
        existing_seams: list[str],
        new_messages: list[Message],
        level: int,
        start_idx: int,
        end_idx: int,
    ) -> str:
        """Re-compact existing seams into a higher-level block."""
        parts: list[str] = [
            "## Prior Context Summaries\n\n"
            "The following <archived_context> blocks were produced earlier. "
            "Merge their key information into a single denser summary.\n\n"
        ]

        for i, seam in enumerate(existing_seams, 1):
            parts.append(f"### Seam {i}\n{seam}\n\n")

        if new_messages:
            parts.append("## Recent Messages\n\n")
            for msg in new_messages:
                role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
                text = _extract_text_from_message(msg)
                if text:
                    parts.append(f"**{role}:** {text}\n\n")

        input_text = "".join(parts)
        max_tokens, word_limit = _level_limits(level)

        from deepseek_tui.protocol.messages import Message as Msg
        from deepseek_tui.protocol.messages import MessageRequest
        from deepseek_tui.protocol.responses import StreamTextDelta

        request = MessageRequest(
            model=self.config.seam_model,
            messages=[
                Msg.user(
                    f"Synthesize the following context into a single dense summary. "
                    f"Preserve: decisions made, file paths, error messages, constraints, "
                    f"hypotheses, open questions, and task state. "
                    f"Drop: greeting, filler, repeated information. "
                    f"Keep it under {word_limit} words.\n\n{input_text}"
                )
            ],
            system_prompt=(
                "You are a context compaction specialist. Produce dense, factual summaries "
                "that preserve every decision, path, error, constraint, and open question."
            ),
            max_tokens=max_tokens,
            temperature=0.1,
        )

        result_text: list[str] = []
        async for event in self._flash_client.stream_chat_completion(request):
            if isinstance(event, StreamTextDelta):
                result_text.append(event.text)

        summary = "".join(result_text)

        import time

        from deepseek_tui.engine.context import estimate_tokens

        timestamp = time.time()
        token_estimate = estimate_tokens(summary)

        async with self._lock:
            self._active_seams.append(
                SeamMetadata(
                    level=level,
                    start_idx=start_idx,
                    end_idx=end_idx,
                    token_estimate=token_estimate,
                    timestamp=timestamp,
                    model=self.config.seam_model,
                )
            )

        from datetime import datetime, timezone

        ts_iso = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()
        return (
            f'<archived_context level="{level}" range="msg {start_idx}-{end_idx}" '
            f'tokens="~{token_estimate}" model="{self.config.seam_model}" '
            f'timestamp="{ts_iso}">\n'
            f"{summary}\n"
            f"</archived_context>"
        )

    async def produce_flash_briefing(
        self,
        existing_seams: list[str],
        structured_state: str | None = None,
    ) -> str:
        """Produce a cycle briefing from existing seams using Flash."""
        from deepseek_tui.engine.cycle import (
            CYCLE_HANDOFF_PROMPT_PATH,
            extract_carry_forward,
        )
        from deepseek_tui.protocol.messages import Message as Msg
        from deepseek_tui.protocol.messages import MessageRequest
        from deepseek_tui.protocol.responses import StreamTextDelta

        parts: list[str] = [
            "## Briefing Request\n\n"
            "Produce a <carry_forward> block summarizing the session state. "
            "Include: decisions made + why, constraints discovered, "
            "hypotheses being tested, approaches that failed, open questions. "
            "Do NOT include tool output bytes, file contents, or step-by-step recaps.\n\n"
        ]

        if structured_state:
            parts.append(f"## Structured State\n\n{structured_state}\n\n")

        if existing_seams:
            parts.append("## Prior Context Summaries\n\n")
            for i, seam in enumerate(existing_seams, 1):
                parts.append(f"### Seam {i}\n{seam}\n\n")
        else:
            parts.append(
                "No prior context summaries available. Produce a brief carry-forward "
                "from the structured state alone.\n"
            )

        input_text = "".join(parts)

        try:
            system = CYCLE_HANDOFF_PROMPT_PATH.read_text(encoding="utf-8")
        except OSError:
            system = "Produce a <carry_forward> block summarizing the session state."

        request = MessageRequest(
            model=self.config.seam_model,
            messages=[Msg.user(input_text)],
            system_prompt=system,
            max_tokens=4096,
            temperature=0.2,
        )

        result_text: list[str] = []
        async for event in self._flash_client.stream_chat_completion(request):
            if isinstance(event, StreamTextDelta):
                result_text.append(event.text)

        raw = "".join(result_text)
        return extract_carry_forward(raw)

    def collect_seam_texts(self, messages: list[Message]) -> list[str]:
        """Collect `<archived_context>` soft-seam blocks from message history."""
        from deepseek_tui.protocol.messages import MessageOrigin

        texts: list[str] = []
        for msg in messages:
            origin = getattr(msg, "origin", None)
            role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
            # Soft seams are user-role reminders; keep reading legacy assistant
            # seams so older sessions still recompact correctly.
            if origin is not MessageOrigin.SOFT_SEAM and role not in {
                "user",
                "assistant",
            }:
                continue
            for block in msg.content:
                if hasattr(block, "text"):
                    text = block.text
                    if (
                        isinstance(text, str)
                        and "<archived_context" in text
                        and 'level="' in text
                    ):
                        texts.append(text)
        return texts

    async def highest_level(self) -> int | None:
        """Get the highest seam level currently recorded."""
        async with self._lock:
            if self._active_seams:
                return self._active_seams[-1].level
            return None

    async def reset(self) -> None:
        """Clear seam tracking (called on hard cycle reset)."""
        async with self._lock:
            self._active_seams.clear()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _summarize_messages(
        self, messages: list[Message], level: int, start_idx: int, end_idx: int
    ) -> str:
        """Summarize a slice of messages using Flash."""
        from deepseek_tui.protocol.messages import Message as Msg
        from deepseek_tui.protocol.messages import MessageRequest
        from deepseek_tui.protocol.responses import StreamTextDelta

        conversation = _messages_to_conversation_text(messages)
        max_tokens, word_limit = _level_limits(level)

        request = MessageRequest(
            model=self.config.seam_model,
            messages=[
                Msg.user(
                    f"Summarize the following conversation segment "
                    f"(messages {start_idx}-{end_idx}). "
                    f"Preserve: key decisions and their rationale, exact file paths, "
                    f"command invocations, error messages, tool-result facts, constraints "
                    f"discovered, hypotheses being tested, and open questions. "
                    f"Drop: greetings, filler, repeated information, and thinking blocks. "
                    f"Keep it under {word_limit} words.\n\n---\n\n{conversation}"
                )
            ],
            system_prompt=(
                "You are a context summarization specialist. Produce dense, factual summaries "
                "that preserve every decision, path, error, constraint, and open question. "
                "Never omit a file path, error message, or decision rationale."
            ),
            max_tokens=max_tokens,
            temperature=0.1,
        )

        result_text: list[str] = []
        async for event in self._flash_client.stream_chat_completion(request):
            if isinstance(event, StreamTextDelta):
                result_text.append(event.text)

        return "".join(result_text)


# ===========================================================================
# Pure logic functions
# ===========================================================================


def seam_level_for_active_input(
    config: SeamConfig, active_input_tokens: int, highest_existing_level: int | None = None
) -> int | None:
    """Determine seam level for active input tokens.

    Each level fires at most once, and only in order.
    """
    if not config.enabled:
        return None
    if config.l1_threshold <= 0:
        config.apply_window(1_000_000)
    highest = highest_existing_level or 0

    if highest < 1 and active_input_tokens >= config.l1_threshold:
        return 1
    if highest < 2 and active_input_tokens >= config.l2_threshold:
        return 2
    if highest < 3 and active_input_tokens >= config.l3_threshold:
        return 3
    return None


def truncate_chars(text: str, max_chars: int) -> str:
    """Truncate a string to max_chars, respecting Unicode."""
    if max_chars == 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


# ===========================================================================
# Helpers
# ===========================================================================


def _level_limits(level: int) -> tuple[int, int]:
    """Return (max_tokens, word_limit) for a seam level."""
    if level == 1:
        return (L1_MAX_TOKENS, 800)
    elif level == 2:
        return (L2_MAX_TOKENS, 600)
    else:
        return (L3_MAX_TOKENS, 400)


def _filter_unpinned(
    msg_range: list[Message], pinned_indices: list[int] | None, start_idx: int
) -> list[Message]:
    """Filter out pinned messages from a range."""
    if not pinned_indices:
        return list(msg_range)
    end = start_idx + len(msg_range)
    local_pins = {
        idx - start_idx for idx in pinned_indices if start_idx <= idx < end
    }
    return [msg for i, msg in enumerate(msg_range) if i not in local_pins]


def _extract_text_from_message(msg: Message) -> str:
    """Extract text content from a message."""
    parts: list[str] = []
    for block in msg.content:
        if hasattr(block, "text"):
            parts.append(block.text)
        elif hasattr(block, "name"):
            parts.append(f"[Tool: {block.name}]")
        elif hasattr(block, "content"):
            parts.append(truncate_chars(str(block.content), 200))
    return " ".join(parts)


def _messages_to_conversation_text(messages: list[Message]) -> str:
    """Convert messages to a text representation for summarization."""
    parts: list[str] = []
    for msg in messages:
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)
        label = "User" if role == "user" else "Assistant"
        for block in msg.content:
            if hasattr(block, "text"):
                snippet = truncate_chars(block.text, 800)
                parts.append(f"{label}: {snippet}\n")
            elif hasattr(block, "name"):
                parts.append(f"{label}: [Used tool: {block.name}]\n")
            elif hasattr(block, "content"):
                snippet = truncate_chars(str(block.content), 200)
                parts.append(f"Tool result: {snippet}\n")
    return "\n".join(parts)
