"""Read-only Codex / Claude Code history adapters and native session import.

Codex uses its read-only history protocol when available. Imported tools remain inert.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from deepseek_tui.config.paths import user_deepseek_dir
from deepseek_tui.server.codex_history import (
    CodexHistoryClient,
    UnsupportedHistory,
    codex_executable,
)
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
    incomplete: bool = False
    source_id: str = ""
    source_turn_id: str = ""
    agent_segment: str | None = None


@dataclass
class History:
    source: Source
    path: Path
    session_id: str = ""
    workspace: str = ""
    title: str = ""
    model: str = ""
    archived: bool = False
    paths: list[Path] = field(default_factory=list)
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


def records(history: History, byte_limit: int | None = None) -> Iterator[dict]:
    # Freeze the byte boundary so an active source cannot extend this import forever.
    with history.path.open("rb") as stream:
        size = os.fstat(stream.fileno()).st_size
        if byte_limit is not None and not 0 <= byte_limit <= size:
            raise ValueError("Referenced Codex history byte boundary is unavailable")
        remaining = size if byte_limit is None else byte_limit
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
                if byte_limit is None and remaining == 0 and not line.endswith(b"\n"):
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


def codex_header(path: Path) -> dict:
    iterator = records(History("codex", path))
    try:
        header = next(iterator, {})
    finally:
        iterator.close()
    payload = header.get("payload")
    if header.get("type") != "session_meta" or not isinstance(payload, dict):
        raise ValueError("Not a recognized Codex session header")
    if not (payload.get("id") or payload.get("session_id")):
        raise ValueError("Codex session ID is missing")
    base = payload.get("history_base")
    if base is not None and (
        not isinstance(base, dict)
        or not isinstance(base.get("thread_id"), str)
        or any(
            type(base.get(key)) is not int or base[key] < 0
            for key in ("end_ordinal_exclusive", "end_byte_offset")
        )
    ):
        raise ValueError("Codex history has an invalid inheritance reference")
    return header


def rollout_id(path: Path, header: dict) -> str:
    # Codex names each rollout with its storage UUID, distinct from the logical session ID.
    match = re.search(r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$", path.stem)
    return (
        match[1] if match else str(header["payload"].get("id") or header["payload"]["session_id"])
    )


def codex_records(history: History) -> Iterator[dict]:
    paths = history.paths or [history.path]
    headers = {path: codex_header(path) for path in paths}
    lookup = {rollout_id(path, header): path for path, header in headers.items()}
    visiting: set[Path] = set()

    def visit(path: Path, end: int | None = None, byte_end: int | None = None):
        if path in visiting or len(visiting) >= 128:
            raise ValueError(
                "Codex history contains a cyclic or excessively deep inheritance chain"
            )
        visiting.add(path)
        header = headers[path]
        base = header["payload"].get("history_base")
        if base:
            parent = lookup.get(str(base.get("thread_id")))
            boundary = base.get("end_ordinal_exclusive")
            offset = base.get("end_byte_offset")
            if parent is None or not isinstance(boundary, int) or not isinstance(offset, int):
                raise ValueError("Referenced Codex ancestor or inheritance boundary is missing")
            inherited_end = min(boundary, end) if end is not None else boundary
            yield from visit(parent, inherited_end, offset if inherited_end == boundary else None)
        part = History("codex", path)
        for row in records(part, byte_end):
            ordinal = row.get("ordinal")
            if end is not None:
                if not isinstance(ordinal, int):
                    raise ValueError("Referenced Codex history has no event ordinals")
                if ordinal >= end:
                    if byte_end is not None:
                        raise ValueError("Codex ordinal and byte inheritance boundaries disagree")
                    break
            yield row
        if byte_end is not None and byte_end < path.stat().st_size:
            with path.open("rb") as stream:
                stream.seek(byte_end)
                line = stream.readline(MAX_LINE_BYTES + 1)
            try:
                following = json.loads(line)
            except ValueError as exc:
                raise ValueError(
                    "Codex inheritance boundary is not a complete record boundary"
                ) from exc
            if following.get("ordinal") != end:
                raise ValueError("Codex ordinal and byte inheritance boundaries disagree")
        history.warnings.update(part.warnings)
        visiting.remove(path)

    yield from visit(history.path)


def grouped_paths(source: Source, root: Path) -> tuple[list[list[Path]], list[dict]]:
    if source != "codex":
        return [[path] for path in session_paths(source, root)], []
    headers, groups, lookup, errors = {}, {}, {}, []
    for path in session_paths(source, root):
        try:
            header = codex_header(path)
            headers[path] = header
            sid = str(header["payload"].get("id") or header["payload"]["session_id"])
            groups.setdefault(sid, []).append(path)
            lookup.setdefault(rollout_id(path, header), []).append(path)
        except (OSError, ValueError, TypeError) as exc:
            errors.append({"path": str(path), "message": str(exc)})
    catalog = codex_catalog(root)
    result = []

    def unique(candidates):
        if not candidates:
            raise ValueError("Referenced Codex history is missing")
        if len(candidates) > 1:
            digests = {hashlib.sha256(p.read_bytes()).digest() for p in candidates}
            if len(digests) != 1:
                raise ValueError("Ambiguous Codex history; supply its original session index")
        return candidates[0]

    for sid, paths in groups.items():
        try:
            indexed = catalog.get(sid, {}).get("rollout_path")
            if indexed:
                # Backups may move to another machine: retain the indexed file identity.
                head = unique([p for p in paths if p.name == Path(indexed).name])
            else:
                parents = {
                    str((headers[p]["payload"].get("history_base") or {}).get("thread_id"))
                    for p in paths
                }
                head = unique([p for p in paths if rollout_id(p, headers[p]) not in parents])
            chain, current = [], head
            while True:
                if current in chain or len(chain) >= 128:
                    raise ValueError(
                        "Codex history contains a cyclic or excessively deep inheritance chain"
                    )
                chain.append(current)
                base = headers[current]["payload"].get("history_base")
                if not base:
                    break
                current = unique(lookup.get(str(base.get("thread_id")), []))
            result.append(chain)
        except (OSError, ValueError, TypeError) as exc:
            errors.append({"path": str(paths[0]), "message": str(exc)})
    return result, errors


@contextmanager
def native_history_client(source: Source, folder: Path):
    home = source_root("codex")
    executable = (
        codex_executable()
        if source == "codex" and folder in {home, home / "sessions", home / "archived_sessions"}
        else None
    )
    client = CodexHistoryClient(executable, home) if executable else None
    try:
        yield client
    finally:
        if client:
            client.close()


def imported_agent_segment(phase: Any) -> str:
    # Preserve explicit source semantics; unclassified historical prose stays visible.
    return "mid_turn_preface" if phase in {"commentary", "analysis"} else "final_answer"


def load_history(source: Source, path: Path, paths: list[Path], client=None) -> History:
    if client is None:
        return read_history(source, path, paths)
    header = codex_header(path)["payload"]
    if isinstance(header.get("source"), dict) and "subagent" in header["source"]:
        raise SkippedSession("Subagent session")
    sid = str(header.get("id") or header["session_id"])
    try:
        metadata, turns = client.read(sid)
    except UnsupportedHistory:
        history = read_history(source, path, paths)
        history.warnings.add("native_history_unavailable")
        return history
    history = History(
        source,
        path,
        session_id=sid,
        paths=paths,
        title=metadata.get("name") or metadata.get("preview") or "",
        workspace=metadata.get("cwd") or header.get("cwd") or "",
        archived="archived_sessions" in path.parts,
    )
    for turn in turns:
        when = datetime.fromtimestamp(turn.get("startedAt") or path.stat().st_mtime, timezone.utc)
        for item in turn["items"]:
            kind = item["type"]
            if kind == "userMessage":
                entry = Entry(
                    "user_message", text_blocks(item.get("content"), history.warnings), when
                )
            elif kind == "agentMessage":
                entry = Entry(
                    "agent_message",
                    item.get("text") or "",
                    when,
                    agent_segment=imported_agent_segment(item.get("phase")),
                )
            elif kind == "reasoning":
                entry = Entry(
                    "agent_reasoning",
                    "\n".join(item.get("summary") or item.get("content") or []),
                    when,
                )
            else:
                # Preserve unfamiliar native items as inert evidence, not executable tools.
                entry = Entry(
                    "tool_call",
                    encoded({k: v for k, v in item.items() if k != "id"}),
                    when,
                    kind,
                    item.get("status") == "failed",
                    item.get("status") in {"inProgress", "interrupted", "cancelled"},
                )
                if kind == "contextCompaction":
                    history.warnings.add("compacted_history")
            if entry.text:
                entry.source_id = item["id"]
                entry.source_turn_id = turn["id"]
                history.entries.append(entry)
    if not any(e.kind == "user_message" for e in history.entries):
        raise SkippedSession("Session has no importable user messages")
    if not history.title:
        history.title = next(e.text for e in history.entries if e.kind == "user_message")[:120]
    return history


def history_digest(history: History) -> str:
    data = {"version": 2, "source": history.source, "entries": [asdict(e) for e in history.entries]}
    return hashlib.sha256(json.dumps(data, default=str, sort_keys=True).encode()).hexdigest()


def import_matches(store: RuntimeThreadStore, history: History, thread: ThreadRecord) -> bool:
    if thread.import_fingerprint != history_digest(history):
        return False
    previous = [
        item
        for turn in store.list_turns_for_thread(thread.id)
        if turn.import_generation == thread.import_generation
        for item in store.list_items_for_turn(turn.id)
    ]
    return [(i.kind.value, i.detail) for i in previous] == [
        (e.kind, e.text) for e in history.entries
    ]


def backup_import(store: RuntimeThreadStore, thread: ThreadRecord, turns: list[TurnRecord]) -> Path:
    backup = (
        store.root
        / "import_backups"
        / thread.id
        / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    )
    for name in ("threads", "turns", "items"):
        (backup / name).mkdir(parents=True, exist_ok=False)
    shutil.copy2(store.root / "threads" / f"{thread.id}.json", backup / "threads")
    for turn in turns:
        shutil.copy2(store.root / "turns" / f"{turn.id}.json", backup / "turns")
        for item in store.list_items_for_turn(turn.id):
            shutil.copy2(store.root / "items" / f"{item.id}.json", backup / "items")
    return backup


def read_codex(history: History) -> None:
    source = codex_header(history.path)["payload"].get("source")
    if isinstance(source, dict) and "subagent" in source:
        raise SkippedSession("Subagent session")
    fallback = datetime.fromtimestamp(history.path.stat().st_mtime, timezone.utc)
    responses: list[Entry] = []
    presentation: list[Entry] = []
    tools: dict[str, Entry] = {}
    has_presentation_user = False
    for row in codex_records(history):
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        when = timestamp(row.get("timestamp"), fallback)
        kind = row.get("type")
        subtype = payload.get("type")
        if kind == "session_meta" or (kind == "event_msg" and subtype == "task_started"):
            history.entries.extend(presentation if has_presentation_user else responses)
            responses = []
            presentation = []
            has_presentation_user = False
        if kind == "session_meta":
            history.session_id = str(payload.get("id") or payload.get("session_id") or "")
            history.workspace = str(payload.get("cwd") or "")
        elif kind == "turn_context":
            history.model = str(payload.get("model") or history.model)
        elif kind == "response_item":
            if subtype == "message" and payload.get("role") in {"user", "assistant"}:
                role = "user_message" if payload["role"] == "user" else "agent_message"
                text = text_blocks(payload.get("content"), history.warnings)
                if text:
                    responses.append(
                        Entry(
                            role,
                            text,
                            when,
                            agent_segment=imported_agent_segment(
                                payload.get("phase") or payload.get("channel")
                            )
                            if role == "agent_message"
                            else None,
                        )
                    )
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
                            agent_segment=imported_agent_segment(item.get("phase"))
                            if itype == "AgentMessage"
                            else None,
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
                        item.get("status")
                        in {"in_progress", "interrupted", "cancelled", "canceled"},
                    )
                )
            elif itype not in {"ContextCompaction"}:
                history.warnings.add("unsupported_records")
        elif kind == "compacted":
            history.warnings.add("compacted_history")
        elif kind == "event_msg" and subtype == "turn_aborted":
            history.warnings.add("interrupted_source")
    # Select the projection per turn, allowing CLI/Desktop history in one session.
    history.entries.extend(presentation if has_presentation_user else responses)
    if tools:
        history.warnings.add("unfinished_tools")
        for entry in tools.values():
            entry.incomplete = True


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
    current = leaf if leaf and leaf_at > last_message_at else last_message
    chain: list[dict] = []
    seen: set[str] = set()
    while current and current in nodes and current not in seen:
        seen.add(current)
        row = nodes[current]
        chain.append(row)
        current = str(row.get("parentUuid") or row.get("logicalParentUuid") or "")
    if current:
        raise ValueError(
            "Claude history has a missing ancestor or cyclic branch; no partial import was saved"
        )
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
        calls_tools = message.get("stop_reason") == "tool_use" or (
            isinstance(content, list)
            and any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
        )
        segment = "mid_turn_preface" if calls_tools else "final_answer"
        if row.get("isCompactSummary"):
            history.warnings.add("compacted_history")
        kind = "user_message" if message.get("role") == "user" else "agent_message"
        if isinstance(content, str) and content:
            history.entries.append(
                Entry(
                    kind,
                    content,
                    when,
                    source_id=str(row.get("uuid", "")),
                    agent_segment=segment if kind == "agent_message" else None,
                )
            )
        for block_index, block in enumerate(content if isinstance(content, list) else []):
            if not isinstance(block, dict):
                continue
            text = text_blocks([block], history.warnings)
            entry_start = len(history.entries)
            if text:
                history.entries.append(
                    Entry(
                        kind, text, when, agent_segment=segment if kind == "agent_message" else None
                    )
                )
            elif block.get("type") == "thinking" and block.get("thinking"):
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
                    history.entries.append(
                        Entry(
                            "tool_call",
                            result,
                            when,
                            "unpaired_tool_result",
                            bool(block.get("is_error")),
                        )
                    )
            elif block.get("type") not in {"thinking", "redacted_thinking"}:
                history.warnings.add("unsupported_records")
            for entry in history.entries[entry_start:]:
                entry.source_id = f"{row.get('uuid', '')}:{block_index}"
    if tools:
        history.warnings.add("unfinished_tools")
        for entry in tools.values():
            entry.incomplete = True


def read_history(source: Source, path: Path, paths: list[Path] | None = None) -> History:
    history = History(source, path, paths=paths or [], archived="archived_sessions" in path.parts)
    stamps = {p: (p.stat().st_size, p.stat().st_mtime_ns) for p in paths or [path]}
    (read_codex if source == "codex" else read_claude)(history)
    if any((p.stat().st_size, p.stat().st_mtime_ns) != stamp for p, stamp in stamps.items()):
        raise ValueError("Source history changed while reading; scan again")
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
    for database in sorted(
        home.glob("state_*.sqlite"), key=lambda p: int(p.stem.split("_")[-1]), reverse=True
    ):
        try:
            with closing(
                sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
            ) as conn:
                columns = {r[1] for r in conn.execute("PRAGMA table_info(threads)")}
                path_column = "rollout_path" if "rollout_path" in columns else "NULL"
                for sid, title, archived, path in conn.execute(
                    f"SELECT id, title, archived, {path_column} FROM threads"
                ):
                    catalog.setdefault(
                        sid, {"title": title, "archived": bool(archived), "rollout_path": path}
                    )
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
    with native_history_client(source, source_root(source, root)) as client:
        return _scan_sessions(store, source, root, client)


def _scan_sessions(store: RuntimeThreadStore, source: Source, root: str | None, client) -> dict:
    folder = source_root(source, root)
    sessions = []
    groups, errors = grouped_paths(source, folder)
    catalog = codex_catalog(folder) if source == "codex" else {}
    skipped = 0
    existing = {t.id: t for t in store.list_threads()}
    seen = set()
    for paths in groups:
        path = paths[0]
        try:
            history = load_history(source, path, paths, client)
            meta = catalog.get(history.session_id, {})
            history.title = str(meta.get("title") or history.title)
            history.archived = bool(meta.get("archived", history.archived))
            if history.thread_id in seen:
                continue
            seen.add(history.thread_id)
            imported = existing.get(history.thread_id)
            update_available = bool(imported and not import_matches(store, history, imported))
            sessions.append(
                {
                    "update_available": update_available,
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
        identity = History(source, Path(), session_id=imported.source_session_id or "")
        if imported.id != identity.thread_id:
            continue  # Native forks have their own lifecycle, not an import identity.
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
    folder = source_root(source, root)
    candidate = Path(path).expanduser().resolve()
    if candidate.suffix != ".jsonl" or not candidate.is_relative_to(folder):
        raise ValueError("Choose a session inside the scanned source folder")
    paths = [candidate]
    if source == "codex":
        groups, errors = grouped_paths(source, folder)
        paths = next(
            (
                group
                for group in groups
                if candidate in group
                and str(
                    codex_header(group[0])["payload"].get("id")
                    or codex_header(group[0])["payload"].get("session_id")
                )
                == session_id
            ),
            [],
        )
        if not paths:
            reason = next(
                (error["message"] for error in errors if error["path"] == str(candidate)),
                "The selected session is no longer part of the current history; scan again",
            )
            raise ValueError(reason)
    with native_history_client(source, folder) as client:
        history = load_history(source, paths[0], paths, client)
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
        fingerprint = history_digest(history)
        generation = uuid4().hex
        if existing and import_matches(store, history, existing):
            return {
                "status": "skipped",
                "thread_id": existing.id,
                "history_only": existing.import_history_only,
                "warnings": sorted(history.warnings),
            }
        old_turns = [
            t
            for t in store.list_turns_for_thread(history.thread_id)
            if t.import_generation or t.id.startswith(f"{history.thread_id}_turn_")
        ]
        backup = backup_import(store, existing, old_turns) if existing else None
        turns: list[TurnRecord] = []
        items: list[TurnItemRecord] = []
        current: TurnRecord | None = None
        source_turn = None
        for index, entry in enumerate(history.entries):
            starts_turn = (
                entry.source_turn_id != source_turn
                if entry.source_turn_id
                else entry.kind == "user_message"
            )
            if current is None or starts_turn:
                source_turn = entry.source_turn_id
                # Native turn order is timestamp-based. Preserve source order even
                # for coarse or regressing timestamps; keep the original on items.
                turn_time = entry.timestamp
                if turns and turn_time <= turns[-1].created_at:
                    turn_time = turns[-1].created_at + timedelta(microseconds=1)
                current = TurnRecord(
                    id=f"{history.thread_id}_turn_{generation[:16]}_{index:08d}",
                    import_generation=generation,
                    thread_id=history.thread_id,
                    status=RuntimeTurnStatus.COMPLETED,
                    input_summary=entry.text[:280],
                    created_at=turn_time,
                    started_at=entry.timestamp,
                )
                turns.append(current)
            item = TurnItemRecord(
                id=f"{history.thread_id}_item_{generation[:16]}_{index:08d}",
                turn_id=current.id,
                kind=TurnItemKind(entry.kind),
                status=(
                    TurnItemLifecycleStatus.INTERRUPTED
                    if entry.incomplete
                    else TurnItemLifecycleStatus.FAILED
                    if entry.failed
                    else TurnItemLifecycleStatus.COMPLETED
                ),
                summary=(entry.name or entry.text)[:280],
                detail=entry.text,
                metadata={
                    "external_history": True,
                    "source": source,
                    "tool_name": entry.name,
                    "source_item_id": entry.source_id,
                    "source_turn_id": entry.source_turn_id,
                    **(
                        {"agent_segment": entry.agent_segment or "final_answer"}
                        if entry.kind == "agent_message"
                        else {}
                    ),
                },
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
            import_generation=generation,
            import_fingerprint=fingerprint,
            import_history_only=history_only,
            import_source_model=history.model,
            archived=history.archived,
        )
        if existing:
            # Replace only imported history; preserve native follow-up turns and settings.
            thread = existing.model_copy(deep=True)
            thread.source_session_path = str(paths[0])
            thread.updated_at = max(thread.updated_at, history.entries[-1].timestamp)
            thread.import_generation = generation
            thread.import_fingerprint = fingerprint
            if thread.latest_turn_id in {t.id for t in old_turns}:
                thread.latest_turn_id = turns[-1].id
            history_only = thread.import_history_only
        new_items = items
        try:
            for item in new_items:
                store.save_item(item)
            for turn in turns:
                store.save_turn(turn)
            # Atomically publish this complete generation only after all records exist.
            store.save_thread(thread)
        except Exception:
            # The original thread pointer is unchanged until the final atomic save.
            for item in new_items:
                store.delete_item(item.id)
            for turn in turns:
                store.delete_turn(turn.id)
            raise
        # Superseded files are already hidden by the committed generation pointer.
        # Retain the separate backup for recovery, and tolerate interrupted cleanup.
        for old in old_turns:
            try:
                for item in store.list_items_for_turn(old.id):
                    store.delete_item(item.id)
                store.delete_turn(old.id)
            except OSError:
                history.warnings.add("backup_cleanup_pending")
    return {
        "status": "updated" if existing else "imported",
        "backup_path": str(backup) if backup else None,
        "thread_id": thread.id,
        "history_only": history_only,
        "warnings": sorted(history.warnings),
    }
