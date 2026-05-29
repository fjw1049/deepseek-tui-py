"""OpenAI-compatible embedding client for smart memory."""

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
