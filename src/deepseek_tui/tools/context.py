from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deepseek_tui.execpolicy.policy import Policy


@dataclass(slots=True)
class ToolContext:
    working_directory: Path
    timeout_ms: int | None = None
    trust_mode: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    policy: Policy | None = None

    def resolve_path(self, path: str) -> Path:
        workspace = self.working_directory.expanduser().resolve()
        candidate = Path(path).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve()
        else:
            resolved = (workspace / candidate).resolve()
        if not self.trust_mode:
            try:
                resolved.relative_to(workspace)
            except ValueError as exc:
                raise ValueError(f"path escapes workspace: {path}") from exc
        return resolved
