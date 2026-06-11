from __future__ import annotations

import pytest

from deepseek_tui.host.contributions import ContributionRegistryError, Contributions
from deepseek_tui.host.prompts import FunctionPromptContributor


class _ToolPack:
    def __init__(self, id: str) -> None:
        self.id = id

    def tools(self, _config: object, *, mode: str) -> list[object]:
        return []


def test_contributions_collect_tool_packs_and_reject_duplicates() -> None:
    contributions = Contributions()
    pack = _ToolPack("core")

    contributions.add_tool_pack(pack)  # type: ignore[arg-type]

    assert contributions.tool_packs() == (pack,)
    with pytest.raises(ContributionRegistryError, match="tool pack"):
        contributions.add_tool_pack(_ToolPack("core"))  # type: ignore[arg-type]


def test_contributions_orders_prompt_contributors() -> None:
    contributions = Contributions()
    second = FunctionPromptContributor("second", 200, lambda _ctx: "second")
    first = FunctionPromptContributor("first", 100, lambda _ctx: "first")

    contributions.add_prompt_contributor(second)
    contributions.add_prompt_contributor(first)

    assert contributions.prompt_contributors() == (first, second)
    with pytest.raises(ContributionRegistryError, match="prompt contributor"):
        contributions.add_prompt_contributor(
            FunctionPromptContributor("first", 300, lambda _ctx: "duplicate")
        )


def test_contributions_orders_post_turn_pipelines() -> None:
    contributions = Contributions()
    first = object()
    second = object()

    contributions.add_post_turn_pipeline(
        id="second",
        owner="test",
        pipeline=second,
        order=200,
    )
    contributions.add_post_turn_pipeline(
        id="first",
        owner="test",
        pipeline=first,
        order=100,
    )

    pipelines = contributions.post_turn_pipelines()
    assert [entry.id for entry in pipelines] == ["first", "second"]
    assert [entry.pipeline for entry in pipelines] == [first, second]
    with pytest.raises(ContributionRegistryError, match="post-turn pipeline"):
        contributions.add_post_turn_pipeline(
            id="first",
            owner="test",
            pipeline=object(),
        )


def test_contributions_exposes_nested_registries() -> None:
    contributions = Contributions()

    assert contributions.services.typed_keys() == ()
    assert contributions.lifecycle.registrations() == ()
    assert contributions.surfaces.routes() == ()
