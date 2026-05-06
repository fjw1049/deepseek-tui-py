from __future__ import annotations

from dataclasses import dataclass, field

from deepseek_tui.protocol.messages import ContentBlock, Message, Role, TextBlock, ThinkingBlock


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
