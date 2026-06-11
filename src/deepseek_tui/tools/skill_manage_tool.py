"""skill_manage tool — procedural skill mutations via ledger."""

from __future__ import annotations

import json
from typing import Any

from deepseek_tui.capabilities.evolution import (
    build_main_tool_evolution_response,
    evolution_decision_from_record_status,
)
from deepseek_tui.evolution.backends.procedural_skill import ProceduralSkillBackend
from deepseek_tui.evolution.constants import EVOLUTION_LEDGER_KEY, resolve_turn_evidence
from deepseek_tui.tools.base import ToolCapability, ToolResult, ToolSpec
from deepseek_tui.tools.context import ToolContext


class SkillManageTool(ToolSpec):
    def name(self) -> str:
        return "skill_manage"

    def description(self) -> str:
        return (
            "Create or update procedural skills (SKILL.md + companion files). "
            "Actions: create, patch, edit, delete, write_file, remove_file. "
            "Patch may target SKILL.md or a supporting file via file_path. "
            "Returns path and preview on mismatch. Skills are how-to; use "
            "memory_curate for durable facts."
        )

    def input_schema(self) -> dict[str, object]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "create",
                        "patch",
                        "edit",
                        "delete",
                        "write_file",
                        "remove_file",
                    ],
                },
                "name": {"type": "string"},
                "content": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "file_path": {"type": "string"},
                "file_content": {"type": "string"},
                "category": {
                    "type": "string",
                    "enum": ["references", "templates", "scripts", "assets"],
                },
                "scope": {"type": "string", "enum": ["project", "user"]},
                "replace_all": {"type": "boolean"},
            },
            "required": ["action", "name"],
        }

    def capabilities(self) -> list[ToolCapability]:
        return [ToolCapability.WRITES_FILES]

    async def execute(self, input_data: dict[str, Any], context: ToolContext) -> ToolResult:
        if context.metadata.get("evolution_review_mode"):
            backend = ProceduralSkillBackend(_store_from_context(context))
            mutation = backend.mutation_from_tool(self.name(), input_data)
            if mutation is None:
                return ToolResult(success=False, content="invalid skill_manage args")
            return ToolResult(
                success=True,
                content=json.dumps({"ok": True, "review_only": True, "kind": mutation.kind}),
            )

        ledger = context.services.optional_named(EVOLUTION_LEDGER_KEY)
        if ledger is None:
            ledger = context.metadata.get(EVOLUTION_LEDGER_KEY)
        evidence = resolve_turn_evidence(context.metadata)
        if ledger is None or evidence is None:
            return ToolResult(success=False, content="evolution ledger not available")

        store = _store_from_context(context)
        backend = ProceduralSkillBackend(store)
        mutation = backend.mutation_from_tool(self.name(), input_data)
        if mutation is None:
            return ToolResult(success=False, content="invalid skill_manage args")

        record = await ledger.submit(mutation, source="main_tool", evidence=evidence)
        decision = evolution_decision_from_record_status(record.status)
        payload = build_main_tool_evolution_response(
            record=record,
            decision=decision,
            mutation=mutation,
            error=record.reason if record.status == "failed" else None,
        )
        if record.status == "applied" and mutation.target_path:
            payload.setdefault("path", mutation.target_path)
        return ToolResult(
            success=bool(payload.get("ok")),
            content=json.dumps(payload, ensure_ascii=False),
        )


def _store_from_context(context: ToolContext):
    from deepseek_tui.evolution.constants import SKILL_STORE_KEY

    store = context.services.optional_named(SKILL_STORE_KEY)
    if store is None:
        store = context.metadata.get(SKILL_STORE_KEY)
    if store is None:
        raise RuntimeError("skill store not configured")
    return store
