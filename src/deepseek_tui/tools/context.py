from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deepseek_tui.execpolicy.policy import Policy
    from deepseek_tui.tools.subagent import SubAgentManager
    from deepseek_tui.tools.task_manager import TaskManager


@dataclass(slots=True)
class ToolContext:
    working_directory: Path
    timeout_ms: int | None = None
    trust_mode: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    policy: Policy | None = None
    task_manager: TaskManager | None = None
    subagent_manager: SubAgentManager | None = None

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
                # Path escapes workspace - extract filename and use it in workspace
                # This handles cases where LLM generates absolute paths like /home/user/file.py
                filename = resolved.name
                if filename:
                    resolved = (workspace / filename).resolve()
                    # Verify the new path is in workspace
                    try:
                        resolved.relative_to(workspace)
                    except ValueError:
                        raise ValueError(f"path escapes workspace: {path}") from exc
                else:
                    raise ValueError(f"path escapes workspace: {path}") from exc
        return resolved
