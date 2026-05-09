from __future__ import annotations

from dataclasses import dataclass, field

from deepseek_tui.protocol.messages import ContentBlock, Message, Role, TextBlock, ThinkingBlock

# Fake-wrapper filtering — mirrors Rust ``streaming.rs:73-137``.
# Some models try to forge tool calls in plain text instead of using the
# structured tool channel. We strip those wrappers so they don't pollute
# the visible transcript.

TOOL_CALL_START_MARKERS: tuple[str, ...] = (
    "[TOOL_CALL]",
    "<deepseek:tool_call",
    "<tool_call",
    "<invoke ",
    "<function_calls>",
)

TOOL_CALL_END_MARKERS: tuple[str, ...] = (
    "[/TOOL_CALL]",
    "</deepseek:tool_call>",
    "</tool_call>",
    "</invoke>",
    "</function_calls>",
)

FAKE_WRAPPER_NOTICE = (
    "Stripped non-API tool-call wrapper from model output "
    "(use the API tool channel)"
)


def contains_fake_tool_wrapper(text: str) -> bool:
    """Return True if *text* contains any known fake-wrapper start marker."""
    return any(m in text for m in TOOL_CALL_START_MARKERS)


def _find_first_marker(text: str, markers: tuple[str, ...]) -> tuple[int, int] | None:
    best: tuple[int, int] | None = None
    for marker in markers:
        idx = text.find(marker)
        if idx < 0:
            continue
        if best is None or idx < best[0]:
            best = (idx, len(marker))
    return best


@dataclass(slots=True)
class FakeWrapperFilter:
    """Stateful filter that strips fake tool-call wrappers across stream deltas.

    Mirrors Rust ``filter_tool_call_delta`` (streaming.rs:110-137). The
    ``in_tool_call`` flag persists across calls so a wrapper that spans
    chunk boundaries still gets stripped.
    """

    in_tool_call: bool = False

    def filter(self, delta: str) -> str:
        if not delta:
            return ""

        out: list[str] = []
        rest = delta
        while True:
            if self.in_tool_call:
                hit = _find_first_marker(rest, TOOL_CALL_END_MARKERS)
                if hit is None:
                    break
                idx, length = hit
                rest = rest[idx + length:]
                self.in_tool_call = False
            else:
                hit = _find_first_marker(rest, TOOL_CALL_START_MARKERS)
                if hit is None:
                    out.append(rest)
                    break
                idx, length = hit
                out.append(rest[:idx])
                rest = rest[idx + length:]
                self.in_tool_call = True
        return "".join(out)


@dataclass(slots=True)
class AssistantResponseBuffer:
    text_parts: list[str] = field(default_factory=list)
    thinking_parts: list[str] = field(default_factory=list)

    def append_text(self, text: str) -> None:
        self.text_parts.append(text)

    def append_thinking(self, thinking: str) -> None:
        self.thinking_parts.append(thinking)

    def has_output(self) -> bool:
        return bool(self.text_parts or self.thinking_parts)

    def build_message(self) -> Message | None:
        if not self.text_parts and not self.thinking_parts:
            return None
        blocks: list[ContentBlock] = []
        if self.thinking_parts:
            blocks.append(ThinkingBlock(thinking="".join(self.thinking_parts)))
        if self.text_parts:
            blocks.append(TextBlock(text="".join(self.text_parts)))
        return Message(role=Role.ASSISTANT, content=blocks)
