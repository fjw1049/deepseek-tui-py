"""Turn-item presentation helpers.

Classify tool calls into item kinds, extract todo/task metadata from tool
results, synthesize file-change diffs, and reconstruct engine messages from
persisted turns.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from deepseek_tui.server.threads.models import (
    TurnItemKind,
    TurnItemLifecycleStatus,
    TurnItemRecord,
    TurnRecord,
)

if TYPE_CHECKING:
    from deepseek_tui.server.threads.store import RuntimeThreadStore


# --- helper functions --------------------------------------------------------


def _ordered_turn_items(
    store: RuntimeThreadStore,
    turn: TurnRecord,
) -> list[TurnItemRecord]:
    """Return turn items in persisted order (``item_ids``), with stable fallback."""
    items = store.list_items_for_turn(turn.id)
    if not items:
        return []

    kind_rank = {
        TurnItemKind.USER_MESSAGE: 0,
        TurnItemKind.AGENT_MESSAGE: 1,
    }

    def sort_key(item: TurnItemRecord) -> tuple:
        started = item.started_at or datetime.min.replace(tzinfo=timezone.utc)
        return (started, kind_rank.get(item.kind, 99), item.id)

    if not turn.item_ids:
        return sorted(items, key=sort_key)

    by_id = {item.id: item for item in items}
    ordered = [by_id[item_id] for item_id in turn.item_ids if item_id in by_id]
    seen = set(turn.item_ids)
    orphans = sorted((item for item in items if item.id not in seen), key=sort_key)
    return ordered + orphans


def reconstruct_messages_from_turn(
    store: RuntimeThreadStore,
    turn: TurnRecord,
) -> list:
    """Rebuild chat messages for one turn at the last completed tool-round.

    Soft-resume contract (aligned with Task/SubAgent durable transcripts):
    - Keep COMPLETED / FAILED tools (failed = finished round with error).
    - Drop INTERRUPTED / IN_PROGRESS / QUEUED tools and interrupted agent
      text so the next turn never resumes mid-tool.
    - ``CONTEXT_COMPACTION`` items that carry a ``session_messages`` snapshot
      replace history accumulated so far (manual /compact persistence).
    """
    from deepseek_tui.protocol.messages import (
        Message,
        Role,
        TextBlock,
        ToolUseBlock,
    )
    from deepseek_tui.tools.durable_transcript import dicts_to_messages

    messages: list[Message] = []
    for item in _ordered_turn_items(store, turn):
        text = (item.detail or item.summary or "").strip()
        if item.kind == TurnItemKind.CONTEXT_COMPACTION:
            meta = item.metadata if isinstance(item.metadata, dict) else {}
            snap = meta.get("session_messages")
            if isinstance(snap, list) and snap:
                messages = list(dicts_to_messages(snap))
            continue
        if item.kind == TurnItemKind.USER_MESSAGE:
            if not text:
                continue
            messages.append(
                Message(role=Role.USER, content=[TextBlock(text=text)])
            )
        elif item.kind == TurnItemKind.AGENT_MESSAGE:
            # Partial preface from a cancelled stream must not seed resume.
            if item.status in {
                TurnItemLifecycleStatus.INTERRUPTED,
                TurnItemLifecycleStatus.IN_PROGRESS,
                TurnItemLifecycleStatus.QUEUED,
                TurnItemLifecycleStatus.CANCELED,
            }:
                continue
            if not text:
                continue
            messages.append(
                Message(role=Role.ASSISTANT, content=[TextBlock(text=text)])
            )
        elif item.kind in {
            TurnItemKind.TOOL_CALL,
            TurnItemKind.COMMAND_EXECUTION,
            TurnItemKind.FILE_CHANGE,
        }:
            # Incomplete tool rounds are the soft-resume cutoff — omit them
            # entirely (do not emit unpaired tool_use or interrupt stubs).
            if item.status not in {
                TurnItemLifecycleStatus.COMPLETED,
                TurnItemLifecycleStatus.FAILED,
            }:
                continue
            if not text:
                continue
            meta = item.metadata if isinstance(item.metadata, dict) else {}
            tool_use_id = str(meta.get("tool_use_id") or item.id)
            tool_name = str(meta.get("tool_name") or item.summary or "tool")
            arguments = meta.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            messages.append(
                Message.assistant_with_tools(
                    [
                        ToolUseBlock(
                            id=tool_use_id,
                            name=tool_name,
                            input=arguments,
                        )
                    ]
                )
            )
            messages.append(
                Message.tool_result(
                    tool_use_id,
                    text,
                    is_error=item.status == TurnItemLifecycleStatus.FAILED,
                )
            )
    return messages


def _turn_has_compaction_snapshot(
    store: RuntimeThreadStore, turn: TurnRecord
) -> bool:
    for item in _ordered_turn_items(store, turn):
        if item.kind is not TurnItemKind.CONTEXT_COMPACTION:
            continue
        meta = item.metadata if isinstance(item.metadata, dict) else {}
        snap = meta.get("session_messages")
        if isinstance(snap, list) and snap:
            return True
    return False


def reconstruct_messages_from_turns(
    store: RuntimeThreadStore,
    thread_id: str,
) -> list:
    """Rebuild Engine chat history from persisted turn items."""
    messages: list = []
    for turn in store.list_turns_for_thread(thread_id):
        turn_msgs = reconstruct_messages_from_turn(store, turn)
        if _turn_has_compaction_snapshot(store, turn):
            # Snapshot already includes prior history — replace, don't append.
            messages = turn_msgs
        else:
            messages.extend(turn_msgs)
    return messages


def tool_kind_for_name(name: str) -> TurnItemKind:
    """Classify a tool name into its turn-item kind."""
    lower = name.lower()
    if lower in ("exec_shell", "exec_shell_wait", "exec_shell_interact"):
        return TurnItemKind.COMMAND_EXECUTION
    if "patch" in lower or "write" in lower or "edit" in lower:
        return TurnItemKind.FILE_CHANGE
    return TurnItemKind.TOOL_CALL


def _parse_tool_arguments(arguments: Any) -> dict[str, Any] | None:
    args = arguments
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(args, dict):
        return None
    return args


def _is_todo_tool_name(tool_name: str) -> bool:
    lower = tool_name.lower()
    return "todo" in lower or "checklist" in lower


def _todo_items_from_arguments(args: dict[str, Any]) -> list[dict[str, Any]] | None:
    todos = args.get("todos")
    if isinstance(todos, list) and todos:
        items: list[dict[str, Any]] = []
        for index, entry in enumerate(todos, start=1):
            if isinstance(entry, str) and entry.strip():
                items.append({"id": index, "content": entry.strip(), "status": "pending"})
                continue
            if not isinstance(entry, dict):
                continue
            content = entry.get("content") or entry.get("text")
            if not isinstance(content, str) or not content.strip():
                continue
            status = entry.get("status") if isinstance(entry.get("status"), str) else "pending"
            item_id = entry.get("id", index)
            items.append(
                {
                    "id": item_id,
                    "content": content.strip(),
                    "status": status,
                }
            )
        return items or None
    legacy = args.get("items")
    if isinstance(legacy, list) and legacy:
        return [
            {"id": index, "content": str(text).strip(), "status": "pending"}
            for index, text in enumerate(legacy, start=1)
            if isinstance(text, str) and str(text).strip()
        ] or None
    return None


def todo_tool_metadata(tool_name: str, arguments: Any) -> dict[str, Any] | None:
    """Expose checklist/todo payloads to Workbench sidebar consumers."""
    if not _is_todo_tool_name(tool_name):
        return None
    args = _parse_tool_arguments(arguments)
    if not args:
        return {"tool_name": tool_name}
    items = _todo_items_from_arguments(args)
    if not items:
        return {"tool_name": tool_name}
    completed = sum(
        1
        for item in items
        if str(item.get("status", "")).lower() in {"completed", "done"}
    )
    return {
        "tool_name": tool_name,
        "items": items,
        "completion_pct": round(completed * 100 / len(items)) if items else 0,
    }


def todo_tool_metadata_from_result(
    tool_name: str,
    arguments: Any,
    result_metadata: dict[str, Any] | None,
    existing_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Merge checklist snapshots from tool args and result metadata for Workbench."""
    if not _is_todo_tool_name(tool_name):
        return None
    base: dict[str, Any] = dict(existing_metadata) if existing_metadata else {}
    base["tool_name"] = tool_name

    if isinstance(result_metadata, dict):
        task_updates = result_metadata.get("task_updates")
        if isinstance(task_updates, dict):
            checklist = task_updates.get("checklist")
            if isinstance(checklist, dict):
                items_raw = checklist.get("items")
                if isinstance(items_raw, list) and items_raw:
                    items: list[dict[str, Any]] = []
                    for index, entry in enumerate(items_raw, start=1):
                        if not isinstance(entry, dict):
                            continue
                        content = entry.get("content") or entry.get("text")
                        if not isinstance(content, str) or not content.strip():
                            continue
                        status = (
                            entry.get("status")
                            if isinstance(entry.get("status"), str)
                            else "pending"
                        )
                        item_id = entry.get("id", index)
                        items.append(
                            {
                                "id": item_id,
                                "content": content.strip(),
                                "status": status,
                            }
                        )
                    if items:
                        completed = sum(
                            1
                            for item in items
                            if str(item.get("status", "")).lower()
                            in {"completed", "done"}
                        )
                        base["items"] = items
                        base["completion_pct"] = (
                            round(completed * 100 / len(items)) if items else 0
                        )
                        in_progress = checklist.get("in_progress_id")
                        if in_progress is not None:
                            base["in_progress_id"] = in_progress
                        return base

    from_args = todo_tool_metadata(tool_name, arguments)
    if from_args and from_args.get("items"):
        base.update(from_args)
        return base

    args = _parse_tool_arguments(arguments)
    if args and "item_id" in args:
        items = base.get("items")
        if isinstance(items, list):
            item_id = str(args["item_id"])
            new_status: str | None = None
            if isinstance(args.get("status"), str):
                new_status = str(args["status"]).lower()
            elif isinstance(args.get("done"), bool):
                new_status = "completed" if args["done"] else "pending"
            if new_status:
                updated: list[dict[str, Any]] = []
                for row in items:
                    if not isinstance(row, dict):
                        continue
                    copy = dict(row)
                    if str(copy.get("id")) == item_id:
                        copy["status"] = new_status
                    updated.append(copy)
                base["items"] = updated
                completed = sum(
                    1
                    for item in updated
                    if str(item.get("status", "")).lower() in {"completed", "done"}
                )
                base["completion_pct"] = (
                    round(completed * 100 / len(updated)) if updated else 0
                )
                return base

    return from_args or (base if base.get("items") else None)


_TASK_TOOL_NAMES = frozenset(
    {"task_create", "task_list", "task_read", "task_cancel"}
)


def _is_task_tool_name(tool_name: str) -> bool:
    return tool_name in _TASK_TOOL_NAMES


def _normalize_task_entry(entry: Any) -> dict[str, Any] | None:
    """Coerce a task summary dict into the Workbench sidebar shape."""
    if not isinstance(entry, dict):
        return None
    task_id = entry.get("id") or entry.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        return None
    status = entry.get("status")
    status = status.strip().lower() if isinstance(status, str) else "queued"
    prompt = entry.get("prompt_summary") or entry.get("prompt") or ""
    return {
        "id": task_id.strip(),
        "status": status,
        "prompt": str(prompt).strip(),
    }


def task_tool_metadata_from_result(
    tool_name: str,
    arguments: Any,
    result_metadata: dict[str, Any] | None,
    existing_metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Expose durable-task payloads to the Workbench TASKS sidebar section.

    ``task_list`` returns ``metadata["tasks"]`` (a list of summaries);
    ``task_create`` / ``task_read`` / ``task_cancel`` return a single task's
    ``task_id`` / ``status`` / ``prompt_summary``. Both shapes are normalised
    into ``metadata["tasks"]`` so the frontend reads one consistent field.
    """
    if not _is_task_tool_name(tool_name):
        return None
    if not isinstance(result_metadata, dict):
        return None

    entries: list[dict[str, Any]] = []
    raw_tasks = result_metadata.get("tasks")
    if isinstance(raw_tasks, list):
        for item in raw_tasks:
            normalized = _normalize_task_entry(item)
            if normalized:
                entries.append(normalized)
    else:
        normalized = _normalize_task_entry(result_metadata)
        if normalized:
            entries.append(normalized)

    if not entries:
        return None

    base: dict[str, Any] = dict(existing_metadata) if existing_metadata else {}
    base["tool_name"] = tool_name
    base["tasks"] = entries
    return base


def tool_item_metadata(tool_name: str, arguments: Any) -> dict[str, Any] | None:
    """Extract file path metadata for Workbench Diff / ChangeInspector."""
    todo_meta = todo_tool_metadata(tool_name, arguments)
    if todo_meta is not None:
        return todo_meta
    if tool_kind_for_name(tool_name) != TurnItemKind.FILE_CHANGE:
        return None
    args = _parse_tool_arguments(arguments)
    if not args:
        return None
    for key in ("path", "file_path", "filename", "target"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return {"path": value.strip()}
    return None


def tool_started_metadata(tool_name: str, arguments: Any) -> dict[str, Any] | None:
    """Metadata persisted on a tool item at start.

    Combines file-path / todo metadata (``tool_item_metadata``) with the raw
    call args under ``tool_input``. The live UI reads the args from the SSE
    event, but a thread reload reads only stored metadata — without this, read
    and search tool rows lose their descriptor ("browse dir src/", "grep TODO")
    after restore.
    """
    metadata = tool_item_metadata(tool_name, arguments)
    parsed = _parse_tool_arguments(arguments)
    if parsed:
        metadata = {**(metadata or {}), "tool_input": parsed}
    return metadata


def _looks_like_unified_diff(text: str) -> bool:
    return any(
        line.startswith(("@@", "diff --git ", "--- ", "+++ ", "index "))
        for line in text.splitlines()
    )


def _file_path_from_arguments(args: dict[str, Any]) -> str:
    for key in ("path", "file_path", "filename", "target"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "file"


def _synthesize_edit_diff(path: str, search: str, replace: str) -> str:
    old_lines = search.splitlines() or [""]
    new_lines = replace.splitlines() or [""]
    body = [f"-{line}" for line in old_lines] + [f"+{line}" for line in new_lines]
    return f"--- a/{path}\n+++ b/{path}\n@@\n" + "\n".join(body)


def _synthesize_new_file_diff(path: str, content: str) -> str:
    lines = content.splitlines()
    count = max(len(lines), 1)
    body = "\n".join(f"+{line}" for line in lines) if lines else "+"
    return f"--- /dev/null\n+++ b/{path}\n@@ -0,0 +1,{count} @@\n{body}"


def file_change_completion_detail(
    tool_name: str,
    arguments: Any,
    result_content: str,
) -> str:
    """Return unified diff text for Workbench ChangeInspector when possible."""
    content = (result_content or "").strip()
    if content and _looks_like_unified_diff(content):
        return content

    args = _parse_tool_arguments(arguments)
    if not args:
        return content

    lower = tool_name.lower()
    path = _file_path_from_arguments(args)

    if lower == "apply_patch":
        patch = args.get("patch")
        if isinstance(patch, str) and _looks_like_unified_diff(patch):
            return patch
        changes = args.get("changes")
        if isinstance(changes, list) and len(changes) == 1:
            only = changes[0]
            if isinstance(only, dict):
                change_path = only.get("path")
                change_content = only.get("content")
                if isinstance(change_path, str) and isinstance(change_content, str):
                    return _synthesize_new_file_diff(change_path.strip(), change_content)

    if lower == "edit_file":
        search = args.get("search", args.get("old_string"))
        replace = args.get("replace", args.get("new_string"))
        if isinstance(search, str) and isinstance(replace, str):
            return _synthesize_edit_diff(path, search, replace)

    if lower == "write_file":
        file_content = args.get("content")
        if isinstance(file_content, str):
            return _synthesize_new_file_diff(path, file_content)

    return content


def duration_ms(start: datetime, end: datetime) -> int:
    """Milliseconds between two datetimes, clamped to >=0."""
    delta = end - start
    ms = int(delta.total_seconds() * 1000)
    return max(ms, 0)
