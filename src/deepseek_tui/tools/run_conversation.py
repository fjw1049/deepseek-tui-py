"""Durable display history, independent of model-context checkpoints.

One writer per running task/agent. Stable block ids let polling clients replace
streaming snapshots without duplicating messages. Old runs may have no history.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any

from deepseek_tui.config.paths import user_deepseek_dir
from deepseek_tui.utils import utc_now_iso, write_json_atomic

logger = logging.getLogger(__name__)


def conversation_path(kind: str, owner_id: str) -> Path:
    if kind not in {"task", "subagent"} or not re.fullmatch(r"[\w-]+", owner_id):
        raise ValueError("Invalid run conversation id")
    return user_deepseek_dir() / "run-conversations" / kind / f"{owner_id}.json"


def load_run_conversation(kind: str, owner_id: str) -> dict[str, Any] | None:
    path = conversation_path(kind, owner_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("blocks"), list) else None
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None


class RunConversation:
    def __init__(self, kind: str, owner_id: str, prompt: str, workspace: Path) -> None:
        self.path = conversation_path(kind, owner_id)
        existing = load_run_conversation(kind, owner_id)
        self.data = existing or {"blocks": [], "workspace": str(workspace)}
        self.blocks: list[dict[str, Any]] = self.data["blocks"]
        self.attempt = uuid.uuid4().hex[:12]
        self.prefix = f"{kind}:{owner_id}:{self.attempt}"
        self.live: dict[str, Any] | None = None
        self.thinking_live: dict[str, Any] | None = None
        self.last_write = 0.0
        self.data["status"] = "running"
        self.data["liveId"] = None
        if not existing:
            self.append("user", prompt)
        else:
            for block in self.blocks:
                if block.get("status") == "running":
                    block["status"] = "error"
                    block.setdefault("detail", "Execution interrupted")
            self.append("system", "继续执行")
        self.save()

    def save(self, *, streaming: bool = False) -> None:
        now = time.monotonic()
        if streaming and now - self.last_write < 0.25:
            return
        try:
            write_json_atomic(self.path, self.data)
            self.last_write = now
        except (OSError, TypeError, ValueError):
            logger.warning("Could not save run conversation %s", self.path, exc_info=True)

    def append(self, kind: str, text: str) -> dict[str, Any]:
        block = {
            "kind": kind,
            "id": f"{self.prefix}:{len(self.blocks)}",
            "text": text,
            "createdAt": utc_now_iso(),
        }
        self.blocks.append(block)
        return block

    def user(self, text: str) -> None:
        self.settle()
        self.append("user", text)
        self.save()

    def delta(self, text: str) -> None:
        if self.live is None:
            self.live = self.append("assistant", "")
            self.live["agentSegment"] = "mid_turn_preface"
            self.data["liveId"] = self.live["id"]
        self.live["text"] += text
        self.save(streaming=True)

    def thinking(self, text: str) -> None:
        if self.thinking_live is None:
            self.thinking_live = self.append("reasoning", "")
        self.thinking_live["text"] += text
        self.save(streaming=True)

    def settle(self, text: str | None = None, *, final: bool = False) -> None:
        if self.live is None and text:
            previous = self.blocks[-1] if self.blocks else None
            if (
                final
                and previous
                and previous.get("kind") == "assistant"
                and previous.get("text") == text
            ):
                self.live = previous
            else:
                self.live = self.append("assistant", text)
        if self.live is not None:
            if text is not None:
                self.live["text"] = text
            self.live["agentSegment"] = "final_answer" if final else "mid_turn_preface"
        self.live = None
        self.thinking_live = None
        self.data["liveId"] = None
        self.save()

    def tool(
        self,
        call_id: str,
        name: str,
        args: dict[str, Any],
        output: str | None = None,
        success: bool | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        block_id = f"{self.prefix}:tool:{call_id}"
        block = next((b for b in self.blocks if b["id"] == block_id), None)
        if block is None:
            block = {"kind": "tool", "id": block_id, "createdAt": utc_now_iso()}
            self.blocks.append(block)
        block.update(
            summary=f"{name}: ",
            status="running" if success is None else "success" if success else "error",
            meta={**(metadata or {}), "tool_name": name, "tool_input": args},
        )
        if output is not None:
            block["detail"] = output
        self.save()

    def finish(self, status: str, error: str | None = None) -> None:
        self.settle()
        self.data["status"] = status
        for block in self.blocks:
            if block.get("status") == "running":
                block["status"] = "error"
                block.setdefault("detail", "Execution interrupted")
        if error:
            self.append("system", error)["severity"] = "error"
        self.save()
