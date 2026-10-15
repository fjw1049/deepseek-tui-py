"""User-granted file access outside the default tool boundary.

One grant store per session answers "did the user authorize this path?" for
every entry point: ``@`` mentions and attachments add grants, approval
prompts add grants, and ``ToolContext.resolve_path`` consults them.

Rules:

* A file grant covers exactly that file; a directory grant covers its tree.
* A write grant also covers reads; a read grant never covers writes.
* Sensitive files (credentials, ``.git/hooks`` for writes) are covered only
  by a grant naming that exact file — never by a directory grant.
* Grants carry the turn that created them so a rewind can drop them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepseek_tui.tools.utils.sensitive import is_sensitive_path, is_sensitive_write_path


def is_sensitive(path: Path, *, write: bool) -> bool:
    return is_sensitive_write_path(path) if write else is_sensitive_path(path)


@dataclass(frozen=True, slots=True)
class PathGrant:
    path: Path
    recursive: bool = False
    write: bool = False
    turn_id: str | None = None

    def covers(self, target: Path, *, write: bool) -> bool:
        if write and not self.write:
            return False
        if target == self.path:
            return True
        if not self.recursive or is_sensitive(target, write=write):
            return False
        return target.is_relative_to(self.path)

    def to_json(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "recursive": self.recursive,
            "write": self.write,
            "turn_id": self.turn_id,
        }

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> PathGrant:
        return cls(
            path=Path(str(raw["path"])),
            recursive=bool(raw.get("recursive", False)),
            write=bool(raw.get("write", False)),
            turn_id=raw.get("turn_id") or None,
        )


@dataclass(slots=True)
class PathGrants:
    """Session grant store, shared by the engine and its sub-agents."""

    grants: list[PathGrant] = field(default_factory=list)
    # Stamped onto new grants; the engine sets it at turn start.
    turn_id: str | None = None
    # Persistence hook (server threads); called after every change.
    on_change: Callable[[list[dict[str, Any]]], None] | None = None

    def allows(self, path: Path, *, write: bool) -> bool:
        return any(grant.covers(path, write=write) for grant in self.grants)

    def add(self, path: Path, *, recursive: bool = False, write: bool = False) -> PathGrant:
        grant = PathGrant(path=path, recursive=recursive, write=write, turn_id=self.turn_id)
        if grant not in self.grants:
            self.grants.append(grant)
            self._changed()
        return grant

    def add_mentions(self, paths: Iterable[Path]) -> None:
        """Grant read access to what the user explicitly referenced."""
        for path in paths:
            self.add(path, recursive=path.is_dir())

    def remove(self, grant: PathGrant) -> None:
        if grant in self.grants:
            self.grants.remove(grant)
            self._changed()

    def drop_turns(self, turn_ids: set[str]) -> None:
        kept = [g for g in self.grants if g.turn_id is None or g.turn_id not in turn_ids]
        if len(kept) != len(self.grants):
            self.grants = kept
            self._changed()

    def dump(self) -> list[dict[str, Any]]:
        return [grant.to_json() for grant in self.grants]

    def load(self, raw: Iterable[dict[str, Any]]) -> None:
        self.grants = []
        for item in raw:
            try:
                self.grants.append(PathGrant.from_json(item))
            except (KeyError, TypeError, ValueError):
                continue

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change(self.dump())


@dataclass(frozen=True, slots=True)
class PathAccess:
    """Outcome of checking one path: allowed, or why the user must approve it."""

    path: Path
    write: bool
    allowed: bool
    sensitive: bool = False
    outside: bool = False

    def denial_message(self, raw: str, workspace: Path) -> str:
        verb = "write" if self.write else "read"
        if self.sensitive:
            return (
                f"refusing to {verb} sensitive file: {self.path} "
                "(matched the credential-file blocklist). Only the user can "
                "authorize it: by @-mentioning it or approving the access prompt."
            )
        return (
            f"path escapes workspace: {raw!r} (workspace: {workspace}). "
            "Use a relative path. The user has not authorized this path; they "
            "can @-mention it or approve the access prompt. Do not work around "
            "this with shell."
        )


def os_denied_message(exc: PermissionError) -> str:
    target = exc.filename or "the requested path"
    return (
        f"operating system denied access to {target}: {exc.strerror or exc}. "
        "This is not an app permission: on macOS, grant this app access in "
        "System Settings > Privacy & Security (Files and Folders or Full Disk Access)."
    )
