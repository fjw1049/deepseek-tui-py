"""Workflow run store / resume tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from deepseek_tui.workflow.models import (
    AgentStep,
    AgentStepConfig,
    FanoutStep,
    SynthesisStep,
    WorkflowMeta,
    WorkflowPhase,
    WorkflowPolicy,
    WorkflowSnapshot,
    WorkflowSpec,
    make_step_output,
)
from deepseek_tui.workflow.store import (
    checkpoint_run,
    create_run,
    list_runs,
    load_run,
    run_path,
    safe_checkpoint_run,
    save_run,
)


def _spec() -> WorkflowSpec:
    return WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p",
                title="P",
                steps=[
                    AgentStep(id="a1", type="agent", label="one", prompt="1"),
                ],
            )
        ],
    )


def test_create_load_checkpoint(tmp_path: Path) -> None:
    record = create_run(_spec(), task="hello", workspace=tmp_path)
    assert record.run_id.startswith("wf_")
    checkpoint_run(
        record,
        completed_step_ids=["a1"],
        outputs={"a1": make_step_output("done")},
        snapshot=WorkflowSnapshot(name="t", description="d"),
        logs=["x"],
        status="interrupted",
        workspace=tmp_path,
    )
    loaded = load_run(record.run_id, workspace=tmp_path)
    assert loaded.status == "interrupted"
    assert loaded.completed_step_ids == ["a1"]
    assert loaded.task == "hello"
    assert "a1" in loaded.restored_outputs()
    runs = list_runs(workspace=tmp_path)
    assert any(r.run_id == record.run_id for r in runs)


def test_timeout_seconds_survives_create_load_roundtrip(tmp_path: Path) -> None:
    """_spec_to_dict must not silently drop per-step timeout_seconds on resume."""
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p",
                title="P",
                steps=[
                    AgentStep(
                        id="a1", type="agent", label="one", prompt="1",
                        timeout_seconds=30,
                    ),
                    FanoutStep(
                        id="f1", type="fanout",
                        agent=AgentStepConfig(prompt="x", timeout_seconds=45),
                        items=["a"],
                    ),
                    SynthesisStep(
                        id="s1", type="synthesis", label="s",
                        prompt_template="p", timeout_seconds=60,
                    ),
                ],
            )
        ],
    )
    record = create_run(spec, task="t", workspace=tmp_path)
    loaded = load_run(record.run_id, workspace=tmp_path)
    parsed = loaded.parsed_spec()
    steps = {s.id: s for s in parsed.phases[0].steps}
    assert steps["a1"].timeout_seconds == 30
    assert steps["f1"].agent.timeout_seconds == 45
    assert steps["s1"].timeout_seconds == 60


def test_save_run_atomic_replace(tmp_path: Path) -> None:
    record = create_run(_spec(), task="t", workspace=tmp_path)
    path = run_path(record.run_id, workspace=tmp_path)
    assert path.is_file()
    leftovers = list(path.parent.glob(".run.json.*.tmp"))
    assert leftovers == []
    record.task = "updated"
    save_run(record, workspace=tmp_path)
    loaded = load_run(record.run_id, workspace=tmp_path)
    assert loaded.task == "updated"


def test_save_run_leaves_prior_file_if_replace_fails(tmp_path: Path) -> None:
    record = create_run(_spec(), task="keep-me", workspace=tmp_path)
    path = run_path(record.run_id, workspace=tmp_path)
    original = path.read_text(encoding="utf-8")
    record.task = "should-not-land"

    def boom(_src: object, _dst: object) -> None:
        raise OSError("simulated replace failure")

    with patch("deepseek_tui.utils.os.replace", side_effect=boom):
        with pytest.raises(OSError, match="simulated"):
            save_run(record, workspace=tmp_path)
    assert path.read_text(encoding="utf-8") == original
    assert "keep-me" in original


def test_safe_checkpoint_run_swallows_errors(tmp_path: Path) -> None:
    record = create_run(_spec(), task="t", workspace=tmp_path)
    with patch(
        "deepseek_tui.workflow.store.save_run",
        side_effect=OSError("disk full"),
    ):
        ok = safe_checkpoint_run(
            record,
            completed_step_ids=["a1"],
            outputs={"a1": make_step_output("x")},
            snapshot=WorkflowSnapshot(name="t", description="d"),
            logs=[],
            status="running",
            workspace=tmp_path,
        )
    assert ok is False
