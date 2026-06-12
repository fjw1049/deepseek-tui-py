"""Prompt extension contracts for capability modules."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class PromptContributorContext:
    mode: object
    workspace: Path | None
    working_set_summary: str | None = None
    skills_context: str | None = None
    locale_tag: str = "en"
    project_context_enabled: bool = True
    subagent_mandate: bool = False
    memory_enabled: bool = False
    memory_path: Path | None = None
    memory_recall: object | None = None
    curated_snapshot: str | None = None
    session_evolution_lines: list[str] | None = None
    evolution_enabled: bool = False
    workflow_guidelines: bool = False


@dataclass(frozen=True, slots=True)
class PromptContribution:
    text: str


class PromptContributor(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def order(self) -> int: ...

    def contribute(
        self,
        context: PromptContributorContext,
    ) -> PromptContribution | None: ...


@dataclass(frozen=True, slots=True)
class FunctionPromptContributor:
    id: str
    order: int
    render: Callable[[PromptContributorContext], str | None]

    def contribute(
        self,
        context: PromptContributorContext,
    ) -> PromptContribution | None:
        text = self.render(context)
        if not text:
            return None
        return PromptContribution(text=text)


def append_prompt_contributions(
    base_prompt: str,
    context: PromptContributorContext,
    contributors: Iterable[PromptContributor],
) -> str:
    prompt = base_prompt
    for contributor in sorted(contributors, key=lambda item: item.order):
        contribution = contributor.contribute(context)
        if contribution is None:
            continue
        text = contribution.text.strip()
        if not text:
            continue
        prompt += "\n\n" + text
    return prompt
