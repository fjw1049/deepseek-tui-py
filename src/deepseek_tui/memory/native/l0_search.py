"""L0 JSONL conversation search (keyword / BM25)."""

from __future__ import annotations

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


def format_l0_hits(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "No matching conversation lines found."
    lines: list[str] = []
    for hit in hits:
        lines.append(
            f"[thread={hit['thread_id']} line={hit['line']} role={hit['role']} "
            f"score={hit.get('score', 0)}]\n  {hit.get('excerpt', hit['content'])}"
        )
    return "\n\n".join(lines)
