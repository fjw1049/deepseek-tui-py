"""Memory search — embedding, FTS tokenization, hybrid search.

Consolidates native/embedding.py, fts_tokenize.py, hybrid_search.py.
OpenAI-compatible embedding client for smart memory.
"""

from __future__ import annotations

import array
import logging
import math
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from deepseek_tui.config.models import MemorySmartConfig

logger = logging.getLogger(__name__)


def pack_embedding(vector: list[float]) -> bytes:
    return array.array("f", vector).tobytes()


def unpack_embedding(blob: bytes) -> array.array[float]:
    buf = array.array("f")
    buf.frombytes(blob)
    return buf


def cosine_similarity(a: array.array[float], b: array.array[float]) -> float:
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(len(a)):
        av = a[i]
        bv = b[i]
        dot += av * bv
        na += av * av
        nb += bv * bv
    denom = math.sqrt(na) * math.sqrt(nb)
    if denom < 1e-12:
        return 0.0
    return dot / denom


class EmbeddingClient:
    """POST ``/v1/embeddings`` (OpenAI-compatible)."""

    def __init__(self, smart: MemorySmartConfig) -> None:
        self._smart = smart
        base = (smart.embedding_base_url or "").strip().rstrip("/")
        self._base_url = base
        self._api_key = (smart.embedding_api_key or "").strip()
        self._model = smart.embedding_model or "text-embedding-3-large"
        self._dimensions = smart.embedding_dimensions
        timeout = max(5.0, smart.embedding_timeout_ms / 1000.0)
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

    @classmethod
    def from_smart_config(cls, smart: MemorySmartConfig) -> EmbeddingClient | None:
        if not smart.embedding_enabled():
            return None
        if not smart.embedding_api_key.strip() or not smart.embedding_base_url.strip():
            logger.warning("embedding_enabled but api_key/base_url missing")
            return None
        return cls(smart)

    async def close(self) -> None:
        await self._client.aclose()

    async def embed(self, text: str) -> list[float]:
        payload: dict[str, object] = {
            "model": self._model,
            "input": text.strip()[:8000],
        }
        if self._dimensions and self._dimensions > 0:
            payload["dimensions"] = self._dimensions
        resp = await self._client.post("/v1/embeddings", json=payload)
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("data") or []
        if not rows:
            raise RuntimeError("embedding API returned empty data")
        vec = rows[0].get("embedding")
        if not isinstance(vec, list) or not vec:
            raise RuntimeError("embedding API returned invalid vector")
        return [float(x) for x in vec]

    async def health_check(self) -> int:
        """Return embedding dimension count (preflight)."""
        vec = await self.embed("ping")
        return len(vec)


# ======================================================================
# From native/fts_tokenize.py
# ======================================================================

# FTS5 query builder with optional jieba for CJK.

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


# ======================================================================
# From native/hybrid_search.py
# ======================================================================

# Hybrid merge: FTS + substring candidates with RRF (no embedding required).

from typing import TypeVar

T = TypeVar("T")


def reciprocal_rank_fusion(
    ranked_lists: list[list[tuple[T, float]]],
    *,
    k: int = 60,
) -> list[tuple[T, float]]:
    scores: dict[str, float] = {}
    rows: dict[str, T] = {}
    for lst in ranked_lists:
        for rank, (row, _) in enumerate(lst):
            row_id = getattr(row, "id", str(rank))
            scores[row_id] = scores.get(row_id, 0.0) + 1.0 / (k + rank + 1)
            rows[row_id] = row
    merged = [(rows[mid], scores[mid]) for mid in scores]
    merged.sort(key=lambda x: x[1], reverse=True)
    return merged
