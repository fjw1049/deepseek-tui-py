"""Curated memory evolution backend."""

from __future__ import annotations

from typing import Any

from deepseek_tui.evolution.curated.store import CuratedMemoryStore, Target
from deepseek_tui.evolution.protocols import ApplyResult, ExperienceMutation


class CuratedMemoryBackend:
    name = "curated_memory"

    def __init__(self, store: CuratedMemoryStore) -> None:
        self._store = store

    def mutation_from_tool(
        self, tool_name: str, args: dict[str, Any]
    ) -> ExperienceMutation | None:
        if tool_name != "memory_curate":
            return None
        action = str(args.get("action", "") or "")
        target = str(args.get("target", "") or "")
        if action not in ("add", "replace", "remove") or target not in ("memory", "user"):
            return None
        kind = f"memory_curate_{action}"
        path = str(
            self._store.memory_path if target == "memory" else self._store.user_path
        )
        return ExperienceMutation(
            kind=kind,  # type: ignore[arg-type]
            payload=dict(args),
            target_path=path,
            risk="low",
        )

    def mutations_from_subagent_tool_results(
        self, tool_results: list[tuple[str, dict[str, Any], str]]
    ) -> list[ExperienceMutation]:
        out: list[ExperienceMutation] = []
        for name, args, _output in tool_results:
            mut = self.mutation_from_tool(name, args)
            if mut is not None:
                out.append(mut)
        return out

    async def apply(self, mutation: ExperienceMutation) -> ApplyResult:
        action = mutation.payload.get("action")
        target = mutation.payload.get("target")
        if action not in ("add", "replace", "remove") or target not in ("memory", "user"):
            return ApplyResult(success=False, message="invalid mutation payload")
        t: Target = target  # type: ignore[assignment]
        try:
            if action == "add":
                result = self._store.add(t, str(mutation.payload.get("content", "") or ""))
            elif action == "replace":
                result = self._store.replace(
                    t,
                    str(mutation.payload.get("old_text", "") or ""),
                    str(mutation.payload.get("content", "") or ""),
                )
            else:
                result = self._store.remove(
                    t, str(mutation.payload.get("old_text", "") or "")
                )
        except Exception as exc:  # noqa: BLE001
            return ApplyResult(success=False, message=str(exc))
        if not result.get("ok"):
            return ApplyResult(
                success=False,
                message=str(result.get("error", "failed")),
                details={
                    k: v
                    for k, v in result.items()
                    if k not in ("ok", "error")
                }
                or None,
            )
        return ApplyResult(
            success=True,
            message=str(result.get("message", result.get("action", "applied"))),
            path=mutation.target_path,
            details={
                k: v
                for k, v in result.items()
                if k != "ok"
            },
        )

    def stable_prompt_block(self) -> str | None:
        return self._store.stable_prompt_block()

    def volatile_prompt_lines(self) -> list[str]:
        return []
