"""Bounded, offline candidate extraction from committed human messages.

No semantic inference: retain exact short user statements with durable-language
cues for human review. Never read assistant/tool claims as user preferences.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from deepseek_tui.state.memory import MemoryStore

MAX_LOG_BYTES = 8_000_000
MAX_RECORDS = 4000
CUE = re.compile(
    r"记住|以后|始终|长期|本项目|这个项目|不要再|纠正|更正|偏好|"
    r"\b(remember|always|never|prefer|correction|this project)\b",
    re.I,
)
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


def capture_candidates(workspace: Path, transcript: Path, limit: int = 5) -> int:
    store = MemoryStore(workspace)
    created = 0
    known = {entry.fingerprint for entry in store._load().entries}
    # Most recent first, so large historical logs cannot crowd out corrections.
    for text, turn_id, seq in reversed(committed_users(transcript)):
        if not 10 <= len(text) <= 1500 or not CUE.search(text):
            continue
        if SECRET.search(text) or any(marker in text for marker in ("```", "<", ">")):
            continue
        source = {
            "type": "local_candidate",
            "transcript": str(transcript.resolve()),
            "turn_id": turn_id,
            "seq": str(seq),
            "quote_hash": hashlib.sha256(text.encode()).hexdigest(),
        }
        try:
            entry = store.write(action="propose", content=text, source=source, kind="constraint")
        except ValueError:
            continue  # Deleted/replaced statements are never resurrected.
        if entry.fingerprint not in known:
            known.add(entry.fingerprint)
            created += 1
        if created >= limit:
            break
    return created
