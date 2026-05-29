"""Native L0+L1+FTS memory provider."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.memory.formatting import wrap_relevant_memories_system_block
from deepseek_tui.memory.native.embedding import EmbeddingClient
from deepseek_tui.memory.native.l0_recorder import L0Recorder
from deepseek_tui.memory.native.l0_search import format_l0_hits, search_l0_jsonl
from deepseek_tui.memory.native.l1_extractor import L1Extractor
from deepseek_tui.memory.native.l2_scenes import SceneStore
from deepseek_tui.memory.native.l3_persona import refresh_persona_from_store
from deepseek_tui.memory.native.scheduler import L1Scheduler
from deepseek_tui.memory.native.store import MemoryStore
from deepseek_tui.memory.provider import CaptureInput, RecallResult

if TYPE_CHECKING:
    from deepseek_tui.config.models import Config

logger = logging.getLogger(__name__)


class NativeMemoryProvider:
    def __init__(self, config: Config, client: LLMClient) -> None:
        self._config = config
        self._client = client
        self._smart = config.memory.smart
        data_dir = self._smart.resolved_data_dir()
        self._data_dir = data_dir
        self._store = MemoryStore(
            data_dir / "store" / "memory.db",
            fts_tokenizer=self._smart.fts_tokenizer,
        )
        self._l0 = L0Recorder(data_dir / "l0", self._store)
        self._l1: L1Extractor | None = None
        self._scheduler: L1Scheduler | None = None
        self._persona_path = data_dir / "persona.md"
        self._scenes = SceneStore(data_dir)
        self._embedder: EmbeddingClient | None = None
        self._backfill_task: asyncio.Task[int] | None = None

    async def start(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._store.open()
        self._embedder = EmbeddingClient.from_smart_config(self._smart)
        if self._embedder is not None:
            try:
                dims = await self._embedder.health_check()
                logger.info("memory_embedding_ready model=%s dims=%d", self._smart.embedding_model, dims)
            except Exception:
                logger.exception("memory_embedding_health_check_failed")
                await self._embedder.close()
                self._embedder = None
        model = (
            self._config.default_text_model
            or self._config.effective_provider_config().model
            or "deepseek-chat"
        )
        self._l1 = L1Extractor(
            self._client,
            self._store,
            model=model,
            confidence_min=self._smart.l1_confidence_min,
            max_per_session=self._smart.l1_max_per_session,
            insert_memory=self._insert_l1_memory,
        )

        async def _run(thread_id: str, batch: list[dict[str, Any]]) -> None:
            if self._l1 is None:
                return
            workspace = ""
            if batch:
                workspace = str(batch[-1].get("workspace") or "")
            background = self._l0.read_recent(thread_id, max_lines=40)
            bg = [m for m in background if m not in batch][-20:]
            result = await self._l1.extract_and_store(
                thread_id,
                batch,
                workspace=workspace,
                background_messages=bg,
            )
            if result.scenes:
                self._scenes.record_scenes(result.scenes, workspace=workspace)
            refresh_persona_from_store(
                self._store,
                self._persona_path,
                workspace=workspace or None,
            )

        self._scheduler = L1Scheduler(
            every_n=self._smart.l1_every_n,
            idle_timeout_s=float(self._smart.l1_idle_timeout_seconds),
            run_extraction=_run,
        )
        if self._embedder is not None and self._smart.embedding_backfill_on_start:
            import asyncio

            self._backfill_task = asyncio.create_task(
                self._backfill_embeddings(),
                name="memory-embedding-backfill",
            )

    async def _backfill_embeddings(self, *, limit: int = 200) -> int:
        """Index rows missing vectors (best-effort background)."""
        if self._embedder is None:
            return 0
        conn = self._store._conn_required()
        rows = conn.execute(
            """
            SELECT m.id, m.content FROM memories m
            LEFT JOIN memory_embeddings e ON e.memory_id = m.id
            WHERE e.memory_id IS NULL
            ORDER BY m.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        done = 0
        for row in rows:
            content = str(row["content"] or "").strip()
            if not content:
                continue
            try:
                vec = await self._embedder.embed(content)
                self._store.save_embedding(
                    str(row["id"]),
                    model=self._embedder._model,
                    vector=vec,
                )
                done += 1
            except Exception:
                logger.exception("embedding_backfill_failed id=%s", row["id"])
        if done:
            logger.info("memory_embedding_backfill_done count=%d", done)
        return done

    async def stop(self) -> None:
        if self._scheduler is not None:
            await self._scheduler.stop()
        if self._backfill_task is not None:
            self._backfill_task.cancel()
            try:
                await self._backfill_task
            except asyncio.CancelledError:
                pass
            self._backfill_task = None
        if self._embedder is not None:
            await self._embedder.close()
            self._embedder = None
        self._store.close()

    async def _embed_query(self, query: str) -> list[float] | None:
        if self._embedder is None or not query.strip():
            return None
        try:
            return await self._embedder.embed(query)
        except Exception:
            logger.exception("memory_query_embed_failed")
            return None

    async def _insert_l1_memory(
        self,
        *,
        content: str,
        mem_type: str,
        workspace: str,
        thread_id: str | None,
        confidence: float,
    ) -> str | None:
        text = content.strip()
        if not text:
            return None
        query_vec: list[float] | None = None
        if self._embedder is not None:
            try:
                query_vec = await self._embedder.embed(text)
                if self._store.is_semantic_duplicate(
                    query_vec,
                    workspace=workspace,
                    threshold=self._smart.embedding_dedup_threshold,
                ):
                    return None
            except Exception:
                logger.exception("memory_embed_dedup_failed")
                query_vec = None
        mem_id = self._store.insert_memory(
            content=text,
            mem_type=mem_type,
            workspace=workspace,
            thread_id=thread_id,
            confidence=confidence,
        )
        if mem_id and query_vec is not None and self._embedder is not None:
            self._store.save_embedding(
                mem_id,
                model=self._embedder._model,
                vector=query_vec,
            )
        return mem_id

    async def recall(
        self,
        thread_id: str,
        query: str,
        *,
        workspace: str | None = None,
    ) -> RecallResult:
        inject = self._smart.l1_inject_position
        if inject not in ("user", "system_volatile"):
            inject = "user"

        query_vec = await self._embed_query(query) if self._smart.hybrid_search else None
        hits = self._store.search_memories(
            query,
            workspace=workspace,
            limit=self._smart.recall_limit,
            score_threshold=self._smart.recall_score_threshold,
            half_life_days=float(self._smart.l1_decay_half_life_days),
            hybrid=self._smart.hybrid_search,
            query_embedding=query_vec,
        )
        lines: list[str] = []
        ids: list[str] = []
        for row, score in hits:
            lines.append(f"- ({row.type}, score={score:.2f}) {row.content}")
            ids.append(row.id)
        l1_context = "\n".join(lines)
        if ids:
            self._store.touch_recalled(ids)

        append_parts: list[str] = []
        nav = self._scenes.navigation_markdown(workspace=workspace)
        if nav:
            append_parts.append(nav)
        if self._persona_path.is_file():
            try:
                persona = self._persona_path.read_text(encoding="utf-8").strip()
            except OSError:
                persona = ""
            if persona:
                append_parts.append(f"<persona>\n{persona}\n</persona>")
        append_system = "\n\n".join(append_parts)

        if inject == "system_volatile" and l1_context:
            l1_context = wrap_relevant_memories_system_block(l1_context)
            return RecallResult(
                l1_context=l1_context,
                append_system=append_system,
                inject_position="system_volatile",
            )

        return RecallResult(
            l1_context=l1_context,
            append_system=append_system,
            inject_position="user",
        )

    async def capture(self, inp: CaptureInput) -> None:
        new_lines = self._l0.append_turn(
            inp.thread_id,
            user_text=inp.user_text,
            messages=inp.messages,
            workspace=inp.workspace,
        )
        if self._scheduler is not None and new_lines:
            self._scheduler.notify_messages(inp.thread_id, new_lines)

    async def flush_session(self, thread_id: str) -> None:
        if self._scheduler is not None:
            await self._scheduler.flush_session(thread_id)

    async def search_memories(
        self,
        query: str,
        *,
        workspace: str | None = None,
        limit: int = 5,
        mem_type: str | None = None,
    ) -> str:
        query_vec = await self._embed_query(query) if self._smart.hybrid_search else None
        hits = self._store.search_memories(
            query,
            workspace=workspace,
            limit=limit,
            score_threshold=0.0,
            half_life_days=float(self._smart.l1_decay_half_life_days),
            hybrid=self._smart.hybrid_search,
            query_embedding=query_vec,
        )
        if mem_type:
            hits = [(r, s) for r, s in hits if r.type == mem_type]
        if not hits:
            return "No matching structured memories found."
        lines = []
        for row, score in hits:
            ws = row.workspace or "global"
            lines.append(
                f"- id={row.id} type={row.type} score={score:.2f} "
                f"workspace={ws}\n  {row.content}"
            )
        return "\n\n".join(lines)

    async def search_conversations(
        self,
        query: str,
        *,
        workspace: str | None = None,
        thread_id: str | None = None,
        limit: int = 5,
    ) -> str:
        hits = search_l0_jsonl(
            self._data_dir / "l0",
            query,
            thread_id=thread_id,
            workspace=workspace,
            limit=limit,
        )
        return format_l0_hits(hits)

    async def remember_instruction(
        self,
        content: str,
        *,
        workspace: str,
        thread_id: str | None = None,
    ) -> str | None:
        """High-confidence manual L1 row (``remember`` tool dual-write)."""
        return await self._insert_l1_memory(
            content=content,
            mem_type="instruction",
            workspace=workspace,
            thread_id=thread_id,
            confidence=1.0,
        )
