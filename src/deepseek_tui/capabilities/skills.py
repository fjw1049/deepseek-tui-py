"""Skills prompt contributions."""

from __future__ import annotations

from deepseek_tui.host.prompts import (
    FunctionPromptContributor,
    PromptContributor,
    PromptContributorContext,
)


def skills_prompt_contributors() -> list[PromptContributor]:
    return [
        FunctionPromptContributor(
            "skills",
            600,
            _skills_context,
        )
    ]


def _skills_context(ctx: PromptContributorContext) -> str | None:
    if ctx.skills_context and ctx.skills_context.strip():
        return ctx.skills_context
    return None
