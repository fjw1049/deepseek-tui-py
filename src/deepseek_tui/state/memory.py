"""Small project memory store. No model calls, embeddings, or automatic extraction."""

from __future__ import annotations

import hashlib
import json
import subprocess
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from deepseek_tui.config.paths import user_memories_dir
from deepseek_tui.utils import write_json_atomic
from deepseek_tui.workspace.project_lease import FileLease


class MemoryEntry(BaseModel):
    id: str
    content: str = Field(max_length=2000)
    kind: Literal["preference", "constraint", "decision", "lesson"]
    applicability: str = Field(default="", max_length=500)
    source: dict[str, str]
    updated_source: dict[str, str]
    created_at: str
    updated_at: str
    revision: int = 1
    status: Literal["active", "candidate", "deleted"] = "active"
    fingerprint: str
    topic: str = Field(default="", max_length=100)
    branch: str = Field(default="", max_length=200)
    expires_at: datetime | None = None
    file_hashes: dict[str, str] = Field(default_factory=dict)

    @field_validator("expires_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("expires_at requires a timezone")
        return value


class MemoryState(BaseModel):
    version: Literal[1] = 1
    entries: list[MemoryEntry] = Field(default_factory=list)
    blocked_fingerprints: list[str] = Field(default_factory=list)


def project_identity(workspace: Path) -> str:
    """Share linked worktrees, but never merge independent clones by remote URL."""
    workspace = workspace.resolve()
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        root = str(Path(result.stdout.strip()).resolve())
    except (OSError, subprocess.SubprocessError):
        root = str(workspace)
    return hashlib.sha256(root.encode()).hexdigest()


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _fingerprint(content: str, applicability: str) -> str:
    return hashlib.sha256(
        (_normalize(content) + "\0" + _normalize(applicability)).encode()
    ).hexdigest()


class MemoryStore:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()
        self.project_id = project_identity(workspace)
        self.root = user_memories_dir()
        self.path = self.root / f"{self.project_id}.json"

    def _load(self) -> MemoryState:
        if self.root.is_symlink() or self.path.is_symlink():
            raise ValueError("Memory storage cannot be a symlink")
        try:
            return MemoryState.model_validate_json(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return MemoryState()

    def read(
        self,
        *,
        query: str = "",
        entry_id: str = "",
        limit: int = 5,
        status: str = "active",
        offset: int = 0,
    ) -> list[MemoryEntry]:
        entries = self.matching_entries(query=query, entry_id=entry_id, status=status)
        return entries[offset : offset + max(1, min(limit, 20))]

    def matching_entries(
        self, *, query: str = "", entry_id: str = "", status: str = "active"
    ) -> list[MemoryEntry]:
        """Literal filtering only. Semantic relevance belongs to the caller/model."""
        entries = [
            entry for entry in self._load().entries
            if entry.status == status or (status == "all" and entry.status != "deleted")
        ]
        if entry_id:
            return [entry for entry in entries if entry.id == entry_id]
        if query.strip():
            needle = _normalize(query)
            entries = [entry for entry in entries if needle in _normalize(
                entry.content + " " + entry.applicability + " " + entry.topic
            )]
        return sorted(entries, key=lambda entry: (entry.updated_at, entry.id), reverse=True)

    def stale_reason(self, entry: MemoryEntry, cache: dict | None = None) -> str | None:
        cache = {} if cache is None else cache
        if entry.expires_at and entry.expires_at <= datetime.now(timezone.utc):
            return "expired"
        if entry.branch:
            try:
                if "branch" not in cache:
                    cache["branch"] = subprocess.run(
                        ["git", "-C", str(self.workspace), "branch", "--show-current"],
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=3,
                    ).stdout.strip()
                branch = cache["branch"]
            except (OSError, subprocess.SubprocessError):
                cache["branch"] = None
                return "branch unavailable"
            if branch != entry.branch:
                return "different branch"
        for path, expected in entry.file_hashes.items():
            try:
                key = ("file", path)
                if key not in cache:
                    cache[key] = self.file_hash(path)
                if cache[key] != expected:
                    return f"file changed: {path}"
            except (OSError, ValueError):
                return f"file unavailable: {path}"
        if entry.status == "candidate" and entry.source.get("type") == "local_candidate":
            from deepseek_tui.state.memory_capture import source_is_live

            if not source_is_live(entry.source):
                return "source removed or rolled back"
        return None

    def file_hash(self, name: str) -> str:
        from deepseek_tui.tools.utils.sensitive import is_sensitive_path

        path = (self.workspace / name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(self.workspace):
            raise ValueError("Memory file conditions must stay inside the workspace")
        if is_sensitive_path(path):
            raise ValueError("Cannot fingerprint a sensitive file")
        with path.open("rb") as stream:
            content = stream.read(1_000_001)
        if len(content) > 1_000_000:
            raise ValueError("Memory file condition exceeds 1 MB")
        return hashlib.sha256(content).hexdigest()

    def recall(self, query: str) -> list[MemoryEntry]:
        needle = _normalize(query)
        return [entry for entry in self.eligible() if needle in _normalize(
            entry.content + " " + entry.applicability + " " + entry.topic
        )]

    def eligible(self) -> list[MemoryEntry]:
        cache = {}
        return [
            entry
            for entry in self.matching_entries()
            if not self.stale_reason(entry, cache)
        ]

    def write(
        self,
        *,
        action: str,
        source: dict[str, str],
        content: str = "",
        kind: str = "lesson",
        applicability: str = "",
        entry_id: str = "",
        revision: int | None = None,
        topic: str = "",
        branch: str = "",
        expires_at: str | None = None,
        files: list[str] | None = None,
    ) -> MemoryEntry:
        if action not in {"remember", "update", "forget", "propose", "accept"}:
            raise ValueError("Unknown memory action")
        if action not in {"forget", "accept"} and not content.strip():
            raise ValueError("Memory content must not be empty")
        self._load()  # Reject redirected storage before creating the lock.
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self.root / f"{self.project_id}.lock"
        if lock_path.is_symlink():
            raise ValueError("Memory lock cannot be a symlink")
        lease = FileLease(lock_path)
        lease.acquire_blocking()
        try:
            state = self._load()
            now = datetime.now(timezone.utc).isoformat()
            fingerprint = _fingerprint(content, applicability)
            entry = next((item for item in state.entries if item.id == entry_id), None)
            if action in {"update", "forget", "accept"}:
                if entry is None or entry.status == "deleted":
                    raise ValueError("Active memory not found in this project")
                if revision != entry.revision:
                    raise ValueError(
                        "Memory changed; read it again and supply its current revision"
                    )
            if action == "accept":
                if entry.status != "candidate" or self.stale_reason(entry):
                    raise ValueError("Candidate is no longer eligible; inspect its source")
                self._check_topic(state, entry.topic, entry.id)
                entry.status = "active"
                entry.revision += 1
                entry.updated_at = now
                entry.updated_source = source
                write_json_atomic(self.path, state.model_dump(mode="json"))
                return entry
            if action != "forget":
                condition_hashes = (
                    entry.file_hashes if action == "update" and files is None
                    else {name: self.file_hash(name) for name in files or []}
                )
                expiry = (datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                          if isinstance(expires_at, str) else expires_at)
                if action == "propose" and fingerprint in state.blocked_fingerprints:
                    raise ValueError("This memory was forgotten or replaced")
                duplicate = next(
                    (
                        item
                        for item in state.entries
                        if item.fingerprint == fingerprint and item is not entry
                        and (item.kind, item.topic, item.branch, item.expires_at, item.file_hashes)
                        == (kind, topic, branch, expiry, condition_hashes)
                    ),
                    None,
                )
                if duplicate is not None:
                    if duplicate.status == "deleted":
                        if action == "propose":
                            raise ValueError("This memory was forgotten")
                        state.entries.remove(duplicate)
                    elif action == "remember" and duplicate.status == "candidate":
                        self._check_topic(state, duplicate.topic, duplicate.id)
                        duplicate.status = "active"
                        duplicate.revision += 1
                        duplicate.source = source
                        duplicate.updated_source = source
                        duplicate.updated_at = now
                        write_json_atomic(self.path, state.model_dump(mode="json"))
                        return duplicate
                    elif action in {"remember", "propose"}:
                        return duplicate
                    else:
                        raise ValueError("An identical memory already exists")
            if action in {"remember", "update"}:
                self._check_topic(state, topic, entry_id)
            if action in {"remember", "propose"}:
                if sum(e.status != "deleted" for e in state.entries) >= 1000:
                    raise ValueError("Project memory capacity reached (1000 live entries)")
                entry = MemoryEntry(
                    id=uuid.uuid4().hex,
                    content=content.strip(),
                    kind=kind,
                    applicability=applicability.strip(),
                    source=source,
                    updated_source=source,
                    created_at=now,
                    updated_at=now,
                    fingerprint=fingerprint,
                    status="candidate" if action == "propose" else "active",
                    topic=topic,
                    branch=branch,
                    expires_at=expires_at,
                    file_hashes=condition_hashes,
                )
                state.entries.append(entry)
            elif action == "update":
                replacement = MemoryEntry(
                    **{
                        **entry.model_dump(),
                        "content": content.strip(),
                        "kind": kind,
                        "applicability": applicability.strip(),
                        "fingerprint": fingerprint,
                        "revision": entry.revision + 1,
                        "updated_at": now,
                        "updated_source": source,
                        "topic": topic,
                        "branch": branch,
                        "expires_at": expires_at,
                        "file_hashes": condition_hashes,
                    }
                )
                state.entries[state.entries.index(entry)] = replacement
                if entry.fingerprint != fingerprint:
                    state.blocked_fingerprints.append(entry.fingerprint)
                entry = replacement
            else:
                entry.status = "deleted"
                entry.content = ""
                entry.applicability = ""
                entry.source = {}
                entry.updated_source = {}
                entry.updated_at = now
                entry.revision += 1
                entry.topic = ""
                entry.branch = ""
                entry.expires_at = None
                entry.file_hashes = {}
            state.blocked_fingerprints = state.blocked_fingerprints[-1000:]
            deleted = sorted(
                (e for e in state.entries if e.status == "deleted"), key=lambda e: e.updated_at
            )
            retired = {e.id for e in deleted[:-1000]}
            state.entries = [e for e in state.entries if e.id not in retired]
            write_json_atomic(self.path, state.model_dump(mode="json"))
            return entry
        finally:
            lease.release()

    def _check_topic(self, state: MemoryState, topic: str, exclude_id: str) -> None:
        # Branch/file-stale entries still conflict: their condition can become true
        # again. Update the existing entry, or use distinct topics per branch.
        if not topic:
            return
        now = datetime.now(timezone.utc)
        for other in state.entries:
            if (
                other.id != exclude_id
                and other.status == "active"
                and _normalize(other.topic) == _normalize(topic)
                and not (other.expires_at and other.expires_at <= now)
            ):
                raise ValueError(f"Topic already exists: id={other.id}; read it and use update")


def render_memories(
    entries: list[MemoryEntry],
    *,
    max_chars: int = 6000,
    store: MemoryStore | None = None,
) -> str:
    """Return whole entries only; never truncate JSON or hide a provenance field."""
    output = []
    size = 0
    for entry in entries:
        data = entry.model_dump(mode="json", exclude={"fingerprint"})
        if store is not None:
            data["stale_reason"] = store.stale_reason(entry)
        row = json.dumps(data, ensure_ascii=False)
        if size + len(row) + 1 > max_chars:
            break
        output.append(row)
        size += len(row) + 1
    return "\n".join(output) or "No matching project memories."
