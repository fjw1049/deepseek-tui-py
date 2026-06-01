"""Historical conversation import for native memory."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepseek_tui.memory.native.manifest import MemoryManifest
from deepseek_tui.memory.provider import CaptureInput


@dataclass(slots=True)
class SeedResult:
    sessions: int = 0
    turns: int = 0
    messages: int = 0


async def seed_memory_from_file(
    provider: Any,
    path: Path,
    *,
    workspace: str,
    flush: bool = True,
) -> SeedResult:
    raw_text = await asyncio.to_thread(path.read_text, encoding="utf-8")
    raw = json.loads(raw_text)
    result = await seed_memory(provider, raw, workspace=workspace, flush=flush)
    manifest = MemoryManifest(provider._data_dir)
    manifest.record_seed_run(
        {
            "source": await asyncio.to_thread(lambda: str(path.expanduser().resolve())),
            "workspace": workspace,
            "sessions": result.sessions,
            "turns": result.turns,
            "messages": result.messages,
        }
    )
    return result


async def seed_memory(
    provider: Any,
    payload: Any,
    *,
    workspace: str,
    flush: bool = True,
) -> SeedResult:
    sessions = _normalize_sessions(payload)
    result = SeedResult(sessions=len(sessions))
    for session in sessions:
        thread_id = str(session.get("thread_id") or session.get("session_id") or "seed")
        turns = _session_turns(session)
        for idx, turn in enumerate(turns):
            user_text, messages = _turn_payload(turn, idx)
            if not user_text and not messages:
                continue
            await provider.capture(
                CaptureInput(
                    thread_id=thread_id,
                    user_text=user_text,
                    workspace=workspace,
                    messages=messages,
                    had_tool_calls=any(m.get("role") == "tool" for m in messages),
                    success=True,
                )
            )
            result.turns += 1
            result.messages += 1 + len(messages)
        if flush:
            await provider.flush_session(thread_id)
    return result


def _normalize_sessions(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("sessions"), list):
        return [s for s in payload["sessions"] if isinstance(s, dict)]
    if isinstance(payload, list):
        return [{"thread_id": "seed", "messages": payload}]
    if isinstance(payload, dict):
        return [payload]
    return []


def _session_turns(session: dict[str, Any]) -> list[Any]:
    if isinstance(session.get("turns"), list):
        return list(session["turns"])
    if isinstance(session.get("rounds"), list):
        return list(session["rounds"])
    if isinstance(session.get("messages"), list):
        return _messages_to_turns(session["messages"])
    return []


def _messages_to_turns(messages: list[Any]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", "") or "")
        if role == "user":
            if current is not None:
                turns.append(current)
            current = {"user": msg.get("content", ""), "messages": []}
        elif current is not None and role in {"assistant", "tool"}:
            current["messages"].append(msg)
    if current is not None:
        turns.append(current)
    return turns


def _turn_payload(turn: Any, idx: int) -> tuple[str, list[dict[str, Any]]]:
    if isinstance(turn, dict):
        user_text = str(turn.get("user") or turn.get("user_text") or "")
        raw_messages = turn.get("messages") or turn.get("assistant_messages") or []
        messages = [m for m in raw_messages if isinstance(m, dict)]
        return user_text, messages
    if isinstance(turn, list):
        user_text = ""
        messages: list[dict[str, Any]] = []
        for msg in turn:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "") or "")
            if role == "user" and not user_text:
                user_text = str(msg.get("content", "") or "")
            elif role in {"assistant", "tool"}:
                messages.append(msg)
        return user_text, messages
    return str(turn) if idx >= 0 else "", []
