"""FTS5 query builder with optional jieba for CJK."""

from __future__ import annotations

import re

_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_RE = re.compile(r"[A-Za-z0-9_]+")


def _simple_cjk_tokens(text: str) -> list[str]:
    """Bigram + whole CJK spans when jieba is unavailable."""
    out: list[str] = []
    for span in _CJK_RE.findall(text):
        if len(span) >= 2:
            out.append(span)
        for i in range(len(span) - 1):
            bigram = span[i : i + 2]
            if bigram not in out:
                out.append(bigram)
    return out


def _latin_tokens(text: str) -> list[str]:
    return [t for t in _LATIN_RE.findall(text) if len(t) >= 2]


def _jieba_tokens(text: str) -> list[str]:
    import jieba

    return [t.strip() for t in jieba.cut_for_search(text) if len(t.strip()) >= 2]


def collect_query_tokens(query: str, *, mode: str = "auto") -> list[str]:
    """Tokenize user query for FTS5 OR clauses."""
    text = query.replace('"', " ").strip()
    if not text:
        return []
    mode = (mode or "auto").strip().lower()
    tokens: list[str] = []
    if mode in ("auto", "jieba"):
        try:
            tokens.extend(_jieba_tokens(text))
        except ImportError:
            if mode == "jieba":
                raise
            tokens.extend(_simple_cjk_tokens(text))
    elif mode == "simple":
        tokens.extend(_simple_cjk_tokens(text))
    else:
        tokens.extend(_latin_tokens(text))
    if mode in ("auto", "simple", "jieba"):
        tokens.extend(_latin_tokens(text))
    # dedupe preserve order
    seen: set[str] = set()
    unique: list[str] = []
    for t in tokens:
        if t in seen:
            continue
        seen.add(t)
        unique.append(t)
    return unique[:24]


def build_fts_query(query: str, *, mode: str = "auto") -> str:
    tokens = collect_query_tokens(query, mode=mode)
    if not tokens:
        return '""'
    return " OR ".join(f'"{t}"' for t in tokens[:12])
