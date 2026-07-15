"""Loop runtime + evaluate_loop_until coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_tui.workflow.models import (
    AgentStep,
    AgentStepConfig,
    FanoutStep,
    LoopStep,
    LoopUntil,
    StepOutput,
    SynthesisStep,
    WorkflowMeta,
    WorkflowPhase,
    WorkflowPolicy,
    WorkflowSpec,
    evaluate_loop_until,
    make_step_output,
)
from deepseek_tui.workflow.runtime import run_workflow
from tests.workflow.test_runtime_fake_runner import FakeRunner


def test_evaluate_loop_until_structured_true() -> None:
    body = [AgentStep(id="chk", type="agent", label="c", prompt="x")]
    outs = {"chk": make_step_output("ok", {"done": True})}
    assert evaluate_loop_until(
        LoopUntil(path="$.done", equals=True), outputs=outs, body=body
    )


def test_evaluate_loop_until_structured_none_falls_back_to_json_text() -> None:
    body = [AgentStep(id="chk", type="agent", label="c", prompt="x")]
    outs = {"chk": make_step_output('{"done": true}', None)}
    assert evaluate_loop_until(
        LoopUntil(path="$.done", equals=True), outputs=outs, body=body
    )


def test_evaluate_loop_until_missing_path_is_false() -> None:
    body = [AgentStep(id="chk", type="agent", label="c", prompt="x")]
    outs = {"chk": make_step_output("ok", {"other": 1})}
    assert not evaluate_loop_until(
        LoopUntil(path="$.done", equals=True), outputs=outs, body=body
    )


def test_evaluate_loop_until_empty_body_is_false() -> None:
    outs = {"chk": make_step_output("ok", {"done": True})}
    assert not evaluate_loop_until(
        LoopUntil(path="$.done", equals=True), outputs=outs, body=[]
    )


def test_evaluate_loop_until_python_equality_accepts_1_as_true() -> None:
    """Documented tolerance: LLM may return done=1."""
    body = [AgentStep(id="chk", type="agent", label="c", prompt="x")]
    outs = {"chk": make_step_output("ok", {"done": 1})}
    assert evaluate_loop_until(
        LoopUntil(path="$.done", equals=True), outputs=outs, body=body
    )


@pytest.mark.asyncio
async def test_loop_until_false_runs_full_max_rounds() -> None:
    runner = FakeRunner(
        structured_by_label={"check": {"done": False}},
    )
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    LoopStep(
                        id="lp",
                        type="loop",
                        max_rounds=3,
                        until=LoopUntil(path="$.done", equals=True),
                        steps=[
                            AgentStep(
                                id="chk",
                                type="agent",
                                label="check",
                                prompt="round {{round}}",
                                output_schema={"type": "object"},
                            )
                        ],
                    )
                ],
            )
        ],
    )
    await run_workflow(spec, runner=runner)
    assert runner.calls == ["check", "check", "check"]
    assert any("round 3" in p for p in runner.prompts)


@pytest.mark.asyncio
async def test_loop_until_none_runs_full_max_rounds() -> None:
    runner = FakeRunner()
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    LoopStep(
                        id="lp",
                        type="loop",
                        max_rounds=2,
                        until=None,
                        steps=[
                            AgentStep(
                                id="chk",
                                type="agent",
                                label="check",
                                prompt="r{{round}}",
                            )
                        ],
                    )
                ],
            )
        ],
    )
    await run_workflow(spec, runner=runner)
    assert len(runner.calls) == 2


@pytest.mark.asyncio
async def test_loop_multi_step_body_order() -> None:
    runner = FakeRunner()
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    LoopStep(
                        id="lp",
                        type="loop",
                        max_rounds=2,
                        until=None,
                        steps=[
                            AgentStep(id="a", type="agent", label="first", prompt="1"),
                            AgentStep(id="b", type="agent", label="second", prompt="2"),
                        ],
                    )
                ],
            )
        ],
    )
    await run_workflow(spec, runner=runner)
    assert runner.calls == ["first", "second", "first", "second"]


@pytest.mark.asyncio
async def test_loop_with_fanout_body() -> None:
    runner = FakeRunner()
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(concurrency=2),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    LoopStep(
                        id="lp",
                        type="loop",
                        max_rounds=2,
                        until=None,
                        steps=[
                            FanoutStep(
                                id="fan",
                                type="fanout",
                                items=["x", "y"],
                                agent=AgentStepConfig(
                                    label_template="f {{item}}",
                                    prompt_template="look {{item}} r{{round}}",
                                ),
                            )
                        ],
                    )
                ],
            )
        ],
    )
    await run_workflow(spec, runner=runner)
    # 2 rounds × 2 items
    assert len(runner.calls) == 4
    assert set(runner.calls) == {"f x", "f y"}


@pytest.mark.asyncio
async def test_loop_output_feeds_synthesis() -> None:
    class LoopThenDone(FakeRunner):
        def __init__(self) -> None:
            super().__init__()
            self.n = 0

        async def run(self, **kwargs: object) -> StepOutput | None:
            label = str(kwargs.get("label"))
            self.calls.append(label)
            self.prompts.append(str(kwargs.get("prompt")))
            if label == "check":
                self.n += 1
                return make_step_output(f"note-{self.n}", {"done": True, "v": self.n})
            return make_step_output(f"syn:{kwargs.get('prompt')}")

    runner = LoopThenDone()
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    LoopStep(
                        id="lp",
                        type="loop",
                        max_rounds=3,
                        until=LoopUntil(path="$.done", equals=True),
                        steps=[
                            AgentStep(
                                id="chk",
                                type="agent",
                                label="check",
                                prompt="go",
                                output_schema={"type": "object"},
                            )
                        ],
                    ),
                    SynthesisStep(
                        id="syn",
                        type="synthesis",
                        label="merge",
                        prompt_template="OUT={{outputs.lp}}",
                    ),
                ],
            )
        ],
    )
    result = await run_workflow(spec, runner=runner)
    assert runner.n == 1
    assert any(p.startswith("OUT=") and "note-1" in p for p in runner.prompts)
    assert "syn" in result.result


@pytest.mark.asyncio
async def test_loop_resume_restarts_from_round_one() -> None:
    """Interrupted loop has no persisted round — body restarts at round 1."""
    runner = FakeRunner(
        structured_by_label={"check": {"done": False}},
    )
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    LoopStep(
                        id="lp",
                        type="loop",
                        max_rounds=2,
                        until=LoopUntil(path="$.done", equals=True),
                        steps=[
                            AgentStep(
                                id="chk",
                                type="agent",
                                label="check",
                                prompt="round {{round}}",
                                output_schema={"type": "object"},
                            )
                        ],
                    )
                ],
            )
        ],
    )
    # Simulate resume where body step was already marked completed mid-loop.
    result = await run_workflow(
        spec,
        runner=runner,
        initial_outputs={"chk": make_step_output("old", {"done": False})},
        skip_step_ids={"chk"},
    )
    assert "lp" in result.result
    # Still runs full 2 rounds despite chk being in skip_step_ids.
    assert runner.calls == ["check", "check"]
    assert any("round 1" in p for p in runner.prompts)


@pytest.mark.asyncio
async def test_fanout_resume_skips_completed_items() -> None:
    """Mid-fanout checkpoint should skip already finished items on resume."""
    runner = FakeRunner()
    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(concurrency=2),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    FanoutStep(
                        id="fan",
                        type="fanout",
                        items=["a", "b", "c"],
                        agent=AgentStepConfig(
                            label_template="f {{item}}",
                            prompt_template="look {{item}}",
                        ),
                    )
                ],
            )
        ],
    )
    result = await run_workflow(
        spec,
        runner=runner,
        initial_outputs={
            "fan:a": make_step_output("done:a"),
            "fan:b": make_step_output("done:b"),
        },
    )
    # Only missing item "c" should spawn.
    assert runner.calls == ["f c"]
    assert isinstance(result.result, dict)
    assert "fan" in result.result
    assert "fan:a" in result.result or "a:" in str(result.result)


@pytest.mark.asyncio
async def test_fanout_checkpoints_each_item(tmp_path: Path) -> None:
    from deepseek_tui.workflow.store import create_run, load_run, safe_checkpoint_run

    runner = FakeRunner()
    seen_keys: list[str] = []

    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(concurrency=1),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    FanoutStep(
                        id="fan",
                        type="fanout",
                        items=["x", "y"],
                        agent=AgentStepConfig(
                            label_template="f {{item}}",
                            prompt_template="look {{item}}",
                        ),
                    )
                ],
            )
        ],
    )
    record = create_run(spec, task="t", workspace=tmp_path)

    def on_checkpoint(ctx_obj: object, snap: object, logs: object) -> None:
        from deepseek_tui.workflow.models import WorkflowRunContext, WorkflowSnapshot

        assert isinstance(ctx_obj, WorkflowRunContext)
        assert isinstance(snap, WorkflowSnapshot)
        for key in ctx_obj.outputs:
            if key.startswith("fan:") and key not in seen_keys:
                seen_keys.append(key)
        safe_checkpoint_run(
            record,
            completed_step_ids=list(ctx_obj.completed_step_ids),
            outputs=dict(ctx_obj.outputs),
            snapshot=snap,
            logs=list(logs) if isinstance(logs, list) else [],
            status="running",
            workspace=tmp_path,
        )

    await run_workflow(spec, runner=runner, on_checkpoint=on_checkpoint)
    # Progressive item keys appear before the whole fan step completes.
    assert seen_keys == ["fan:x", "fan:y"] or set(seen_keys) >= {"fan:x", "fan:y"}
    loaded = load_run(record.run_id, workspace=tmp_path)
    assert "fan:x" in loaded.outputs or "fan" in loaded.completed_step_ids


@pytest.mark.asyncio
async def test_checkpoint_callback_error_does_not_abort_run() -> None:
    runner = FakeRunner()
    calls = {"n": 0}

    def bad_checkpoint(*_a: object, **_k: object) -> None:
        calls["n"] += 1
        raise OSError("disk full")

    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    AgentStep(id="a1", type="agent", label="one", prompt="1"),
                ],
            )
        ],
    )
    result = await run_workflow(
        spec, runner=runner, on_checkpoint=bad_checkpoint
    )
    assert runner.calls == ["one"]
    assert result.result is not None
    assert calls["n"] >= 1
