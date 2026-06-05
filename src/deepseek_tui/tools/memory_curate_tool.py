"""memory_curate tool — curated MEMORY.md / USER.md mutations via ledger."""

from __future__ import annotations

import json
from typing import Any

from deepseek_tui.evolution.backends.curated_memory import CuratedMemoryBackend
from deepseek_tui.evolution.constants import (
    EVOLUTION_LEDGER_KEY,
    resolve_turn_evidence,
)
from deepseek_tui.evolution.tool_response import (
    build_evolution_tool_response,
    decision_from_record_status,
)
from deepseek_tui.tools.base import ToolCapability, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext


class MemoryCurateTool(ToolSpec):
    def name(self) -> str:
        return "memory_curate"

    def description(self) -> str:
        return (
            "Curate durable agent notes (target=memory) or user profile facts "
            "(target=user) in §-separated curated files. Actions: add, replace, remove. "
            "Returns current_entries and usage; if at capacity, replace or remove first. "
            "Use conversation_search for task progress, not curated memory."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "replace", "remove"]},
                "target": {"type": "string", "enum": ["memory", "user"]},
                "content": {"type": "string"},
                "old_text": {"type": "string"},
            },
            "required": ["action", "target"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        store = _store_from_context(context)
        if context.metadata.get("evolution_review_mode"):
            backend = CuratedMemoryBackend(store)
            mutation = backend.mutation_from_tool(self.name(), input_data)
            if mutation is None:
                return ToolResult(success=False, content="invalid memory_curate args")
            return ToolResult(
                success=True,
                content=json.dumps({"ok": True, "review_only": True, "kind": mutation.kind}),
            )

        ledger = context.metadata.get(EVOLUTION_LEDGER_KEY)
        evidence = resolve_turn_evidence(context.metadata)
        if ledger is None or evidence is None:
            return ToolResult(success=False, content="evolution ledger not available")

        backend = CuratedMemoryBackend(store)
        mutation = backend.mutation_from_tool(self.name(), input_data)
        if mutation is None:
            return ToolResult(success=False, content="invalid memory_curate args")

        record = await ledger.submit(mutation, source="main_tool", evidence=evidence)
        decision = decision_from_record_status(record.status)
        payload = build_evolution_tool_response(
            record=record,
            decision=decision,
            mutation=mutation,
            store=store,
            error=record.reason if record.status == "failed" else None,
        )
        return ToolResult(
            success=bool(payload.get("ok")),
            content=json.dumps(payload, ensure_ascii=False),
        )


def _store_from_context(context: ToolContext):
    from deepseek_tui.evolution.constants import CURATED_MEMORY_STORE_KEY

    store = context.metadata.get(CURATED_MEMORY_STORE_KEY)
    if store is None:
        raise RuntimeError("curated memory store not configured")
    return store
