"""Rewind audit records: an append-only trace of deleted conversation.

``rewind_thread`` destroys turns and items irrecoverably. Before the first
deletion the manager archives the dropped turns and items — full records —
into the thread's audit JSONL with a content fingerprint, mirroring bb's
``system/operation`` audit event for history rewrites. The archive is what
makes a rewind inspectable after the fact.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from deepseek_tui.server.threads.models import TurnRecord
from deepseek_tui.server.threads.store import RuntimeThreadStore


def build_rewind_audit_record(
    store: RuntimeThreadStore,
    thread_id: str,
    turns: list[TurnRecord],
    cutoff_turn_index: int,
    *,
    before_item_id: str,
    restore_files: bool,
) -> dict[str, Any]:
    """Archive every turn/item the rewind is about to delete, oldest first.

    Items of the cutoff turn are captured from ``before_item_id`` onward;
    every later turn is captured whole with its item records. Missing item
    files become placeholders — the audit must reflect what was deleted,
    not guess at it.
    """
    dropped: list[dict[str, Any]] = []
    item_count = 0
    for offset, turn in enumerate(turns[cutoff_turn_index:]):
        if offset == 0:
            dropping = False
            item_ids: list[str] = []
            for item_id in turn.item_ids:
                if item_id == before_item_id:
                    dropping = True
                if dropping:
                    item_ids.append(item_id)
        else:
            item_ids = list(turn.item_ids)
        items: list[dict[str, Any]] = []
        for item_id in item_ids:
            item_count += 1
            try:
                items.append(store.load_item(item_id).model_dump(mode="json"))
            except FileNotFoundError:
                items.append({"id": item_id, "missing": True})
        dropped.append({"turn": turn.model_dump(mode="json"), "items": items})

    fingerprint = hashlib.sha256(
        json.dumps(dropped, ensure_ascii=False, sort_keys=True, default=str).encode(
            "utf-8"
        )
    ).hexdigest()
    return {
        "audit_id": f"rwa_{uuid.uuid4().hex[:12]}",
        "thread_id": thread_id,
        "at": datetime.now(timezone.utc).isoformat(),
        "before_item_id": before_item_id,
        "restore_files": restore_files,
        "fingerprint": fingerprint,
        "turns": len(dropped),
        "items": item_count,
        "snapshot": dropped,
    }
