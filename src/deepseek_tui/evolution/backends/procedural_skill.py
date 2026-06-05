"""Procedural skill evolution backend."""

from __future__ import annotations

from typing import Any, Literal

from deepseek_tui.evolution.procedural.skill_store import ProceduralSkillStore
from deepseek_tui.evolution.protocols import ApplyResult, ExperienceMutation, RiskLevel

_ACTION_TO_KIND: dict[str, str] = {
    "create": "skill_create",
    "patch": "skill_patch",
    "edit": "skill_edit",
    "delete": "skill_delete",
    "write_file": "skill_write_file",
    "remove_file": "skill_remove_file",
}


class ProceduralSkillBackend:
    name = "procedural_skill"

    def __init__(self, store: ProceduralSkillStore) -> None:
        self._store = store
        self._volatile_lines: list[str] = []

    def mutation_from_tool(
        self, tool_name: str, args: dict[str, Any]
    ) -> ExperienceMutation | None:
        if tool_name != "skill_manage":
            return None
        action = str(args.get("action", "") or "")
        kind = _ACTION_TO_KIND.get(action)
        if kind is None:
            return None
        name = str(args.get("name", "") or "")
        path = None
        if name:
            try:
                path = str(self._store.skill_root(name))
            except ValueError:
                return None
        risk: RiskLevel = "low"
        if action == "delete":
            risk = "high"
        elif action != "patch":
            risk = "medium"
        return ExperienceMutation(
            kind=kind,  # type: ignore[arg-type]
            payload=dict(args),
            target_path=path,
            risk=risk,
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
        args = mutation.payload
        action = str(args.get("action", "") or "")
        name = str(args.get("name", "") or "")
        scope = args.get("scope")
        scope_val: Literal["project", "user"] | None = None
        if scope in ("project", "user"):
            scope_val = scope
        try:
            if action == "create":
                res = self._store.create(name, str(args.get("content", "") or ""), scope=scope_val)
            elif action == "patch":
                file_path = str(args.get("file_path", "") or "").strip() or None
                res = self._store.patch(
                    name,
                    str(args.get("old_string", "") or ""),
                    str(args.get("new_string", "") or ""),
                    scope=scope_val,
                    replace_all=bool(args.get("replace_all", False)),
                    file_path=file_path,
                )
            elif action == "edit":
                res = self._store.edit(name, str(args.get("content", "") or ""), scope=scope_val)
            elif action == "delete":
                res = self._store.delete(name, scope=scope_val)
            elif action == "write_file":
                res = self._store.write_file(
                    name,
                    str(args.get("file_path", "") or ""),
                    str(args.get("file_content", "") or ""),
                    scope=scope_val,
                    category=args.get("category"),  # type: ignore[arg-type]
                )
            elif action == "remove_file":
                res = self._store.remove_file(
                    name,
                    str(args.get("file_path", "") or ""),
                    scope=scope_val,
                    category=args.get("category"),  # type: ignore[arg-type]
                )
            else:
                return ApplyResult(success=False, message=f"unknown action {action}")
        except Exception as exc:  # noqa: BLE001
            return ApplyResult(success=False, message=str(exc))
        details = {
            "message": res.message,
            "path": res.path,
        }
        if res.preview:
            details["preview"] = res.preview
        if not res.ok:
            return ApplyResult(
                success=False,
                message=res.message,
                path=res.path,
                details=details,
            )
        if action in ("create", "patch", "edit", "write_file"):
            self._volatile_lines.append(
                f"New/updated skill `{name}` — use load_skill to activate."
            )
        return ApplyResult(
            success=True,
            message=res.message,
            path=res.path,
            details=details,
        )

    def stable_prompt_block(self) -> str | None:
        return None

    def volatile_prompt_lines(self) -> list[str]:
        return list(self._volatile_lines)

    def clear_volatile(self) -> None:
        self._volatile_lines.clear()
