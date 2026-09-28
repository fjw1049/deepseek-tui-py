"""Bounded, read-only calls to the installed Codex history protocol."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path


class UnsupportedHistory(ValueError):
    """The installed runtime cannot expose this history protocol."""


def codex_executable() -> str | None:
    # Prefer the desktop runtime that wrote desktop history over an older PATH CLI.
    for app in ("Codex.app", "ChatGPT.app"):
        candidate = Path("/Applications") / app / "Contents/Resources/codex"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("codex")


class CodexHistoryClient:
    def __init__(self, executable: str, home: Path):
        self.process = subprocess.Popen(
            [executable, "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "CODEX_HOME": str(home)},
        )
        self.messages: queue.Queue = queue.Queue()
        self.sequence = 0
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        try:
            self.call(
                "initialize",
                {
                    "clientInfo": {"name": "deepseek-history-import", "version": "1.0"},
                    "capabilities": {"experimentalApi": True},
                },
            )
            self.process.stdin.write(b'{"method":"initialized"}\n')
            self.process.stdin.flush()
        except BaseException:
            self.close()
            raise

    def _read(self) -> None:
        try:
            while line := self.process.stdout.readline(64 * 1024 * 1024 + 1):
                if len(line) > 64 * 1024 * 1024:
                    raise ValueError("Codex history response exceeds the 64 MB page limit")
                self.messages.put(json.loads(line))
        except (ValueError, OSError) as exc:
            self.messages.put(exc)
        finally:
            self.messages.put(ValueError("Codex history service closed unexpectedly"))

    def call(self, method: str, params: dict) -> dict:
        if method not in {"initialize", "thread/read", "thread/turns/list"}:
            raise ValueError("Only read-only Codex history methods are allowed")
        self.sequence += 1
        self.process.stdin.write(
            (
                json.dumps(
                    {
                        "id": self.sequence,
                        "method": method,
                        "params": params,
                    }
                )
                + "\n"
            ).encode()
        )
        self.process.stdin.flush()
        deadline = time.monotonic() + 30
        while True:
            try:
                message = self.messages.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise ValueError(
                    "Codex history request timed out; retry after closing busy tasks"
                ) from exc
            if isinstance(message, Exception):
                raise message
            if message.get("id") != self.sequence:
                continue
            if error := message.get("error"):
                if error.get("code") == -32601:
                    raise UnsupportedHistory("Installed Codex does not support history pagination")
                raise ValueError(f"Codex history read failed: {error.get('message', error)}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise ValueError("Codex returned an invalid history response")
            return result

    def read(self, thread_id: str) -> tuple[dict, list[dict]]:
        metadata = self.call("thread/read", {"threadId": thread_id, "includeTurns": False})[
            "thread"
        ]
        turns, cursors, turn_ids = [], set(), set()
        cursor = None
        deadline = time.monotonic() + 120
        while True:
            if time.monotonic() >= deadline:
                raise ValueError("Codex history pagination timed out; no partial import was saved")
            result = self.call(
                "thread/turns/list",
                {
                    "threadId": thread_id,
                    "limit": 50,
                    "sortDirection": "asc",
                    "itemsView": "full",
                    "cursor": cursor,
                },
            )
            for turn in result["data"]:
                if turn.get("itemsView") != "full" or turn["id"] in turn_ids:
                    raise ValueError(
                        "Codex returned incomplete or overlapping history pages; scan again"
                    )
                turn_ids.add(turn["id"])
                turns.append(turn)
            cursor = result.get("nextCursor")
            if cursor is None:
                break
            if cursor in cursors:
                raise ValueError(
                    "Codex returned a repeated history cursor; no partial import was saved"
                )
            cursors.add(cursor)
        after = self.call("thread/read", {"threadId": thread_id, "includeTurns": False})["thread"]
        if any(metadata.get(k) != after.get(k) for k in ("updatedAt", "path")):
            raise ValueError("Source history changed while reading; scan again")
        if after.get("status", {}).get("type") == "active":
            raise ValueError(
                "Source conversation is still active; import after the current turn finishes"
            )
        return metadata, turns

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout):
            if stream:
                stream.close()
