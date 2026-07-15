"""WorkflowListTool tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.tools.registry import ToolContext
from deepseek_tui.tools.workflow import WorkflowListTool
from deepseek_tui.workflow.models import (
    AgentStep,
    WorkflowMeta,
    WorkflowPhase,
    WorkflowPolicy,
    WorkflowSnapshot,
    WorkflowSpec,
    make_step_output,
)
from deepseek_tui.workflow.store import checkpoint_run, create_run


def _spec() -> WorkflowSpec:
    return WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p",
                title="P",
                steps=[AgentStep(id="a1", type="agent", label="one", prompt="1")],
            )
        ],
    )


@pytest.mark.asyncio
async def test_workflow_list_returns_user_workflow_and_runs(tmp_path: Path) -> None:
    # A user-defined named workflow in the workspace.
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "my_review.json").write_text(
        '{"version":1,"meta":{"name":"my_review","description":"custom"},'
        '"policy":{},"phases":[{"id":"p","title":"P","steps":'
        '[{"id":"a","type":"agent","label":"w","prompt":"x"}]}]}'
    )

    # A run record on disk.
    spec = _spec()
    record = create_run(spec, task="review repo", workspace=tmp_path)
    checkpoint_run(
        record,
        completed_step_ids=["a1"],
        outputs={"a1": make_step_output("done")},
        snapshot=WorkflowSnapshot(name="t", description="d"),
        logs=[],
        status="completed",
        workspace=tmp_path,
    )

    tool = WorkflowListTool()
    ctx = ToolContext(working_directory=tmp_path)
    result = await tool.execute({"runs_limit": 5}, ctx)

    assert result.success
    names = [w["name"] for w in result.metadata["workflows"]]
    assert "my_review" in names  # user-defined workflow discovered
    assert "repo_review" in names  # bundled preset still discovered
    assert len(result.metadata["runs"]) == 1
    assert result.metadata["runs"][0]["run_id"] == record.run_id
    assert result.metadata["runs"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_workflow_list_empty_workspace_still_lists_presets(
    tmp_path: Path,
) -> None:
    tool = WorkflowListTool()
    ctx = ToolContext(working_directory=tmp_path)
    result = await tool.execute({}, ctx)
    assert result.success
    assert result.metadata["runs"] == []
    assert len(result.metadata["workflows"]) >= 1  # bundled presets
