"""Evolution backend protocols."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

MutationKind = Literal[
    "memory_curate_add",
    "memory_curate_replace",
    "memory_curate_remove",
    "skill_create",
    "skill_patch",
    "skill_edit",
    "skill_delete",
    "skill_write_file",
    "skill_remove_file",
]

RiskLevel = Literal["low", "medium", "high"]


@dataclass(slots=True)
class ExperienceMutation:
    kind: MutationKind
    payload: dict[str, Any]
    target_path: str | None = None
    risk: RiskLevel = "medium"
    reason: str = ""
    diff_before: str | None = None
    diff_after: str | None = None


@dataclass(slots=True)
class ApplyResult:
    success: bool
    message: str = ""
    path: str | None = None
    diff: str | None = None
    details: dict[str, Any] | None = None


class EvolutionBackend(Protocol):
    name: str

    def mutation_from_tool(
        self, tool_name: str, args: dict[str, Any]
    ) -> ExperienceMutation | None: ...

    def mutations_from_subagent_tool_results(
        self, tool_results: list[tuple[str, dict[str, Any], str]]
    ) -> list[ExperienceMutation]: ...

    async def apply(self, mutation: ExperienceMutation) -> ApplyResult: ...

    def stable_prompt_block(self) -> str | None: ...

    def volatile_prompt_lines(self) -> list[str]: ...


class EvolutionPolicy(Protocol):
    def decide(
        self, mutation: ExperienceMutation, *, source: str
    ) -> Literal["auto", "propose", "deny"]: ...
