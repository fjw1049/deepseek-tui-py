"""Tests for DAG compile, ready-set join, dynamic mutations, and support helpers."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from deepseek_tui.workflow.dag import CompiledGraph, compile_phases_to_graph, compile_workflow_graph
from deepseek_tui.workflow.dynamic import apply_decision_actions
from deepseek_tui.workflow.helpers import list_helpers, run_support_helper
from deepseek_tui.workflow.models import (
    AgentStep,
    AgentStepConfig,
    DynamicStep,
    DynamicBudget,
    DynamicPermissions,
    FanoutStep,
    WorkflowMeta,
    WorkflowPhase,
    WorkflowPolicy,
    WorkflowRunContext,
    WorkflowSpec,
    adaptive_workflow_spec,
    make_step_output,
    parse_workflow_spec,
)
from deepseek_tui.workflow.runtime import run_workflow
from deepseek_tui.workflow.store import create_run, load_run


class FakeRunner:
    def __init__(self, replies: dict[str, Any] | None = None) -> None:
        self.replies = replies or {}
        self.calls: list[str] = []

    async def run(self, *, prompt: str, label: str, **kwargs: Any) -> Any:
        self.calls.append(label)
        raw = self.replies.get(label, self.replies.get("*", "ok"))
        if isinstance(raw, Exception):
            raise raw
        if isinstance(raw, dict):
            return make_step_output(json.dumps(raw), raw)
        return make_step_output(str(raw))


def test_phases_compile_to_sequential_dag() -> None:
    phases = [
        WorkflowPhase(
            id="p1",
            title="P1",
            steps=[
                AgentStep(id="a", type="agent", label="a", prompt="1"),
                AgentStep(id="b", type="agent", label="b", prompt="2"),
            ],
        )
    ]
    g = compile_phases_to_graph(phases)
    assert set(g.nodes) == {"a", "b"}
    assert g.predecessors["b"] == {"a"}
    assert g.ready_ids(set(), set(), set()) == ["a"]
    assert g.ready_ids({"a"}, set(), set()) == ["b"]


def test_v2_diamond_join_parses() -> None:
    spec = parse_workflow_spec(
        {
            "version": 2,
            "meta": {"name": "join", "description": "A,B→C"},
            "policy": {},
            "graph": {
                "nodes": [
                    {"id": "a", "type": "agent", "label": "a", "prompt": "A"},
                    {"id": "b", "type": "agent", "label": "b", "prompt": "B"},
                    {
                        "id": "c",
                        "type": "reduce",
                        "label": "join",
                        "from": ["a", "b"],
                        "prompt_template": "A={{outputs.a}} B={{outputs.b}}",
                    },
                ],
                "edges": [
                    {"from": "a", "to": "c"},
                    {"from": "b", "to": "c"},
                ],
            },
        }
    )
    g = compile_workflow_graph(spec)
    assert g.predecessors["c"] == {"a", "b"}
    ready = set(g.ready_ids(set(), set(), set()))
    assert ready == {"a", "b"}
    assert set(g.ready_ids({"a", "b"}, set(), set())) == {"c"}


@pytest.mark.asyncio
async def test_parallel_ready_then_reduce() -> None:
    spec = parse_workflow_spec(
        {
            "version": 2,
            "meta": {"name": "join", "description": "A,B→C"},
            "policy": {"concurrency": 2},
            "graph": {
                "nodes": [
                    {"id": "a", "type": "agent", "label": "worker-a", "prompt": "A"},
                    {"id": "b", "type": "agent", "label": "worker-b", "prompt": "B"},
                    {
                        "id": "c",
                        "type": "reduce",
                        "label": "joiner",
                        "from": ["a", "b"],
                        "prompt_template": "{{outputs.a}}|{{outputs.b}}",
                    },
                ],
                "edges": [
                    {"from": "a", "to": "c"},
                    {"from": "b", "to": "c"},
                ],
            },
        }
    )
    runner = FakeRunner(
        {"worker-a": "A-out", "worker-b": "B-out", "joiner": "merged"}
    )
    result = await run_workflow(spec, runner=runner, task="t")
    assert "worker-a" in runner.calls and "worker-b" in runner.calls
    assert "joiner" in runner.calls
    assert result.snapshot.done_count >= 3


@pytest.mark.asyncio
async def test_fail_fast_skips_successors() -> None:
    spec = parse_workflow_spec(
        {
            "version": 2,
            "meta": {"name": "ff", "description": "fail fast"},
            "policy": {"on_error": "fail_fast"},
            "graph": {
                "nodes": [
                    {"id": "a", "type": "agent", "label": "boom", "prompt": "x"},
                    {"id": "b", "type": "agent", "label": "later", "prompt": "y"},
                ],
                "edges": [{"from": "a", "to": "b"}],
            },
        }
    )

    class Boom(FakeRunner):
        async def run(self, *, prompt: str, label: str, **kwargs: Any) -> Any:
            if label == "boom":
                raise RuntimeError("nope")
            return await super().run(prompt=prompt, label=label, **kwargs)

    from deepseek_tui.workflow.models import WorkflowFailedError

    with pytest.raises(WorkflowFailedError):
        await run_workflow(spec, runner=Boom({}))


def test_support_helpers_allowlist() -> None:
    assert "dedupe_findings" in list_helpers()
    inputs = {
        "a": make_step_output("dup\nkeep", None),
        "b": make_step_output("DUP\nnew", None),
    }
    out = run_support_helper("dedupe_findings", inputs, {})
    assert "keep" in out.text
    assert "new" in out.text
    # "dup"/"DUP" collapse case-insensitively
    assert out.structured["count"] == 2


def test_dynamic_spawn_mutation() -> None:
    from deepseek_tui.workflow.dag import build_adjacency

    step = DynamicStep(
        id="orch",
        type="dynamic",
        budget=DynamicBudget(),
        permissions=DynamicPermissions(
            actions=["spawn", "stop"],
        ),
    )
    graph = build_adjacency(
        {
            "orch": step,
            "seed": AgentStep(id="seed", type="agent", label="seed", prompt="s"),
        },
        [],
    )
    # Attach seed as completed so spawn after seed is valid
    ctx = WorkflowRunContext(task="t", completed_step_ids=["seed"])
    ctx.outputs["seed"] = make_step_output("seeded")
    flags = apply_decision_actions(
        step,
        {
            "actions": [
                {
                    "action": "spawn",
                    "id": "dyn/orch/r1/worker",
                    "label": "worker",
                    "prompt": "inspect more",
                    "after": ["seed"],
                }
            ]
        },
        graph=graph,
        ctx=ctx,
        round_idx=1,
        parent_id="orch",
    )
    assert "dyn/orch/r1/worker" in graph.nodes
    assert "dyn/orch/r1/worker" in ctx.generated_node_ids
    assert flags["new_node_ids"] == ["dyn/orch/r1/worker"]
    assert graph.predecessors["dyn/orch/r1/worker"] == {"seed"}


def test_dynamic_default_after_is_ready_now() -> None:
    from deepseek_tui.workflow.dag import build_adjacency

    step = DynamicStep(
        id="orch",
        type="dynamic",
        permissions=DynamicPermissions(actions=["spawn"]),
    )
    graph = build_adjacency({"orch": step}, [])
    ctx = WorkflowRunContext(task="t")
    apply_decision_actions(
        step,
        {
            "actions": [
                {
                    "action": "spawn",
                    "id": "w1",
                    "label": "worker1",
                    "prompt": "go",
                }
            ]
        },
        graph=graph,
        ctx=ctx,
        round_idx=1,
        parent_id="orch",
    )
    assert graph.predecessors["w1"] == set()


def test_dynamic_rejects_dangling_after() -> None:
    from deepseek_tui.workflow.dag import build_adjacency
    from deepseek_tui.workflow.models import WorkflowValidationError

    step = DynamicStep(
        id="orch",
        type="dynamic",
        permissions=DynamicPermissions(actions=["spawn"]),
    )
    graph = build_adjacency({"orch": step}, [])
    ctx = WorkflowRunContext(task="t")
    with pytest.raises(WorkflowValidationError, match="unknown predecessor"):
        apply_decision_actions(
            step,
            {
                "actions": [
                    {
                        "action": "spawn",
                        "id": "w1",
                        "label": "worker1",
                        "prompt": "go",
                        "after": ["missing"],
                    }
                ]
            },
            graph=graph,
            ctx=ctx,
            round_idx=1,
            parent_id="orch",
        )


def test_dynamic_replan_removes_pending_nodes() -> None:
    from deepseek_tui.workflow.dag import build_adjacency

    step = DynamicStep(
        id="orch",
        type="dynamic",
        permissions=DynamicPermissions(actions=["spawn", "replan"]),
    )
    graph = build_adjacency({"orch": step}, [])
    ctx = WorkflowRunContext(task="t")
    apply_decision_actions(
        step,
        {
            "actions": [
                {"action": "spawn", "id": "w1", "label": "w1", "prompt": "a"},
                {"action": "spawn", "id": "w2", "label": "w2", "prompt": "b"},
            ]
        },
        graph=graph,
        ctx=ctx,
        round_idx=1,
        parent_id="orch",
    )
    ctx.completed_step_ids.append("w1")
    ctx.outputs["w1"] = make_step_output("kept")
    flags = apply_decision_actions(
        step,
        {"actions": [{"action": "replan"}]},
        graph=graph,
        ctx=ctx,
        round_idx=2,
        parent_id="orch",
    )
    assert flags["replan"] is True
    assert "w2" in flags["replan_dropped"]
    assert "w2" not in graph.nodes
    assert "w1" in graph.nodes  # completed generated node stays
    assert "w1" in ctx.outputs


def test_dynamic_mutation_cycle_rejected() -> None:
    from deepseek_tui.workflow.dag import build_adjacency
    from deepseek_tui.workflow.models import WorkflowValidationError

    step = DynamicStep(
        id="orch",
        type="dynamic",
        permissions=DynamicPermissions(actions=["spawn", "splice_dag"]),
    )
    graph = build_adjacency({"orch": step}, [])
    ctx = WorkflowRunContext(task="t")
    apply_decision_actions(
        step,
        {
            "actions": [
                {"action": "spawn", "id": "a", "label": "a", "prompt": "1"},
            ]
        },
        graph=graph,
        ctx=ctx,
        round_idx=1,
        parent_id="orch",
    )
    with pytest.raises(WorkflowValidationError, match="cycle"):
        apply_decision_actions(
            step,
            {
                "actions": [
                    {
                        "action": "spawn",
                        "id": "b",
                        "label": "b",
                        "prompt": "2",
                        "after": ["a"],
                    },
                    {
                        # splice that adds edge b→a creating a cycle with a→b
                        "action": "splice_dag",
                        "id": "sg",
                        "nodes": [{"id": "c", "type": "agent", "label": "c", "prompt": "3"}],
                        "edges": [{"from": "b", "to": "a"}],
                    },
                ]
            },
            graph=graph,
            ctx=ctx,
            round_idx=2,
            parent_id="orch",
        )


def test_controller_prompt_respects_context_filter() -> None:
    from deepseek_tui.workflow.dag import build_adjacency
    from deepseek_tui.workflow.dynamic import build_controller_prompt

    step = DynamicStep(
        id="orch",
        type="dynamic",
        context_include_outputs=["keep"],
        max_context_chars=10_000,
    )
    graph = build_adjacency({"orch": step}, [])
    ctx = WorkflowRunContext(task="t")
    ctx.outputs["keep"] = make_step_output("KEEP_ME")
    ctx.outputs["drop"] = make_step_output("DROP_ME")
    prompt = build_controller_prompt(
        step, task="t", graph=graph, ctx=ctx, round_idx=1
    )
    assert "KEEP_ME" in prompt
    assert "DROP_ME" not in prompt


@pytest.mark.asyncio
async def test_dynamic_multi_round_sees_spawn_output() -> None:
    """Soul regression: round 2 must observe worker1 as done with its output."""

    class CtrlRunner:
        def __init__(self) -> None:
            self.round = 0
            self.calls: list[str] = []
            self.round2_line: str | None = None

        async def run(self, *, prompt: str, label: str, **kwargs: Any) -> Any:
            self.calls.append(label)
            if label.startswith("dynamic:"):
                self.round += 1
                if self.round == 1:
                    act = {
                        "actions": [
                            {
                                "action": "spawn",
                                "id": "w1",
                                "label": "worker1",
                                "prompt": "gather evidence",
                            }
                        ]
                    }
                    return make_step_output(json.dumps(act), act)
                line = next(
                    (ln for ln in prompt.splitlines() if ln.startswith("- w1 ")),
                    "",
                )
                self.round2_line = line
                act = {"actions": [{"action": "stop", "success": True}]}
                return make_step_output(json.dumps(act), act)
            return make_step_output(f"evidence-from-{label}")

    spec = parse_workflow_spec(adaptive_workflow_spec(task_description="t"))
    runner = CtrlRunner()
    await run_workflow(spec, runner=runner, task="t")
    assert runner.calls[:3] == [
        "dynamic:orchestrate:r1",
        "worker1",
        "dynamic:orchestrate:r2",
    ]
    assert runner.round2_line is not None
    assert "[done]" in runner.round2_line
    assert "evidence-from-worker1" in runner.round2_line


@pytest.mark.asyncio
async def test_dynamic_spawn_and_synthesize_same_round() -> None:
    class CtrlRunner:
        async def run(self, *, prompt: str, label: str, **kwargs: Any) -> Any:
            if label.startswith("dynamic:"):
                act = {
                    "actions": [
                        {
                            "action": "spawn",
                            "id": "w1",
                            "label": "worker1",
                            "prompt": "look",
                        },
                        {
                            "action": "synthesize",
                            "id": "syn",
                            "label": "final",
                            "from": ["w1"],
                            "prompt": "merge {{outputs.w1}}",
                        },
                    ]
                }
                return make_step_output(json.dumps(act), act)
            return make_step_output(f"out:{label}")

    spec = parse_workflow_spec(adaptive_workflow_spec(task_description="t"))
    result = await run_workflow(spec, runner=CtrlRunner(), task="t")
    assert "out:final" in str(result.result) or (
        isinstance(result.result, str) and "out:final" in result.result
    )


def test_mode_dynamic_resolves_adaptive() -> None:
    from deepseek_tui.tools.workflow import WorkflowTool

    spec = WorkflowTool()._resolve_spec({"mode": "dynamic", "task": "explore risks"})
    assert spec.meta.name == "adaptive"
    assert any(s.type == "dynamic" for p in spec.phases for s in p.steps)


def test_adaptive_spec_and_preset_roundtrip(tmp_path) -> None:
    raw = adaptive_workflow_spec(task_description="explore X")
    spec = parse_workflow_spec(raw)
    assert spec.meta.name == "adaptive"
    g = compile_workflow_graph(spec)
    assert "orchestrate" in g.nodes
    assert g.nodes["orchestrate"].type == "dynamic"

    record = create_run(spec, task="explore X", workspace=tmp_path)
    loaded = load_run(record.run_id, workspace=tmp_path)
    again = loaded.parsed_spec()
    assert again.meta.name == "adaptive"
    assert compile_workflow_graph(again).nodes["orchestrate"].type == "dynamic"


def test_repo_review_preset_is_v2_dag() -> None:
    from deepseek_tui.workflow.catalog import resolve_workflow

    spec = resolve_workflow("repo_review")
    assert spec.version == 2
    g = compile_workflow_graph(spec)
    assert g.predecessors["inspect"] == {"plan"}
    assert "plan" in g.predecessors["final"] or "inspect" in g.predecessors["final"]


@pytest.mark.asyncio
async def test_support_node_in_graph() -> None:
    spec = parse_workflow_spec(
        {
            "version": 2,
            "meta": {"name": "sup", "description": "helper"},
            "graph": {
                "nodes": [
                    {"id": "a", "type": "agent", "label": "w", "prompt": "hi"},
                    {
                        "id": "h",
                        "type": "support",
                        "uses": "flatten_previews",
                        "from": ["a"],
                    },
                ],
                "edges": [{"from": "a", "to": "h"}],
            },
        }
    )
    result = await run_workflow(spec, runner=FakeRunner({"w": "hello"}), task="t")
    assert "a" in result.snapshot.result or "h" in str(result.result)


def test_validate_decision_stop_must_be_alone() -> None:
    from deepseek_tui.workflow.dynamic import validate_decision
    from deepseek_tui.workflow.models import WorkflowValidationError

    step = DynamicStep(
        id="orch",
        type="dynamic",
        permissions=DynamicPermissions(actions=["spawn", "stop"]),
    )
    with pytest.raises(WorkflowValidationError, match="stop must be the only"):
        validate_decision(
            {
                "actions": [
                    {"action": "spawn", "prompt": "x"},
                    {"action": "stop"},
                ]
            },
            step=step,
        )


def test_validate_decision_synthesize_must_be_last() -> None:
    from deepseek_tui.workflow.dynamic import validate_decision
    from deepseek_tui.workflow.models import WorkflowValidationError

    step = DynamicStep(
        id="orch",
        type="dynamic",
        permissions=DynamicPermissions(actions=["spawn", "synthesize"]),
    )
    # Same-batch spawn→synthesize is allowed (finish in one round).
    validate_decision(
        {
            "actions": [
                {"action": "spawn", "prompt": "x"},
                {"action": "synthesize", "prompt": "y"},
            ]
        },
        step=step,
    )
    with pytest.raises(WorkflowValidationError, match="synthesize must be the last"):
        validate_decision(
            {
                "actions": [
                    {"action": "synthesize", "prompt": "y"},
                    {"action": "spawn", "prompt": "x"},
                ]
            },
            step=step,
        )


def test_validate_decision_rejects_repeat_signature() -> None:
    from deepseek_tui.workflow.dynamic import (
        decision_loop_signature,
        validate_decision,
    )
    from deepseek_tui.workflow.models import WorkflowFailedError

    step = DynamicStep(
        id="orch",
        type="dynamic",
        permissions=DynamicPermissions(actions=["spawn", "stop"]),
    )
    decision = {"actions": [{"action": "spawn", "id": "w1", "prompt": "look"}]}
    sig = validate_decision(decision, step=step, previous_signatures=[])
    assert sig == decision_loop_signature(decision)
    with pytest.raises(WorkflowFailedError, match="repeated the same decision"):
        validate_decision(decision, step=step, previous_signatures=[sig])


@pytest.mark.asyncio
async def test_fail_fast_cancels_spawned_agents() -> None:
    """fail_fast must ask the SubAgentManager to cancel siblings, not only
    cancel asyncio Tasks."""
    from deepseek_tui.workflow.models import WorkflowFailedError

    cancelled: list[str] = []

    class FakeManager:
        async def cancel(self, agent_id: str) -> None:
            cancelled.append(agent_id)

    class TrackingRunner:
        def __init__(self) -> None:
            self._n = 0

        async def run(self, **kwargs: Any) -> Any:
            on_agent_id = kwargs.get("on_agent_id")
            self._n += 1
            aid = f"agent-{self._n}"
            if callable(on_agent_id):
                on_agent_id(aid)
            label = kwargs.get("label")
            if label == "bad":
                raise RuntimeError("boom")
            await asyncio.sleep(0.05)
            return make_step_output(f"ok:{label}")

    spec = WorkflowSpec(
        version=1,
        meta=WorkflowMeta(name="t", description="d"),
        policy=WorkflowPolicy(on_error="fail_fast", concurrency=2),
        phases=[
            WorkflowPhase(
                id="p1",
                title="P",
                steps=[
                    FanoutStep(
                        id="fan",
                        type="fanout",
                        items=["good", "bad"],
                        agent=AgentStepConfig(
                            label_template="{{item}}",
                            prompt_template="work {{item}}",
                        ),
                    ),
                ],
            )
        ],
    )

    with pytest.raises(WorkflowFailedError, match="bad"):
        await run_workflow(
            spec,
            runner=TrackingRunner(),  # type: ignore[arg-type]
            manager=FakeManager(),  # type: ignore[arg-type]
        )
    assert cancelled, "fail_fast should cancel spawned agent ids via manager"


@pytest.mark.asyncio
async def test_nested_dag_runs_independent_children_concurrently() -> None:
    """Regression: nested DagStep ran its ready batch with a sequential
    for-await loop, so ``policy.concurrency`` was ignored and independent
    children ran one at a time. They must now gather concurrently."""
    in_flight = 0
    max_in_flight = 0
    counter_lock = asyncio.Lock()

    class ConcurrencyRunner:
        async def run(self, *, prompt: str, label: str, **kwargs: Any) -> Any:
            nonlocal in_flight, max_in_flight
            async with counter_lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            try:
                await asyncio.sleep(0.05)
            finally:
                async with counter_lock:
                    in_flight -= 1
            return make_step_output(f"{label}-out")

    # Diamond: a and b are independent (both feed c). With concurrency=2 the
    # dag must run a and b in the same batch. (A 2-node dag with no edges
    # would default to a sequential chain, so it can't express parallelism.)
    spec = parse_workflow_spec(
        {
            "version": 2,
            "meta": {"name": "dag", "description": "nested concurrent"},
            "policy": {"concurrency": 2},
            "graph": {
                "nodes": [
                    {
                        "id": "root",
                        "type": "dag",
                        "nodes": [
                            {"id": "a", "type": "agent", "label": "a", "prompt": "A"},
                            {"id": "b", "type": "agent", "label": "b", "prompt": "B"},
                            {"id": "c", "type": "agent", "label": "c", "prompt": "C"},
                        ],
                        "edges": [
                            {"from": "a", "to": "c"},
                            {"from": "b", "to": "c"},
                        ],
                    }
                ],
                "edges": [],
            },
        }
    )
    await run_workflow(spec, runner=ConcurrencyRunner())  # type: ignore[arg-type]
    assert max_in_flight >= 2, "nested dag children a and b should run concurrently"


@pytest.mark.asyncio
async def test_drain_ready_cancels_sibling_batch_on_fail_fast() -> None:
    """Regression: ``_drain_ready`` used ``asyncio.gather`` without cancelling
    siblings on failure, so a fail_fast node left the other batch task running
    as an orphan that kept mutating ctx/snapshot while the error handler ran.
    Siblings must now be cancelled."""
    from deepseek_tui.workflow.models import WorkflowFailedError

    b_completed = False

    class FailRunner:
        async def run(self, *, prompt: str, label: str, **kwargs: Any) -> Any:
            nonlocal b_completed
            if label == "worker-a":
                raise RuntimeError("boom")
            await asyncio.sleep(0.2)
            b_completed = True
            return make_step_output("b-out")

    spec = parse_workflow_spec(
        {
            "version": 2,
            "meta": {"name": "fail", "description": "fail_fast orphan"},
            "policy": {"concurrency": 2, "on_error": "fail_fast"},
            "graph": {
                "nodes": [
                    {"id": "a", "type": "agent", "label": "worker-a", "prompt": "A"},
                    {"id": "b", "type": "agent", "label": "worker-b", "prompt": "B"},
                ],
                "edges": [],
            },
        }
    )
    with pytest.raises(WorkflowFailedError):
        await run_workflow(spec, runner=FailRunner())  # type: ignore[arg-type]
    # Give any orphan that escaped cancellation a chance to finish. With the
    # fix worker-b is cancelled before its sleep completes.
    await asyncio.sleep(0.4)
    assert not b_completed, "sibling worker-b should have been cancelled, not completed"
