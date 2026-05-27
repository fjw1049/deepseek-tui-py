"""OS execution sandbox — policy, manager, and macOS Seatbelt integration.

Port of ``docs/DeepSeek-TUI-main/crates/tui/src/sandbox/{policy,mod}.rs``.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WritableRoot:
    root: Path
    read_only_subpaths: tuple[Path, ...] = ()

    def is_path_writable(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root.resolve())
        except ValueError:
            return False
        for subpath in self.read_only_subpaths:
            try:
                path.resolve().relative_to(subpath.resolve())
                return False
            except ValueError:
                continue
        return True


@dataclass(frozen=True, slots=True)
class ExecutionSandboxPolicy:
    """Runtime shell sandbox policy (distinct from config ``sandbox_mode``)."""

    kind: str
    writable_roots: tuple[Path, ...] = ()
    network_access: bool = False
    exclude_tmpdir: bool = False
    exclude_slash_tmp: bool = False

    @classmethod
    def read_only(cls) -> ExecutionSandboxPolicy:
        return cls(kind="read-only")

    @classmethod
    def danger_full_access(cls) -> ExecutionSandboxPolicy:
        return cls(kind="danger-full-access")

    @classmethod
    def external_sandbox(cls, *, network_access: bool = False) -> ExecutionSandboxPolicy:
        return cls(kind="external-sandbox", network_access=network_access)

    @classmethod
    def workspace_write(
        cls,
        *,
        writable_roots: tuple[Path, ...] = (),
        network_access: bool = False,
        exclude_tmpdir: bool = False,
        exclude_slash_tmp: bool = False,
    ) -> ExecutionSandboxPolicy:
        return cls(
            kind="workspace-write",
            writable_roots=writable_roots,
            network_access=network_access,
            exclude_tmpdir=exclude_tmpdir,
            exclude_slash_tmp=exclude_slash_tmp,
        )

    @classmethod
    def default(cls) -> ExecutionSandboxPolicy:
        return cls.workspace_write()

    @staticmethod
    def has_full_disk_read_access() -> bool:
        return True

    def has_full_disk_write_access(self) -> bool:
        return self.kind in ("danger-full-access", "external-sandbox")

    def has_network_access(self) -> bool:
        if self.kind == "danger-full-access":
            return True
        if self.kind == "read-only":
            return False
        return self.network_access

    def should_sandbox(self) -> bool:
        return self.kind not in ("danger-full-access", "external-sandbox")

    def get_writable_roots(self, cwd: Path) -> list[WritableRoot]:
        if self.kind != "workspace-write":
            return []

        roots: list[Path] = list(self.writable_roots)
        try:
            roots.append(cwd.resolve())
        except OSError:
            roots.append(cwd)

        if not self.exclude_slash_tmp:
            try:
                roots.append(Path("/tmp").resolve())
            except OSError:
                pass

        if not self.exclude_tmpdir:
            tmpdir = __import__("os").environ.get("TMPDIR")
            if tmpdir:
                try:
                    roots.append(Path(tmpdir).resolve())
                except OSError:
                    pass

        seen: set[str] = set()
        writable: list[WritableRoot] = []
        for root in roots:
            try:
                key = str(root.resolve())
                root = root.resolve()
            except OSError:
                key = str(root)
            if key in seen:
                continue
            seen.add(key)
            read_only: list[Path] = []
            deepseek_dir = root / ".deepseek"
            if deepseek_dir.is_dir():
                read_only.append(deepseek_dir)
            writable.append(
                WritableRoot(root=root, read_only_subpaths=tuple(read_only))
            )
        return _propagate_read_only_subpaths(writable)


def _propagate_read_only_subpaths(roots: list[WritableRoot]) -> list[WritableRoot]:
    """Extend ancestor writable roots with nested .deepseek read-only paths."""
    updated: list[WritableRoot] = []
    for wr in roots:
        try:
            wr_resolved = wr.root.resolve()
        except OSError:
            wr_resolved = wr.root
        read_only = list(wr.read_only_subpaths)
        for other in roots:
            try:
                other_resolved = other.root.resolve()
            except OSError:
                other_resolved = other.root
            if other_resolved == wr_resolved:
                continue
            try:
                other_resolved.relative_to(wr_resolved)
            except ValueError:
                continue
            for subpath in other.read_only_subpaths:
                if subpath not in read_only:
                    read_only.append(subpath)
            nested_deepseek = other_resolved / ".deepseek"
            if nested_deepseek.is_dir() and nested_deepseek not in read_only:
                read_only.append(nested_deepseek)
        updated.append(
            WritableRoot(root=wr.root, read_only_subpaths=tuple(read_only))
        )
    return updated


class SandboxType(str, Enum):
    NONE = "none"
    MACOS_SEATBELT = "macos-seatbelt"


@dataclass(slots=True)
class CommandSpec:
    program: str
    args: list[str]
    cwd: Path
    env: dict[str, str] = field(default_factory=dict)
    timeout_ms: int = 120_000
    sandbox_policy: ExecutionSandboxPolicy = field(
        default_factory=ExecutionSandboxPolicy.default
    )
    justification: str | None = None

    @classmethod
    def shell(cls, command: str, cwd: Path, timeout_ms: int) -> CommandSpec:
        return cls(
            program="sh",
            args=["-c", command],
            cwd=cwd,
            timeout_ms=timeout_ms,
        )

    def with_policy(self, policy: ExecutionSandboxPolicy) -> CommandSpec:
        return CommandSpec(
            program=self.program,
            args=list(self.args),
            cwd=self.cwd,
            env=dict(self.env),
            timeout_ms=self.timeout_ms,
            sandbox_policy=policy,
            justification=self.justification,
        )

    def with_env(self, env: dict[str, str] | None) -> CommandSpec:
        merged = dict(self.env)
        if env:
            merged.update(env)
        return CommandSpec(
            program=self.program,
            args=list(self.args),
            cwd=self.cwd,
            env=merged,
            timeout_ms=self.timeout_ms,
            sandbox_policy=self.sandbox_policy,
            justification=self.justification,
        )

    def display_command(self) -> str:
        if self.program == "sh" and len(self.args) == 2 and self.args[0] == "-c":
            return self.args[1]
        return " ".join([self.program, *self.args])


@dataclass(slots=True)
class ExecEnv:
    command: list[str]
    cwd: Path
    env: dict[str, str]
    timeout_ms: int
    sandbox_type: SandboxType
    policy: ExecutionSandboxPolicy

    def program(self) -> str:
        return self.command[0] if self.command else "sh"

    def args(self) -> list[str]:
        return self.command[1:] if len(self.command) > 1 else []

    def is_sandboxed(self) -> bool:
        return self.sandbox_type != SandboxType.NONE


def get_platform_sandbox() -> SandboxType | None:
    if sys.platform != "darwin":
        return None
    from deepseek_tui.execpolicy import seatbelt

    if seatbelt.is_available():
        return SandboxType.MACOS_SEATBELT
    return None


def is_sandbox_available() -> bool:
    return get_platform_sandbox() is not None


def sandbox_policy_for_mode(mode: str, workspace: Path) -> ExecutionSandboxPolicy:
    normalized = (mode or "agent").strip().lower()
    if normalized == "plan":
        return ExecutionSandboxPolicy.read_only()
    if normalized in ("yolo", "trust"):
        return ExecutionSandboxPolicy.danger_full_access()
    return ExecutionSandboxPolicy.workspace_write(
        writable_roots=(workspace.resolve(),),
        network_access=True,
    )


def suggest_elevation_policy(
    current: ExecutionSandboxPolicy,
    denial_message: str,
    *,
    workspace: Path,
) -> ExecutionSandboxPolicy | None:
    """One-step sandbox relaxation after a Seatbelt denial (L3)."""
    if not current.should_sandbox():
        return None
    msg = (denial_message or "").lower()
    ws = workspace.resolve()
    roots = current.writable_roots or (ws,)
    if "network" in msg and not current.has_network_access():
        return ExecutionSandboxPolicy.workspace_write(
            writable_roots=roots,
            network_access=True,
            exclude_tmpdir=current.exclude_tmpdir,
            exclude_slash_tmp=current.exclude_slash_tmp,
        )
    if any(token in msg for token in ("file-write", "write access", "protected location")):
        if current.kind == "read-only":
            return sandbox_policy_for_mode("agent", ws)
        return ExecutionSandboxPolicy.workspace_write(
            writable_roots=roots,
            network_access=True,
            exclude_tmpdir=False,
            exclude_slash_tmp=False,
        )
    if current.kind != "danger-full-access":
        return ExecutionSandboxPolicy.danger_full_access()
    return None


def elevation_kind_label(policy: ExecutionSandboxPolicy) -> str:
    if policy.kind == "danger-full-access":
        return "full_access"
    if policy.has_network_access():
        return "network"
    return "write"


def sync_execution_sandbox_policy(
    context: Any,
    mode: str,
    workspace: Path | None = None,
) -> None:
    ws = workspace or context.working_directory
    context.execution_sandbox_policy = sandbox_policy_for_mode(mode, ws)


class SandboxManager:
    def __init__(self) -> None:
        self._sandbox_available: bool | None = None

    def is_available(self) -> bool:
        if self._sandbox_available is None:
            self._sandbox_available = is_sandbox_available()
        return self._sandbox_available

    def select_sandbox(self, policy: ExecutionSandboxPolicy) -> SandboxType:
        if not policy.should_sandbox():
            return SandboxType.NONE
        return get_platform_sandbox() or SandboxType.NONE

    def prepare(self, spec: CommandSpec) -> ExecEnv:
        sandbox_type = self.select_sandbox(spec.sandbox_policy)
        if sandbox_type == SandboxType.NONE:
            if spec.sandbox_policy.should_sandbox() and sys.platform == "darwin":
                logger.warning(
                    "sandbox policy %s requested but seatbelt unavailable; running unsandboxed",
                    spec.sandbox_policy.kind,
                )
            return self._prepare_unsandboxed(spec)
        if sandbox_type == SandboxType.MACOS_SEATBELT:
            return self._prepare_seatbelt(spec)
        return self._prepare_unsandboxed(spec)

    @staticmethod
    def _prepare_unsandboxed(spec: CommandSpec) -> ExecEnv:
        command = [spec.program, *spec.args]
        return ExecEnv(
            command=command,
            cwd=spec.cwd,
            env=dict(spec.env),
            timeout_ms=spec.timeout_ms,
            sandbox_type=SandboxType.NONE,
            policy=spec.sandbox_policy,
        )

    @staticmethod
    def _prepare_seatbelt(spec: CommandSpec) -> ExecEnv:
        from deepseek_tui.execpolicy import seatbelt

        original_command = [spec.program, *spec.args]
        seatbelt_args = seatbelt.create_seatbelt_args(
            original_command,
            spec.sandbox_policy,
            spec.cwd,
        )
        command = [seatbelt.SANDBOX_EXEC_PATH, *seatbelt_args]
        env = dict(spec.env)
        env["DEEPSEEK_SANDBOX"] = "seatbelt"
        return ExecEnv(
            command=command,
            cwd=spec.cwd,
            env=env,
            timeout_ms=spec.timeout_ms,
            sandbox_type=SandboxType.MACOS_SEATBELT,
            policy=spec.sandbox_policy,
        )

    @staticmethod
    def was_denied(sandbox_type: SandboxType, exit_code: int, stderr: str) -> bool:
        if sandbox_type == SandboxType.NONE:
            return False
        if sandbox_type == SandboxType.MACOS_SEATBELT:
            from deepseek_tui.execpolicy import seatbelt

            return seatbelt.detect_denial(exit_code, stderr)
        return False

    @staticmethod
    def denial_message(sandbox_type: SandboxType, stderr: str) -> str:
        if sandbox_type == SandboxType.NONE:
            return "Command failed (no sandbox)"
        if sandbox_type == SandboxType.MACOS_SEATBELT:
            if "file-write" in stderr:
                return (
                    "Sandbox blocked write access. The command tried to write "
                    "to a protected location."
                )
            if "network" in stderr:
                return (
                    "Sandbox blocked network access. Enable network_access "
                    "in sandbox policy if needed."
                )
            first_line = stderr.splitlines()[0] if stderr else "unknown"
            return f"Sandbox blocked operation: {first_line}"
        return "Sandbox blocked operation"


SANDBOX_MANAGER = SandboxManager()


def apply_sandbox_metadata(
    metadata: dict[str, Any],
    *,
    exec_env: ExecEnv,
    exit_code: int | None,
    stderr: str,
) -> None:
    metadata["sandboxed"] = exec_env.is_sandboxed()
    metadata["sandbox_type"] = exec_env.sandbox_type.value
    if exec_env.is_sandboxed() and exit_code is not None:
        denied = SandboxManager.was_denied(
            exec_env.sandbox_type,
            exit_code,
            stderr,
        )
        metadata["sandbox_denied"] = denied
        if denied:
            metadata["denial_message"] = SandboxManager.denial_message(
                exec_env.sandbox_type,
                stderr,
            )
