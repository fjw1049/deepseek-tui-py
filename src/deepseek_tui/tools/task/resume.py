"""Compare a durable task's stored authority with the caller before resuming."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def task_scope(task: Any) -> dict[str, Any]:
    return {
        "workspace": str(Path(task.workspace).resolve()),
        "mode": task.mode,
        "allow_shell": task.allow_shell,
        "trust_mode": task.trust_mode,
        "auto_approve": task.auto_approve,
    }


def scope_key(scope: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(scope, sort_keys=True).encode()).hexdigest()


def permission_changes(target: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    fields = []
    if not Path(target["workspace"]).is_relative_to(Path(current["workspace"]).resolve()):
        fields.append("workspace")
    for field in ("auto_approve", "trust_mode", "allow_shell"):
        if target[field] and not current[field]:
            fields.append(field)
    if (current["mode"] == "plan" and target["mode"] != "plan") or (
        target["mode"] in ("yolo", "trust") and current["mode"] != target["mode"]
    ):
        fields.append("mode")
    return [
        {"field": field, "current": current[field], "target": target[field]} for field in fields
    ]
