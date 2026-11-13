"""Validate provenance of legacy candidates; no automatic extraction."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

MAX_LOG_BYTES = 8_000_000
MAX_RECORDS = 4000
SECRET = re.compile(
    r"sk-[\w-]{12,}|-----BEGIN .*PRIVATE KEY|"
    r"(?:api[_ -]?key|token|password|secret|密码|密钥)\s*[:=：]\s*\S+",
    re.I,
)


def committed_users(path: Path) -> list[tuple[str, str, int]]:
    """Replay live records, retaining original user evidence across compaction."""
    from deepseek_tui.engine.context_pressure import extract_user_query_text

    if path.is_symlink() or path.stat().st_size > MAX_LOG_BYTES:
        raise ValueError("Transcript exceeds local capture limits or is a symlink")
    records = []
    with path.open(encoding="utf-8") as stream:
        for count, line in enumerate(stream):
            if count >= MAX_RECORDS:
                raise ValueError("Transcript exceeds capture record limit")
            try:
                record = json.loads(line)
            except ValueError:
                continue  # A torn append is not evidence.
            if record["type"] == "rollback":
                records = [item for item in records if item["seq"] <= record["to_seq"]]
            else:
                records.append(record)
    messages = []
    users = {}
    for record in records:
        messages[record["keep"] :] = record["messages"]
        if record["type"] != "commit":
            continue
        for message in messages:
            # Legacy messages with unknown provenance are deliberately not mined.
            if message.get("role") != "user" or message.get("origin") != "real_user":
                continue
            text = "\n".join(
                block["text"] for block in message.get("content", []) if block.get("type") == "text"
            )
            text = extract_user_query_text(text)
            if text not in users:
                users[text] = (text, record.get("turn_id") or "", record["seq"])
    return list(users.values())


def source_is_live(source: dict[str, str]) -> bool:
    try:
        return any(
            hashlib.sha256(text.encode()).hexdigest() == source.get("quote_hash")
            and str(seq) == source.get("seq")
            and turn_id == source.get("turn_id")
            for text, turn_id, seq in committed_users(Path(source["transcript"]))
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False
