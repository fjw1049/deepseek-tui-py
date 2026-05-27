from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deepseek_tui.execpolicy.policy import Policy
    from deepseek_tui.execpolicy.sandbox import ExecutionSandboxPolicy
    from deepseek_tui.network.policy import NetworkPolicyDecider
    from deepseek_tui.tools.subagent import SubAgentManager
    from deepseek_tui.tools.task_manager import TaskManager


@dataclass(slots=True)
class ToolContext:
    working_directory: Path
    timeout_ms: int | None = None
    trust_mode: bool = False
    active_task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    policy: Policy | None = None
    task_manager: TaskManager | None = None
    subagent_manager: SubAgentManager | None = None
    network_policy: NetworkPolicyDecider | None = None
    execution_sandbox_policy: ExecutionSandboxPolicy | None = None
    elevated_sandbox_policy: ExecutionSandboxPolicy | None = None

    def resolve_path(self, path: str) -> Path:
        """Resolve ``path`` against the workspace, refusing escapes.

        Mirrors Rust ``PathEscape`` (tools/src/lib.rs:67-75): when the
        resolved path falls outside ``working_directory``, raise
        ``ValueError`` instead of silently rewriting it. The negative
        signal lets the LLM self-correct on the next turn — without it,
        absolute-path hallucinations (``/home/user/foo.py``) keep
        succeeding and the model never learns.

        ``trust_mode`` bypasses the check (used for system-initiated
        operations that must touch e.g. ``~/.deepseek``).
        """
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
                raise ValueError(
                    f"path escapes workspace: {path!r} "
                    f"(workspace: {workspace}). Use a relative path."
                ) from exc
        return resolved
