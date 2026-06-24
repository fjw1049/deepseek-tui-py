"""Memory seed, manifest, and native provider.

Consolidates native/seed.py, manifest.py, provider.py.
Historical conversation import for native memory.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any



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
    from deepseek_tui.memory.coordinator import CaptureInput
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


# ======================================================================
# From native/manifest.py
# ======================================================================

# Memory data-dir manifest and provenance records.

import json
import os
import time
from pathlib import Path
from typing import Any


class ManifestMismatchError(RuntimeError):
    pass


class MemoryManifest:
    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / ".metadata" / "manifest.json"

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> dict[str, Any]:
        if not self._path.is_file():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def ensure_store_binding(self, *, store_path: Path, **_kwargs: object) -> None:
        binding = {
            "backend": "sqlite",
            "store_path": str(store_path.expanduser().resolve()),
        }
        manifest = self.read()
        existing = manifest.get("store_binding")
        if isinstance(existing, dict):
            if existing.get("backend") != binding["backend"]:
                raise ManifestMismatchError(
                    f"memory data directory is bound to backend "
                    f"'{existing.get('backend')}', not '{binding['backend']}'"
                )
            if existing.get("store_path") != binding["store_path"]:
                raise ManifestMismatchError(
                    f"memory data directory is bound to store path "
                    f"'{existing.get('store_path')}', not '{binding['store_path']}'"
                )
        else:
            manifest["created_at"] = _now_iso()
            manifest["store_binding"] = binding
            manifest.setdefault("seed_runs", [])
            self.write(manifest)

    def record_seed_run(self, record: dict[str, Any]) -> None:
        manifest = self.read()
        manifest.setdefault("created_at", _now_iso())
        runs = manifest.get("seed_runs")
        if not isinstance(runs, list):
            runs = []
        runs.append({"recorded_at": _now_iso(), **record})
        manifest["seed_runs"] = runs[-20:]
        self.write(manifest)

    def write(self, manifest: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self._path)



def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ======================================================================
# From native/provider.py
# ======================================================================

# Native L0+L1+FTS memory provider.

import asyncio
import functools
import json
import logging
import time
from typing import TYPE_CHECKING, Any

from deepseek_tui.client.base import LLMClient
from deepseek_tui.memory.store import CheckpointManager
from deepseek_tui.memory.store import MemoryCleaner
from deepseek_tui.memory.search import EmbeddingClient
from deepseek_tui.memory.l0 import L0Recorder
from deepseek_tui.memory.l0 import format_l0_hits, search_l0_jsonl
from deepseek_tui.memory.l1 import L1Extractor
from deepseek_tui.memory.pipeline import L1Scheduler
from deepseek_tui.memory.l2 import SceneStore
from deepseek_tui.memory.l3 import (
    persona_paths_for_workspace,
    refresh_persona_with_llm,
)
from deepseek_tui.memory.pipeline import MemoryPipelineConfig, MemoryPipelineManager
from deepseek_tui.memory.store import MemoryStore

if TYPE_CHECKING:
    from deepseek_tui.config.models import Config

logger = logging.getLogger(__name__)

MEMORY_TOOLS_GUIDE = """<memory-tools-guide>
## 记忆工具调用指南

当注入的记忆片段不足以回答用户问题时，可主动调用 memory_search 或 conversation_search 下钻。
memory_search 用于搜索结构化 L1 记忆；conversation_search 用于查找 L0 原始对话证据。
每轮对话中二者合计最多调用 3 次。
</memory-tools-guide>"""


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
        self._pipeline: MemoryPipelineManager | None = None
        self._persona_path = data_dir / "persona.md"
        self._scenes = SceneStore(data_dir)
        self._checkpoint = CheckpointManager(data_dir)
        self._manifest = MemoryManifest(data_dir)
        self._embedder: EmbeddingClient | None = None
        self._backfill_task: asyncio.Task[int] | None = None
        self._last_scene_names: dict[str, str] = {}

    async def start(self) -> None:
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._manifest.ensure_store_binding(
            store_path=self._store.path,
            config=self._smart,
        )
        self._store.open()
        if self._smart.cleanup_on_start:
            MemoryCleaner(self._data_dir, self._store).run(
                retention_days=self._smart.retention_days
            )
        self._embedder = EmbeddingClient.from_smart_config(self._smart)
        if self._embedder is not None:
            try:
                dims = await self._embedder.health_check()
                logger.info(
                    "memory_embedding_ready model=%s dims=%d",
                    self._smart.embedding_model,
                    dims,
                )
            except Exception:
                logger.exception("memory_embedding_health_check_failed")
                await self._embedder.close()
                self._embedder = None
        model = (
            self._config.default_text_model
            or self._config.effective_provider_config().model
            or "deepseek-chat"
        )
        checkpoint = self._checkpoint.read()
        self._last_scene_names = {
            thread_id: state.last_scene_name
            for thread_id, state in checkpoint.runner_states.items()
            if state.last_scene_name
        }
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
                previous_scene_name=self._last_scene_names.get(thread_id, "无"),
            )
            if result.last_scene_name:
                self._last_scene_names[thread_id] = result.last_scene_name
                self._checkpoint.update_runner_state(
                    thread_id,
                    last_scene_name=result.last_scene_name,
                )
            if self._pipeline is not None:
                scenes = []
                for scene in result.committed_scenes or []:
                    if isinstance(scene, dict):
                        scene_copy = dict(scene)
                        scene_copy["workspace"] = workspace
                        scenes.append(scene_copy)
                self._pipeline.notify_l1_completed(
                    thread_id,
                    scenes=scenes,
                    inserted=result.inserted,
                    workspace=workspace,
                )

        async def _run_l2(
            _thread_id: str, scenes: list[dict[str, Any]]
        ) -> Any:
            workspace = ""
            if scenes:
                workspace = str(scenes[-1].get("workspace") or "")
            return await self._scenes.extract_with_llm(
                self._client,
                model=model,
                scenes=scenes,
                workspace=workspace,
                max_scenes=self._smart.l2_max_scenes,
            )

        async def _run_l3(_reason: str, workspace: str | None = None) -> None:
            scene_summary = self._scenes.navigation_markdown(
                workspace=workspace, limit=12
            )
            await refresh_persona_with_llm(
                self._client,
                self._store,
                self._persona_path,
                model=model,
                workspace=workspace,
                enabled=self._smart.l3_persona_llm_enabled,
                scene_summary=scene_summary,
            )

        self._pipeline = MemoryPipelineManager(
            data_dir=self._data_dir,
            config=MemoryPipelineConfig(
                l2_enabled=self._smart.l2_enabled,
                l2_delay_after_l1_seconds=float(
                    self._smart.l2_delay_after_l1_seconds
                ),
                l2_min_interval_seconds=float(self._smart.l2_min_interval_seconds),
                l2_max_interval_seconds=float(self._smart.l2_max_interval_seconds),
                l2_session_active_window_hours=float(
                    self._smart.l2_session_active_window_hours
                ),
                l3_persona_interval=self._smart.l3_persona_interval,
            ),
            run_l2=_run_l2,
            run_l3=_run_l3,
        )
        self._scheduler = L1Scheduler(
            every_n=self._smart.l1_every_n,
            idle_timeout_s=float(self._smart.l1_idle_timeout_seconds),
            warmup_enabled=self._smart.l1_warmup_enabled,
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
        rows = await asyncio.to_thread(self._store.iter_unembedded, limit=limit)
        done = 0
        for row_id, raw_content in rows:
            content = raw_content.strip()
            if not content:
                continue
            try:
                vec = await self._embedder.embed(content)
                await asyncio.to_thread(
                    functools.partial(
                        self._store.save_embedding,
                        row_id,
                        model=self._embedder._model,
                        vector=vec,
                    )
                )
                done += 1
            except Exception:
                logger.exception("embedding_backfill_failed id=%s", row_id)
        if done:
            logger.info("memory_embedding_backfill_done count=%d", done)
        return done

    async def stop(self) -> None:
        if self._scheduler is not None:
            await self._scheduler.stop()
        if self._pipeline is not None:
            await self._pipeline.stop()
            self._pipeline = None
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
        priority: int | None = None,
        scene_name: str = "",
        source_message_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        timestamps: list[str] | None = None,
        session_key: str | None = None,
        session_id: str = "",
        action: str = "store",
        target_ids: list[str] | None = None,
    ) -> str | None:
        text = content.strip()
        if not text:
            return None
        query_vec: list[float] | None = None
        if self._embedder is not None:
            try:
                query_vec = await self._embedder.embed(text)
                if action == "store":
                    is_dup = await asyncio.to_thread(
                        functools.partial(
                            self._store.is_semantic_duplicate,
                            query_vec,
                            workspace=workspace,
                            threshold=self._smart.embedding_dedup_threshold,
                        )
                    )
                    if is_dup:
                        return None
            except Exception:
                logger.exception("memory_embed_dedup_failed")
                query_vec = None
        mem_id = await asyncio.to_thread(
            functools.partial(
                self._store_l1_decision,
                action=action,
                content=text,
                mem_type=mem_type,
                workspace=workspace,
                thread_id=thread_id,
                confidence=confidence,
                priority=priority,
                scene_name=scene_name,
                source_message_ids=source_message_ids,
                metadata=metadata,
                timestamps=timestamps,
                session_key=session_key or thread_id,
                session_id=session_id,
                target_ids=target_ids or [],
            )
        )
        if mem_id and query_vec is not None and self._embedder is not None:
            await asyncio.to_thread(
                functools.partial(
                    self._store.save_embedding,
                    mem_id,
                    model=self._embedder._model,
                    vector=query_vec,
                )
            )
        return mem_id

    def _store_l1_decision(
        self,
        *,
        action: str,
        content: str,
        mem_type: str,
        workspace: str,
        thread_id: str | None,
        confidence: float,
        priority: int | None = None,
        scene_name: str = "",
        source_message_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        timestamps: list[str] | None = None,
        session_key: str | None = None,
        session_id: str = "",
        target_ids: list[str] | None = None,
    ) -> str | None:
        """Apply TencentDB-style L1 write decisions to the SQLite index + audit log."""
        normalized_action = action if action in {"store", "update", "merge", "skip"} else "store"
        targets = target_ids or []
        if normalized_action == "skip":
            return None
        if normalized_action in {"update", "merge"} and targets:
            self._store.delete_memories(targets)
        mem_id = self._store.insert_memory(
            content=content,
            mem_type=mem_type,
            workspace=workspace,
            thread_id=thread_id,
            confidence=confidence,
            priority=priority,
            scene_name=scene_name,
            source_message_ids=source_message_ids,
            metadata=metadata,
            timestamps=timestamps,
            session_key=session_key or thread_id,
            session_id=session_id,
            allow_duplicate=normalized_action in {"update", "merge"},
        )
        if mem_id:
            self._append_l1_record(
                record_id=mem_id,
                content=content,
                mem_type=mem_type,
                priority=priority,
                scene_name=scene_name,
                source_message_ids=source_message_ids,
                metadata=metadata,
                timestamps=timestamps,
                thread_id=thread_id,
                session_key=session_key or thread_id,
                session_id=session_id,
                workspace=workspace,
                action=normalized_action,
                target_ids=targets,
            )
        return mem_id

    def _append_l1_record(
        self,
        *,
        record_id: str,
        content: str,
        mem_type: str,
        priority: int | None,
        scene_name: str,
        source_message_ids: list[str] | None,
        metadata: dict[str, Any] | None,
        timestamps: list[str] | None,
        thread_id: str | None,
        session_key: str | None,
        session_id: str,
        workspace: str,
        action: str = "store",
        target_ids: list[str] | None = None,
    ) -> None:
        """Append a TencentDB-style L1 audit record beside the SQLite index."""
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        record = {
            "id": record_id,
            "content": content,
            "type": mem_type,
            "priority": priority if priority is not None else 100,
            "scene_name": scene_name,
            "source_message_ids": source_message_ids or [],
            "metadata": metadata or {},
            "timestamps": timestamps or [now_iso],
            "createdAt": now_iso,
            "updatedAt": now_iso,
            "sessionKey": session_key or thread_id or "",
            "sessionId": session_id,
            "workspace": workspace,
            "action": action,
            "target_ids": target_ids or [],
        }
        records_dir = self._data_dir / "records"
        records_dir.mkdir(parents=True, exist_ok=True)
        shard = time.strftime("%Y-%m-%d", time.localtime())
        with (records_dir / f"{shard}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    async def recall(
        self,
        thread_id: str,
        query: str,
        *,
        workspace: str | None = None,
    ) -> "RecallResult":
        from deepseek_tui.memory.coordinator import (
            CaptureInput, RecallResult, escape_memory_xml_tags, format_activity_time,
        )
        inject = self._smart.l1_inject_position
        if inject not in ("user", "system_volatile"):
            inject = "user"

        query_vec = await self._embed_query(query) if self._smart.hybrid_search else None
        hits = await asyncio.to_thread(
            functools.partial(
                self._store.search_memories,
                query,
                workspace=workspace,
                limit=self._smart.recall_limit,
                score_threshold=self._smart.recall_score_threshold,
                half_life_days=float(self._smart.l1_decay_half_life_days),
                hybrid=self._smart.hybrid_search,
                query_embedding=query_vec,
            )
        )
        lines: list[str] = []
        ids: list[str] = []
        for row, score in hits:
            scene = f"|{row.scene_name}" if row.scene_name else ""
            age = format_activity_time(row.created_at)
            lines.append(
                f"- [{row.type}{scene}] {escape_memory_xml_tags(row.content)} "
                f"(score={score:.2f}, {age})"
            )
            ids.append(row.id)
        l1_context = "\n".join(lines)
        if ids:
            await asyncio.to_thread(self._store.touch_recalled, ids)

        append_parts: list[str] = []
        nav = self._scenes.navigation_markdown(workspace=workspace)
        if nav:
            append_parts.append(f"<scene-navigation>\n{nav}\n</scene-navigation>")
        for persona_path in persona_paths_for_workspace(
            self._persona_path,
            workspace=workspace,
        ):
            if not persona_path.is_file():
                continue
            try:
                persona = persona_path.read_text(encoding="utf-8").strip()
            except OSError:
                persona = ""
            if persona:
                append_parts.append(f"<user-persona>\n{persona}\n</user-persona>")
        if append_parts or l1_context:
            append_parts.append(MEMORY_TOOLS_GUIDE)
        append_system = "\n\n".join(append_parts)

        if inject == "system_volatile" and l1_context:
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
        if self._pipeline is not None:
            await self._pipeline.flush_session(thread_id)

    async def search_memories(
        self,
        query: str,
        *,
        workspace: str | None = None,
        limit: int = 5,
        mem_type: str | None = None,
    ) -> str:
        query_vec = await self._embed_query(query) if self._smart.hybrid_search else None
        hits = await asyncio.to_thread(
            functools.partial(
                self._store.search_memories,
                query,
                workspace=workspace,
                limit=limit,
                score_threshold=0.0,
                half_life_days=float(self._smart.l1_decay_half_life_days),
                hybrid=self._smart.hybrid_search,
                query_embedding=query_vec,
            )
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
        exclude_thread_id: str | None = None,
        limit: int = 5,
        summarize: bool = True,
    ) -> str:
        hits = search_l0_jsonl(
            self._data_dir / "l0",
            query,
            thread_id=thread_id,
            workspace=workspace,
            exclude_thread_id=exclude_thread_id,
            limit=limit,
        )
        return format_l0_hits(hits, summarize=summarize)

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
            priority=100,
            scene_name="manual remember",
            source_message_ids=[],
            metadata={},
            timestamps=[],
            session_key=thread_id,
            session_id="",
        )
