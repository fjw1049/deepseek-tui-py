"""L0 memory layer — raw turn recording, search, summarization.

Consolidates native/l0_*.py. L0 JSONL incremental recorder.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from deepseek_tui.memory.coordinator import sanitize_memory_text, strip_code_blocks
from deepseek_tui.memory.store import MemoryStore

_MIN_CONTENT_LEN = 4
_MAX_LINE_BYTES = 32_000


def _should_capture_l0(content: str) -> bool:
    text = sanitize_memory_text(content)
    if len(text) < _MIN_CONTENT_LEN:
        return False
    if len(text.encode("utf-8")) > _MAX_LINE_BYTES:
        return False
    return True


class L0Recorder:
    def __init__(self, l0_dir: Path, store: MemoryStore) -> None:
        self._l0_dir = l0_dir
        self._store = store
        self._l0_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, thread_id: str) -> Path:
        safe = thread_id.replace("/", "_")
        return self._l0_dir / f"{safe}.jsonl"

    def append_turn(
        self,
        thread_id: str,
        *,
        user_text: str,
        messages: list[dict[str, Any]],
        workspace: str,
    ) -> list[dict[str, Any]]:
        """Append new L0 lines; return messages eligible for L1 extraction.

        Tool role messages are stored in L0 for audit/conversation_search but
        excluded from the returned list so they don't enter L1 extraction.
        """
        path = self._path_for(thread_id)
        last_ts, last_count = self._store.get_l0_cursor(thread_id)
        all_lines: list[dict[str, Any]] = []
        l1_eligible: list[dict[str, Any]] = []
        now_ms = int(time.time() * 1000)

        if _should_capture_l0(user_text):
            clean_user_text = sanitize_memory_text(user_text)
            record = {
                "id": f"msg_{now_ms}_user",
                "role": "user",
                "content": clean_user_text,
                "timestamp": now_ms,
                "workspace": workspace,
                "thread_id": thread_id,
                "sessionKey": thread_id,
                "sessionId": "",
                "recordedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            all_lines.append(record)
            l1_eligible.append(record)

        for msg in messages:
            role = str(msg.get("role", ""))
            if role not in ("assistant", "tool"):
                continue
            content = str(msg.get("content", "") or "")
            if not _should_capture_l0(content):
                continue
            msg_ts = msg.get("timestamp") or now_ms
            if isinstance(msg_ts, (int, float)) and int(msg_ts) <= last_ts:
                continue
            clean_content = sanitize_memory_text(content)
            record = {
                "id": msg.get("id") or f"msg_{now_ms}_{role}",
                "role": role,
                "content": clean_content,
                "timestamp": msg_ts,
                "workspace": workspace,
                "thread_id": thread_id,
                "sessionKey": thread_id,
                "sessionId": "",
                "recordedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            all_lines.append(record)
            if role != "tool":
                stripped = strip_code_blocks(clean_content)
                if stripped:
                    l1_record = {**record, "content": stripped}
                    l1_eligible.append(l1_record)
                else:
                    l1_eligible.append(record)

        if not all_lines:
            return []

        with path.open("a", encoding="utf-8") as handle:
            for line in all_lines:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")

        self._store.set_l0_cursor(
            thread_id,
            last_timestamp_ms=now_ms,
            last_message_count=last_count + len(all_lines),
        )
        return l1_eligible

    def read_recent(self, thread_id: str, *, max_lines: int = 80) -> list[dict[str, Any]]:
        path = self._path_for(thread_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        out: list[dict[str, Any]] = []
        for raw in lines[-max_lines:]:
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return out


# L0 JSONL conversation search (keyword / BM25).

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

K1 = 1.5
B = 0.75
EXCERPT_CHARS = 320


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def search_l0_jsonl(
    l0_dir: Path,
    query: str,
    *,
    thread_id: str | None = None,
    workspace: str | None = None,
    exclude_thread_id: str | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """BM25 search over ``l0/*.jsonl`` lines."""
    terms = _tokenize(query)
    if not terms:
        return []

    docs: list[dict[str, Any]] = []
    if not l0_dir.is_dir():
        return []

    paths = sorted(l0_dir.glob("*.jsonl"))
    if thread_id:
        safe = thread_id.replace("/", "_")
        paths = [p for p in paths if p.stem == safe or p.name == f"{safe}.jsonl"]

    for path in paths:
        tid = path.stem
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for idx, raw in enumerate(lines):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if workspace and row.get("workspace") and row["workspace"] != workspace:
                continue
            content = str(row.get("content", "") or "")
            if not content.strip():
                continue
            if exclude_thread_id and tid == exclude_thread_id.replace("/", "_"):
                continue
            docs.append(
                {
                    "thread_id": tid,
                    "line": idx,
                    "role": row.get("role", "?"),
                    "content": content,
                    "timestamp": row.get("timestamp"),
                }
            )

    if not docs:
        return []

    doc_lens = [len(_tokenize(d["content"])) or 1 for d in docs]
    avgdl = sum(doc_lens) / len(doc_lens)
    df: Counter[str] = Counter()
    doc_term_freqs: list[Counter[str]] = []
    for doc in docs:
        tf = Counter(_tokenize(doc["content"]))
        doc_term_freqs.append(tf)
        for t in tf:
            df[t] += 1

    n_docs = len(docs)
    scores: list[tuple[float, int]] = []
    for i, tf in enumerate(doc_term_freqs):
        score = 0.0
        dl = doc_lens[i]
        for term in terms:
            if term not in df:
                continue
            freq = tf.get(term, 0)
            if freq == 0:
                continue
            idf = math.log((n_docs - df[term] + 0.5) / (df[term] + 0.5) + 1.0)
            score += idf * (freq * (K1 + 1)) / (freq + K1 * (1 - B + B * dl / avgdl))
        scores.append((score, i))

    scores.sort(key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    for score, idx in scores[:limit]:
        if score <= 0:
            continue
        doc = dict(docs[idx])
        doc["score"] = round(score, 3)
        text = doc["content"]
        if len(text) > EXCERPT_CHARS:
            doc["excerpt"] = text[:EXCERPT_CHARS] + "…"
        else:
            doc["excerpt"] = text
        out.append(doc)
    return out


def format_l0_hits(hits: list[dict[str, Any]], *, summarize: bool = False) -> str:
    if not hits:
        return "No matching conversation lines found."
    if summarize:

        return summarize_l0_hits(hits)
    lines: list[str] = []
    for hit in hits:
        lines.append(
            f"[thread={hit['thread_id']} line={hit['line']} role={hit['role']} "
            f"score={hit.get('score', 0)}]\n  {hit.get('excerpt', hit['content'])}"
        )
    return "\n\n".join(lines)


# Summarized L0 conversation hit formatting.

from collections import defaultdict
from typing import Any


def summarize_l0_hits(hits: list[dict[str, Any]]) -> str:
    """Compact digest grouped by thread — avoids raw excerpt pile-ups."""
    if not hits:
        return "No matching conversation lines found."

    by_thread: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for hit in hits:
        by_thread[str(hit.get("thread_id", "?"))].append(hit)

    sections: list[str] = []
    for thread_id, thread_hits in sorted(by_thread.items()):
        lines: list[str] = [f"## Thread `{thread_id}` ({len(thread_hits)} hit(s))"]
        for hit in thread_hits:
            role = hit.get("role", "?")
            score = hit.get("score", 0)
            excerpt = str(hit.get("excerpt") or hit.get("content") or "")
            one_line = " ".join(excerpt.split())
            if len(one_line) > 160:
                one_line = one_line[:159] + "…"
            lines.append(
                f"- line {hit.get('line', '?')} [{role}] score={score}: {one_line}"
            )
        sections.append("\n".join(lines))
    return "\n\n".join(sections)
