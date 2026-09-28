"""LLM message and request models."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator

# ============================================================================
# Content blocks & Message
# ============================================================================


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class MessageOrigin(str, Enum):
    """Internal provenance for context assembly (not sent on the wire)."""

    REAL_USER = "real_user"
    SYSTEM_REMINDER = "system_reminder"
    COMPACTION_BRIDGE = "compaction_bridge"
    # Retired: soft seams (L1/L2/L3) no longer exist, so nothing writes this.
    # Kept because sessions persisted while they did still carry it on disk —
    # removing the member would fail to deserialize them.
    SOFT_SEAM = "soft_seam"
    CYCLE_SEED = "cycle_seed"
    # Harness-rendered replay of everything the human has asked for so far.
    # Distinct from REAL_USER: it is not a fresh turn, so it must not be read
    # as "the current request", and distinct from SYSTEM_REMINDER: its content
    # is the user's own words, which nothing may paraphrase away.
    REQUEST_LEDGER = "request_ledger"
    # Hidden goal-driver continuation. Not a fresh human request.
    GOAL_CONTINUATION = "goal_continuation"


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ThinkingBlock(BaseModel):
    type: Literal["thinking"] = "thinking"
    thinking: str
    signature: str | None = None


class ImageBlock(BaseModel):
    """Durable image reference; binary data never lives in the transcript."""

    type: Literal["image"] = "image"
    asset_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    mime_type: Literal[
        "image/png", "image/jpeg", "image/webp", "image/gif", "image/bmp", "image/tiff"
    ]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    byte_size: int = Field(gt=0)
    detail: Literal["auto", "low", "high"] = "auto"
    crop: tuple[int, int, int, int] | None = None

    @field_validator("crop")
    @classmethod
    def _validate_crop(
        cls, value: tuple[int, int, int, int] | None
    ) -> tuple[int, int, int, int] | None:
        if value is not None:
            x, y, width, height = value
            if x < 0 or y < 0 or width <= 0 or height <= 0:
                raise ValueError("crop requires nonnegative coordinates and positive dimensions")
        # Actual image bounds (including EXIF orientation) are checked by the encoder.
        return value


class ToolUseBlock(BaseModel):
    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False
    images: list[ImageBlock] = Field(default_factory=list)


ContentBlock = Annotated[
    TextBlock | ImageBlock | ThinkingBlock | ToolUseBlock | ToolResultBlock,
    Field(discriminator="type"),
]


class Message(BaseModel):
    role: Role
    content: list[ContentBlock] = Field(default_factory=list)
    # Session-local tag; ignored by API serializers that only read role/content.
    origin: MessageOrigin | None = None
    # Archived assets remain available for read_file without resending their pixels.
    image_references: list[ImageBlock] = Field(default_factory=list)

    @classmethod
    def system(cls, text: str, *, origin: MessageOrigin | None = None) -> Message:
        return cls(role=Role.SYSTEM, content=[TextBlock(text=text)], origin=origin)

    @classmethod
    def user(
        cls,
        text: str,
        *,
        origin: MessageOrigin | None = None,
        images: list[ImageBlock] | None = None,
    ) -> Message:
        return cls(role=Role.USER, content=[TextBlock(text=text), *(images or [])], origin=origin)

    @classmethod
    def assistant(cls, text: str, *, origin: MessageOrigin | None = None) -> Message:
        return cls(role=Role.ASSISTANT, content=[TextBlock(text=text)], origin=origin)

    @classmethod
    def assistant_with_tools(cls, blocks: list[ToolUseBlock]) -> Message:
        from typing import cast
        return cls(role=Role.ASSISTANT, content=cast(list[ContentBlock], blocks))

    @classmethod
    def tool_result(
        cls,
        tool_use_id: str,
        content: str,
        is_error: bool = False,
        *,
        images: list[ImageBlock] | None = None,
    ) -> Message:
        return cls(
            role=Role.TOOL,
            content=[
                ToolResultBlock(
                    tool_use_id=tool_use_id, content=content, is_error=is_error, images=images or []
                )
            ],
        )

    def text_content(self) -> str:
        """Join text blocks; empty string when none."""
        parts: list[str] = []
        for block in self.content:
            if isinstance(block, TextBlock) and block.text:
                parts.append(block.text)
        return "\n".join(parts)


# ============================================================================
# MessageRequest (formerly requests.py)
# ============================================================================


class MessageRequest(BaseModel):
    model: str = Field(min_length=1, pattern=r"\S")
    messages: list[Message] = Field(default_factory=list)
    system_prompt: str | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_choice: str | dict[str, Any] | None = None
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, allow_inf_nan=False)
    top_p: float | None = Field(default=None, allow_inf_nan=False)
    reasoning_effort: str | None = None
    extra_body: dict[str, Any] = Field(default_factory=dict)
    stream: bool = True
