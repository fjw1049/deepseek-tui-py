"""Types for user-attached file context expansion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(slots=True)
class ContextConfig:
    """Limits aligned with Rust ``file_mention.rs`` defaults."""

    max_mentions: int = 8
    max_inline_bytes: int = 128 * 1024
    max_directory_entries: int = 80
    max_total_inline_bytes: int = 512 * 1024
    large_file_mode: Literal["truncate", "reference"] = "truncate"
    expansion_header: str = "Local context from @mentions:"


@dataclass(slots=True)
class UserTurnInput:
    raw_text: str


@dataclass(slots=True)
class ContextReference:
    kind: str
    source: str
    label: str
    target: str
    included: bool
    expanded: bool
    detail: str | None = None
    artifact_path: str | None = None
    bytes_inlined: int = 0


@dataclass(slots=True)
class ProcessedTurnInput:
    display_text: str
    model_text: str
    references: list[ContextReference] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
