"""Read-only Codex / Claude Code history adapters and native session import.

No source harness is started. Imported tools are evidence, never executable calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from deepseek_tui.config.paths import user_deepseek_dir
from deepseek_tui.server.threads.models import (
    RuntimeTurnStatus,
    ThreadRecord,
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
)
from deepseek_tui.server.threads.store import RuntimeThreadStore

Source = Literal["codex", "claude"]
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024 * 1024


class SkippedSession(ValueError):
    """An empty or auxiliary log, not an import failure."""


@dataclass
class Entry:
    kind: str
    text: str
    timestamp: datetime
    name: str = ""
    failed: bool = False


@dataclass
class History:
    source: Source
    path: Path
    session_id: str = ""
    workspace: str = ""
    title: str = ""
    model: str = ""
    archived: bool = False
    entries: list[Entry] = field(default_factory=list)
    warnings: set[str] = field(default_factory=set)

    @property
    def thread_id(self) -> str:
        digest = hashlib.sha256(f"{self.source}:{self.session_id}".encode()).hexdigest()[:32]
        return f"thr_import_{digest}"


def source_root(source: Source, root: str | None = None) -> Path:
    if root:
        return Path(root).expanduser().resolve()
    env, name = ("CODEX_HOME", ".codex") if source == "codex" else ("CLAUDE_CONFIG_DIR", ".claude")
    return Path(os.environ.get(env) or Path.home() / name).expanduser().resolve()


def timestamp(value: Any, fallback: datetime) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=result.tzinfo or timezone.utc)
    except (TypeError, ValueError):
        return fallback


def records(history: History) -> Iterator[dict]:
    # Freeze the byte boundary so an active source cannot extend this import forever.
    with history.path.open("rb") as stream:
        remaining = os.fstat(stream.fileno()).st_size
        if remaining > MAX_FILE_BYTES:
            raise ValueError("Session exceeds the 256 MB import limit")
        while remaining:
            line = stream.readline(min(remaining, MAX_LINE_BYTES + 1))
            if not line:
                break
            remaining -= len(line)
            if len(line) > MAX_LINE_BYTES:
                raise ValueError("Session contains a record larger than 16 MB")
            try:
                raw = json.loads(line)
            except (ValueError, UnicodeDecodeError) as exc:
                if remaining == 0 and not line.endswith(b"\n"):
                    history.warnings.add("unfinished_tail")
                    break
                raise ValueError("Session contains an invalid JSON record") from exc
            if isinstance(raw, dict):
                yield raw


def text_blocks(content: Any, warnings: set[str]) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind in {"text", "Text", "summary_text", "input_text", "output_text"}:
            parts.append(str(block.get("text") or ""))
        elif kind in {
            "image",
            "input_image",
            "image_url",
            "local_image",
            "document",
            "input_audio",
        }:
            warnings.add("attachments_not_copied")
            parts.append(f"[{kind}: attachment not copied from the source session]")
    return "\n".join(parts)


def encoded(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def read_codex(history: History) -> None:
    fallback = datetime.fromtimestamp(history.path.stat().st_mtime, timezone.utc)
    responses: list[Entry] = []
    presentation: list[Entry] = []
    tools: dict[str, Entry] = {}
    has_presentation_user = False
    for row in records(history):
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        when = timestamp(row.get("timestamp"), fallback)
        kind = row.get("type")
        subtype = payload.get("type")
        if kind == "session_meta":
            if isinstance(payload.get("source"), dict) and "subagent" in payload["source"]:
                raise SkippedSession("Subagent session")
            history.session_id = str(payload.get("id") or payload.get("session_id") or "")
            history.workspace = str(payload.get("cwd") or "")
        elif kind == "turn_context":
            history.model = str(payload.get("model") or history.model)
        elif kind == "response_item":
            if subtype == "message" and payload.get("role") in {"user", "assistant"}:
                role = "user_message" if payload["role"] == "user" else "agent_message"
                text = text_blocks(payload.get("content"), history.warnings)
                if text:
                    responses.append(Entry(role, text, when))
            elif subtype in {"function_call", "custom_tool_call"}:
                name = str(payload.get("name") or "tool")
                entry = Entry(
                    "tool_call",
                    encoded(payload.get("arguments", payload.get("input", ""))),
                    when,
                    name,
                )
                responses.append(entry)
                tools[str(payload.get("call_id"))] = entry
            elif subtype in {"function_call_output", "custom_tool_call_output"}:
                entry = tools.pop(str(payload.get("call_id")), None)
                if entry:
                    entry.text += "\n\nResult:\n" + encoded(payload.get("output", ""))
            elif subtype == "reasoning":
                text = text_blocks(payload.get("summary"), history.warnings)
                if text:
                    responses.append(Entry("agent_reasoning", text, when))
        elif kind == "event_msg" and subtype == "item_completed":
            item = payload.get("item", {})
            if not isinstance(item, dict):
                history.warnings.add("unsupported_records")
                continue
            itype = item.get("type")
            if itype in {"UserMessage", "AgentMessage"}:
                text = text_blocks(item.get("content"), history.warnings)
                if text:
                    presentation.append(
                        Entry(
                            "user_message" if itype == "UserMessage" else "agent_message",
                            text,
                            when,
                        )
                    )
                    has_presentation_user |= itype == "UserMessage"
            elif itype == "Reasoning":
                value = item.get("summary_text") or item.get("raw_content") or []
                text = "\n".join(value) if isinstance(value, list) else str(value)
                if text:
                    presentation.append(Entry("agent_reasoning", text, when))
            elif itype in {
                "CommandExecution",
                "FileChange",
                "McpToolCall",
                "WebSearch",
                "ImageView",
            }:
                detail = {k: v for k, v in item.items() if k not in {"id", "type", "process_id"}}
                presentation.append(
                    Entry(
                        "tool_call",
                        encoded(detail),
                        when,
                        str(itype),
                        item.get("status") == "failed",
                    )
                )
            elif itype not in {"ContextCompaction"}:
                history.warnings.add("unsupported_records")
        elif kind == "compacted":
            history.warnings.add("compacted_history")
        elif kind == "event_msg" and subtype == "turn_aborted":
            history.warnings.add("interrupted_source")
    # New Codex logs have a complete UI projection; older logs use response items.
    # Never concatenate both copies of the same transcript.
    history.entries = presentation if has_presentation_user else responses
    if tools:
        history.warnings.add("unfinished_tools")


def read_claude(history: History) -> None:
    fallback = datetime.fromtimestamp(history.path.stat().st_mtime, timezone.utc)
    nodes: dict[str, dict] = {}
    leaf = ""
    last_message = ""
    leaf_at = last_message_at = -1
    for position, row in enumerate(records(history)):
        if row.get("isSidechain"):
            continue
        history.session_id = str(row.get("sessionId") or history.session_id)
        history.workspace = str(row.get("cwd") or history.workspace)
        if row.get("type") == "ai-title":
            history.title = str(row.get("aiTitle") or history.title)
        if row.get("type") == "last-prompt":
            leaf = str(row.get("leafUuid") or "")
            leaf_at = position
        key = row.get("uuid")
        if key:
            nodes[str(key)] = row
            if row.get("type") in {"user", "assistant"}:
                last_message = str(key)
                last_message_at = position
    # Traverse the selected leaf's ancestry, retaining all assistant block UUIDs.
    # A final last-prompt can select an older branch. If newer output follows the
    # pointer, that output is the current continuation instead.
    current = leaf if leaf in nodes and leaf_at > last_message_at else last_message
    chain: list[dict] = []
    seen: set[str] = set()
    while current and current in nodes and current not in seen:
        seen.add(current)
        row = nodes[current]
        chain.append(row)
        current = str(row.get("parentUuid") or row.get("logicalParentUuid") or "")
    if current and current not in nodes:
        history.warnings.add("partial_branch")
    if not chain:
        return
    if sum(r.get("type") in {"user", "assistant"} for r in nodes.values()) > sum(
        r.get("type") in {"user", "assistant"} for r in chain
    ):
        history.warnings.add("other_branches_skipped")
    tools: dict[str, Entry] = {}
    for row in reversed(chain):
        message = row.get("message")
        if not isinstance(message, dict) or row.get("isMeta"):
            continue
        when = timestamp(row.get("timestamp"), fallback)
        history.model = str(message.get("model") or history.model)
        content = message.get("content")
        if row.get("isCompactSummary"):
            history.warnings.add("compacted_history")
        text = text_blocks(content, history.warnings)
        if text:
            kind = "user_message" if message.get("role") == "user" else "agent_message"
            history.entries.append(Entry(kind, text, when))
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "thinking" and block.get("thinking"):
                history.entries.append(Entry("agent_reasoning", str(block["thinking"]), when))
            elif block.get("type") == "tool_use":
                entry = Entry(
                    "tool_call",
                    encoded(block.get("input", {})),
                    when,
                    str(block.get("name") or "tool"),
                )
                history.entries.append(entry)
                tools[str(block.get("id"))] = entry
            elif block.get("type") == "tool_result":
                entry = tools.pop(str(block.get("tool_use_id")), None)
                result = text_blocks(block.get("content"), history.warnings)
                if entry:
                    entry.text += "\n\nResult:\n" + result
                    entry.failed = bool(block.get("is_error"))
                else:
                    history.warnings.add("unpaired_tool_results")
    if tools:
        history.warnings.add("unfinished_tools")


def read_history(source: Source, path: Path) -> History:
    history = History(source, path, archived="archived_sessions" in path.parts)
    (read_codex if source == "codex" else read_claude)(history)
    if not history.session_id:
        raise ValueError("Not a recognized session: missing source session ID")
    if not any(e.kind == "user_message" for e in history.entries):
        raise SkippedSession("Session has no importable user messages")
    if not history.title:
        history.title = next(e.text for e in history.entries if e.kind == "user_message")[:120]
    return history


def session_paths(source: Source, root: Path) -> Iterator[Path]:
    roots = [root]
    if source == "codex" and (root / "sessions").is_dir():
        roots = [root / "sessions", root / "archived_sessions"]
    elif source == "claude" and (root / "projects").is_dir():
        roots = [root / "projects"]
    for folder in roots:
        for path in sorted(folder.rglob("*.jsonl")):
            if path.name.startswith("agent-") or "subagents" in path.parts:
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                continue
            yield path


def codex_catalog(root: Path) -> dict[str, dict]:
    """Optional title/archive enrichment; transcripts remain the source of messages."""
    catalog: dict[str, dict] = {}
    home = root.parent if root.name in {"sessions", "archived_sessions"} else root
    for database in sorted(home.glob("state_*.sqlite"), reverse=True):
        try:
            with closing(
                sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
            ) as conn:
                for sid, title, archived in conn.execute("SELECT id, title, archived FROM threads"):
                    catalog.setdefault(sid, {"title": title, "archived": bool(archived)})
            break
        except sqlite3.Error:
            continue
    index = home / "session_index.jsonl"
    if index.is_file():
        try:
            with index.open() as stream:
                for line in stream:
                    row = json.loads(line)
                    if row.get("id") and row.get("thread_name"):
                        catalog.setdefault(row["id"], {})["title"] = row["thread_name"]
        except (OSError, ValueError):
            pass
    return catalog


def scan_sessions(store: RuntimeThreadStore, source: Source, root: str | None) -> dict:
    folder = source_root(source, root)
    sessions, errors = [], []
    catalog = codex_catalog(folder) if source == "codex" else {}
    skipped = 0
    existing = {t.id: t for t in store.list_threads()}
    seen = set()
    for path in session_paths(source, folder):
        try:
            history = read_history(source, path)
            meta = catalog.get(history.session_id, {})
            history.title = str(meta.get("title") or history.title)
            history.archived = bool(meta.get("archived", history.archived))
            if history.thread_id in seen:
                continue
            seen.add(history.thread_id)
            imported = existing.get(history.thread_id)
            sessions.append(
                {
                    "id": history.session_id,
                    "source": source,
                    "path": str(path),
                    "title": history.title,
                    "workspace": history.workspace,
                    "workspace_available": bool(
                        history.workspace and Path(history.workspace).is_dir()
                    ),
                    "archived": history.archived,
                    "model": history.model,
                    "message_count": sum(
                        e.kind in {"user_message", "agent_message"} for e in history.entries
                    ),
                    "updated_at": history.entries[-1].timestamp.isoformat(),
                    "warnings": sorted(history.warnings),
                    "imported_thread_id": imported.id if imported else None,
                    "history_only": bool(
                        imported
                        and (imported.import_history_only or not Path(imported.workspace).is_dir())
                    ),
                }
            )
        except SkippedSession:
            skipped += 1
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append({"path": str(path), "message": str(exc)})
    # History-only imports can be linked even after the original logs were removed.
    for imported in existing.values():
        if imported.import_source != source or imported.id in seen:
            continue
        sessions.append(
            {
                "id": imported.source_session_id,
                "source": source,
                "path": imported.source_session_path or "",
                "title": imported.title or imported.id,
                "workspace": imported.source_workspace or "",
                "workspace_available": bool(
                    imported.source_workspace and Path(imported.source_workspace).is_dir()
                ),
                "archived": imported.archived,
                "model": imported.import_source_model or "",
                "message_count": None,
                "updated_at": imported.updated_at.isoformat(),
                "warnings": [],
                "imported_thread_id": imported.id,
                "history_only": imported.import_history_only
                or not Path(imported.workspace).is_dir(),
            }
        )
    sessions.sort(key=lambda s: s["updated_at"], reverse=True)
    return {
        "root": str(folder),
        "available": folder.is_dir(),
        "sessions": sessions,
        "errors": errors,
        "skipped": skipped,
    }


def import_session(
    store: RuntimeThreadStore,
    *,
    source: Source,
    root: str | None,
    path: str,
    session_id: str,
    workspace: str | None,
    model: str,
    provider: str,
) -> dict:
    target = Path(workspace).expanduser().resolve() if workspace else None
    if target is not None and not target.is_dir():
        raise ValueError("The selected project folder is unavailable")
    identity = History(source, Path(path), session_id=session_id)
    with store.event_lock():
        try:
            existing = store.load_thread(identity.thread_id)
        except FileNotFoundError:
            existing = None
        if existing:
            if (existing.import_history_only or not Path(existing.workspace).is_dir()) and target:
                existing.workspace = str(target)
                existing.import_history_only = False
                store.save_thread(existing)
                return {"status": "linked", "thread_id": existing.id, "warnings": []}
            return {
                "status": "skipped",
                "thread_id": existing.id,
                "history_only": existing.import_history_only,
                "warnings": [],
            }
    folder = source_root(source, root)
    candidate = Path(path).expanduser().resolve()
    if candidate.suffix != ".jsonl" or not candidate.is_relative_to(folder):
        raise ValueError("Choose a session inside the scanned source folder")
    history = read_history(source, candidate)
    if source == "codex":
        meta = codex_catalog(folder).get(history.session_id, {})
        history.title = str(meta.get("title") or history.title)
        history.archived = bool(meta.get("archived", history.archived))
    if history.session_id != session_id:
        raise ValueError("The source session changed; scan again")
    if target is None and history.workspace and Path(history.workspace).is_dir():
        target = Path(history.workspace).resolve()
    # A missing source directory never silently inherits the application's current project.
    history_only = target is None
    workspace_path = str(target or user_deepseek_dir() / "workspace")
    with store.event_lock():
        # Another importer may have committed while this file was being parsed.
        try:
            existing = store.load_thread(history.thread_id)
        except FileNotFoundError:
            existing = None
        if existing:
            return {
                "status": "skipped",
                "thread_id": existing.id,
                "history_only": existing.import_history_only,
                "warnings": [],
            }
        turns: list[TurnRecord] = []
        items: list[TurnItemRecord] = []
        current: TurnRecord | None = None
        for index, entry in enumerate(history.entries):
            if entry.kind == "user_message":
                # Native turn order is timestamp-based. Preserve source order even
                # for coarse or regressing timestamps; keep the original on items.
                turn_time = entry.timestamp
                if turns and turn_time <= turns[-1].created_at:
                    turn_time = turns[-1].created_at + timedelta(microseconds=1)
                current = TurnRecord(
                    id=f"{history.thread_id}_turn_{index:08d}",
                    thread_id=history.thread_id,
                    status=RuntimeTurnStatus.COMPLETED,
                    input_summary=entry.text[:280],
                    created_at=turn_time,
                    started_at=entry.timestamp,
                )
                turns.append(current)
            if current is None:
                continue
            item = TurnItemRecord(
                id=f"{history.thread_id}_item_{index:08d}",
                turn_id=current.id,
                kind=TurnItemKind(entry.kind),
                status=TurnItemLifecycleStatus.FAILED
                if entry.failed
                else TurnItemLifecycleStatus.COMPLETED,
                summary=(entry.name or entry.text)[:280],
                detail=entry.text,
                metadata={"external_history": True, "source": source, "tool_name": entry.name},
                started_at=entry.timestamp,
                ended_at=entry.timestamp,
            )
            current.item_ids.append(item.id)
            current.ended_at = entry.timestamp
            items.append(item)
        thread = ThreadRecord(
            id=history.thread_id,
            title=history.title,
            model=model,
            provider=provider,
            workspace=workspace_path,
            created_at=turns[0].created_at,
            updated_at=history.entries[-1].timestamp,
            latest_turn_id=turns[-1].id,
            source_session_id=history.session_id,
            source_session_path=str(candidate),
            source_workspace=history.workspace,
            import_source=source,
            import_history_only=history_only,
            import_source_model=history.model,
            archived=history.archived,
        )
        try:
            for item in items:
                store.save_item(item)
            for turn in turns:
                store.save_turn(turn)
            # Commit the discoverable thread last. A retry uses the same IDs.
            store.save_thread(thread)
        except Exception:
            for item in items:
                store.delete_item(item.id)
            for turn in turns:
                store.delete_turn(turn.id)
            store.delete_thread(thread.id)
            raise
    return {
        "status": "imported",
        "thread_id": thread.id,
        "history_only": history_only,
        "warnings": sorted(history.warnings),
    }
