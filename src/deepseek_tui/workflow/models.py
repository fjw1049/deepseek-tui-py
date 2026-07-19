"""Workflow models, validation, serialization, templates, constants.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


class WorkflowAbortedError(Exception):
    pass


class WorkflowFailedError(Exception):
    pass


StepType = Literal[
    "agent",
    "fanout",
    "pipeline",
    "synthesis",
    "reduce",
    "loop",
    "dag",
    "dynamic",
    "support",
]
ApprovalMode = Literal["analysis_only", "trusted_workflow", "strict", "inherit"]
OnErrorMode = Literal["continue", "fail_fast"]
WorktreeMode = Literal["off", "on"]
SourcePolicy = Literal["success", "partial"]
AgentRunStatus = Literal["queued", "running", "done", "error", "skipped"]

MAX_FANOUT_ITEMS = 16
MAX_LOOP_ROUNDS = 8
WAIT_TIMEOUT_MS = 3_600_000
DEFAULT_WALL_CLOCK_SECONDS = 600
DEFAULT_CONCURRENCY = 4
DEFAULT_MAX_AGENTS = 10
PREVIEW_MAX_PER_STEP = 2000
PREVIEW_MAX_FANOUT_ITEM = 800
FULL_TEXT_MAX = 32_768

DYNAMIC_ACTIONS = frozenset(
    {
        "spawn",
        "fanout",
        "reduce",
        "support",
        "splice_dag",
        "nested_workflow",
        "synthesize",
        "replan",
        "stop",
    }
)


@dataclass(slots=True)
class WorkflowMeta:
    name: str
    description: str


@dataclass(slots=True)
class WorkflowPolicy:
    approval_mode: ApprovalMode = "inherit"
    on_error: OnErrorMode = "continue"
    max_agents: int = 10
    concurrency: int = 4
    wall_clock_seconds: int = 600
    # NOTE: enforced at runtime via character/4 estimate in the DAG scheduler.
    token_budget: int | None = None
    worktree: WorktreeMode = "off"


@dataclass(slots=True)
class AgentStepConfig:
    label: str | None = None
    label_template: str | None = None
    agent_type: str = "general"
    model: str | None = None
    allowed_tools: list[str] | None = None
    prompt: str | None = None
    prompt_template: str | None = None
    output_schema: dict[str, Any] | None = None
    timeout_seconds: int | None = None


@dataclass(slots=True)
class AgentStep:
    id: str
    type: Literal["agent"]
    label: str
    agent_type: str = "general"
    model: str | None = None
    allowed_tools: list[str] | None = None
    prompt: str = ""
    output_schema: dict[str, Any] | None = None
    timeout_seconds: int | None = None


@dataclass(slots=True)
class ItemsFrom:
    """Dynamic fanout source: resolve an array from a prior step's structured output."""

    step: str
    path: str = "$"


@dataclass(slots=True)
class FanoutStep:
    id: str
    type: Literal["fanout"]
    agent: AgentStepConfig
    items: list[str] | None = None
    items_from: ItemsFrom | None = None
    concurrency: int | None = None


@dataclass(slots=True)
class PipelineStage:
    label_template: str | None = None
    agent_type: str = "general"
    model: str | None = None
    prompt_template: str = ""


@dataclass(slots=True)
class PipelineStep:
    id: str
    type: Literal["pipeline"]
    items: list[str]
    stages: list[PipelineStage]


@dataclass(slots=True)
class SynthesisStep:
    id: str
    type: Literal["synthesis"]
    label: str
    agent_type: str = "general"
    model: str | None = None
    allowed_tools: list[str] | None = None
    prompt_template: str = ""
    output_schema: dict[str, Any] | None = None
    timeout_seconds: int | None = None


@dataclass(slots=True)
class ReduceStep:
    """Fan-in: wait for ``from_steps``, then run one synthesis-style agent."""

    id: str
    type: Literal["reduce"]
    label: str
    from_steps: list[str]
    agent_type: str = "general"
    model: str | None = None
    allowed_tools: list[str] | None = None
    prompt_template: str = ""
    output_schema: dict[str, Any] | None = None
    timeout_seconds: int | None = None
    source_policy: SourcePolicy = "partial"


@dataclass(slots=True)
class LoopUntil:
    """Stop a loop when a body step's structured output matches ``equals``."""

    path: str
    equals: Any = True
    step: str | None = None  # default: last body step


@dataclass(slots=True)
class LoopStep:
    id: str
    type: Literal["loop"]
    max_rounds: int
    steps: list[WorkflowStep]
    until: LoopUntil | None = None


@dataclass(slots=True)
class DagStep:
    """Nested subgraph container; exposes ``output_from`` node output upstream."""

    id: str
    type: Literal["dag"]
    nodes: list[WorkflowStep]
    edges: list[tuple[str, str]]  # (from, to)
    output_from: str | None = None


@dataclass(slots=True)
class DynamicBudget:
    max_decision_rounds: int = 12
    max_agents: int = 32
    max_mutations: int = 80
    max_fanout_items: int = 16
    max_nested_dynamic_depth: int = 2
    wall_clock_seconds: int = 1200


@dataclass(slots=True)
class DynamicPermissions:
    actions: list[str] = field(
        default_factory=lambda: [
            "spawn",
            "fanout",
            "reduce",
            "support",
            "splice_dag",
            "synthesize",
            "replan",
            "stop",
        ]
    )
    allow_nested_workflow: bool = True
    allow_write_tools: bool = False


@dataclass(slots=True)
class DynamicStep:
    id: str
    type: Literal["dynamic"]
    controller_agent_type: str = "review"
    controller_model: str | None = None
    controller_allowed_tools: list[str] | None = None
    budget: DynamicBudget = field(default_factory=DynamicBudget)
    permissions: DynamicPermissions = field(default_factory=DynamicPermissions)
    context_include_outputs: list[str] = field(default_factory=lambda: ["*"])
    max_context_chars: int = 48_000


@dataclass(slots=True)
class SupportStep:
    id: str
    type: Literal["support"]
    uses: str
    from_steps: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)


WorkflowStep = (
    AgentStep
    | FanoutStep
    | PipelineStep
    | SynthesisStep
    | ReduceStep
    | LoopStep
    | DagStep
    | DynamicStep
    | SupportStep
)


@dataclass(slots=True)
class WorkflowPhase:
    id: str
    title: str
    steps: list[WorkflowStep]


@dataclass(slots=True)
class WorkflowSpec:
    version: int
    meta: WorkflowMeta
    policy: WorkflowPolicy
    phases: list[WorkflowPhase] = field(default_factory=list)
    # Populated after parse (v1 compile or v2 native). Not part of authoring JSON.
    compiled_graph: Any | None = field(default=None, repr=False)


@dataclass(slots=True)
class StepOutput:
    text: str
    structured: Any | None
    preview: str


@dataclass(slots=True)
class WorkflowAgentRun:
    step_id: str
    label: str
    phase_id: str
    status: AgentRunStatus
    agent_id: str | None = None
    result_preview: str | None = None
    error: str | None = None


@dataclass(slots=True)
class WorkflowNodeSnapshot:
    id: str
    type: str
    status: AgentRunStatus
    generated: bool = False
    predecessors: list[str] = field(default_factory=list)
    label: str | None = None


@dataclass(slots=True)
class WorkflowSnapshot:
    name: str
    description: str
    phases: list[str] = field(default_factory=list)
    current_phase: str | None = None
    logs: list[str] = field(default_factory=list)
    agents: list[WorkflowAgentRun] = field(default_factory=list)
    agent_count: int = 0
    running_count: int = 0
    done_count: int = 0
    error_count: int = 0
    duration_ms: int | None = None
    result: Any | None = None
    nodes: list[WorkflowNodeSnapshot] = field(default_factory=list)
    edges: list[dict[str, str]] = field(default_factory=list)
    dynamic_rounds: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class WorkflowStepError:
    step_id: str
    error: str


@dataclass(slots=True)
class WorkflowRunResult:
    meta: WorkflowMeta
    result: Any
    snapshot: WorkflowSnapshot
    logs: list[str]
    duration_ms: int
    errors: list[WorkflowStepError] = field(default_factory=list)


@dataclass(slots=True)
class WorkflowRunContext:
    outputs: dict[str, StepOutput] = field(default_factory=dict)
    spawned_agent_ids: list[str] = field(default_factory=list)
    synthesis_step_ids: list[str] = field(default_factory=list)
    task: str = ""
    round: int | None = None
    completed_step_ids: list[str] = field(default_factory=list)
    skipped_step_ids: list[str] = field(default_factory=list)
    failed_step_ids: list[str] = field(default_factory=list)
    dynamic_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    budgets_used: dict[str, int] = field(default_factory=dict)
    generated_node_ids: list[str] = field(default_factory=list)
    nested_dynamic_depth: int = 0
    estimated_tokens_used: int = 0
    # Serialized CompiledGraph (incl. dynamic mutations) for checkpoint/resume.
    runtime_graph: dict[str, Any] | None = None


# Parse and validate Workflow IR JSON.



class WorkflowValidationError(ValueError):
    pass


def parse_workflow_spec(raw: Any) -> WorkflowSpec:
    """Parse tool input into a validated WorkflowSpec (v1 phases or v2 graph)."""
    if not isinstance(raw, dict):
        raise WorkflowValidationError("workflow spec must be a JSON object")
    if raw.get("spec") is not None and isinstance(raw.get("spec"), dict):
        raw = raw["spec"]
    version = raw.get("version", 1)
    if version not in (1, 2):
        raise WorkflowValidationError(f"unsupported workflow version: {version}")
    meta_raw = raw.get("meta")
    if not isinstance(meta_raw, dict):
        raise WorkflowValidationError("meta must be an object")
    name = meta_raw.get("name")
    description = meta_raw.get("description")
    if not isinstance(name, str) or not name.strip():
        raise WorkflowValidationError("meta.name must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise WorkflowValidationError("meta.description must be a non-empty string")
    meta = WorkflowMeta(name=name.strip(), description=description.strip())
    policy = _parse_policy(raw.get("policy") or {})

    from deepseek_tui.workflow.dag import (
        CompiledGraph,
        GraphEdge,
        assert_acyclic,
        build_adjacency,
        compile_phases_to_graph,
    )

    if version == 1 or (version == 2 and raw.get("phases") and not raw.get("graph")):
        phases_raw = raw.get("phases")
        if not isinstance(phases_raw, list) or not phases_raw:
            raise WorkflowValidationError("phases must be a non-empty array")
        phases, step_ids, agent_step_count = _parse_phases(phases_raw)
        if agent_step_count == 0:
            raise WorkflowValidationError("workflow must include at least one agent step")
        _validate_output_refs(phases, step_ids)
        spec = WorkflowSpec(version=1 if version == 1 else 2, meta=meta, policy=policy, phases=phases)
        spec.compiled_graph = compile_phases_to_graph(phases)
        return spec

    # version 2 native graph
    graph_raw = raw.get("graph")
    if not isinstance(graph_raw, dict):
        raise WorkflowValidationError("graph must be an object for version 2")
    nodes_raw = graph_raw.get("nodes")
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise WorkflowValidationError("graph.nodes must be a non-empty array")
    edges_raw = graph_raw.get("edges") or []
    if not isinstance(edges_raw, list):
        raise WorkflowValidationError("graph.edges must be an array")

    nodes: dict[str, WorkflowStep] = {}
    step_ids: set[str] = set()
    agent_step_count = 0
    after_hints: dict[str, list[str]] = {}
    for idx, node_raw in enumerate(nodes_raw):
        if not isinstance(node_raw, dict):
            raise WorkflowValidationError("each graph node must be an object")
        after = node_raw.get("after")
        step = _parse_step(node_raw, "graph", idx)
        if step.id in nodes:
            raise WorkflowValidationError(f"duplicate step id: {step.id}")
        nodes[step.id] = step
        for sid in _collect_step_ids(step):
            step_ids.add(sid)
        agent_step_count += _agent_weight(step)
        if after is not None:
            after_hints[step.id] = _parse_after(after, step.id)

    edges: list[GraphEdge] = []
    for eraw in edges_raw:
        if not isinstance(eraw, dict):
            raise WorkflowValidationError("each edge must be an object")
        fr, to = eraw.get("from"), eraw.get("to")
        if not isinstance(fr, str) or not isinstance(to, str):
            raise WorkflowValidationError("edge.from and edge.to must be strings")
        edges.append(GraphEdge(from_id=fr.strip(), to_id=to.strip()))

    for nid, preds in after_hints.items():
        for pred in preds:
            edges.append(GraphEdge(from_id=pred, to_id=nid))
            # reduce/support from_steps also imply edges
            pass

    # Auto-wire reduce/support from_steps as edges when missing
    for nid, step in nodes.items():
        if step.type == "reduce":
            for pred in step.from_steps:
                edges.append(GraphEdge(from_id=pred, to_id=nid))
        elif step.type == "support":
            for pred in step.from_steps:
                edges.append(GraphEdge(from_id=pred, to_id=nid))

    # Dedupe edges
    seen_e: set[tuple[str, str]] = set()
    uniq_edges: list[GraphEdge] = []
    for e in edges:
        key = (e.from_id, e.to_id)
        if key in seen_e:
            continue
        seen_e.add(key)
        uniq_edges.append(e)

    if agent_step_count == 0 and not any(s.type == "dynamic" for s in nodes.values()):
        raise WorkflowValidationError("workflow must include at least one agent or dynamic step")

    graph = build_adjacency(nodes, uniq_edges)
    assert_acyclic(graph)
    # Fake single phase for UI
    graph.phase_of = {nid: "graph" for nid in nodes}
    graph.phase_titles = {"graph": meta.name}
    _validate_graph_output_refs(graph)

    # Also expose a linear phases view for tools that still expect phases
    phases = [
        WorkflowPhase(id="graph", title=meta.name, steps=list(nodes.values()))
    ]
    spec = WorkflowSpec(version=2, meta=meta, policy=policy, phases=phases)
    spec.compiled_graph = graph
    return spec


def _parse_phases(
    phases_raw: list[Any],
) -> tuple[list[WorkflowPhase], set[str], int]:
    phases: list[WorkflowPhase] = []
    step_ids: set[str] = set()
    agent_step_count = 0
    for phase_raw in phases_raw:
        if not isinstance(phase_raw, dict):
            raise WorkflowValidationError("each phase must be an object")
        raw_id = phase_raw.get("id")
        phase_id = str(raw_id).strip() if raw_id else ""
        if not phase_id:
            phase_id = f"phase_{len(phases) + 1}"
        title = phase_raw.get("title")
        if not isinstance(title, str) or not title.strip():
            title = phase_id
        steps_raw = phase_raw.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise WorkflowValidationError(f"phase {phase_id}: steps must be non-empty")
        steps: list[WorkflowStep] = []
        for step_idx, step_raw in enumerate(steps_raw):
            step = _parse_step(step_raw, phase_id, step_idx)
            for sid in _collect_step_ids(step):
                if sid in step_ids:
                    raise WorkflowValidationError(f"duplicate step id: {sid}")
                step_ids.add(sid)
            agent_step_count += _agent_weight(step)
            steps.append(step)
        phases.append(WorkflowPhase(id=phase_id.strip(), title=title.strip(), steps=steps))
    return phases, step_ids, agent_step_count


def _agent_weight(step: WorkflowStep) -> int:
    if step.type in ("agent", "synthesis", "reduce", "fanout", "loop", "dynamic"):
        return 1
    if step.type == "pipeline":
        return len(step.stages) * max(1, len(step.items))
    if step.type == "dag":
        return sum(_agent_weight(s) for s in step.nodes) or 1
    if step.type == "support":
        return 0
    return 0


def _parse_after(raw: Any, step_id: str) -> list[str]:
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip()]
        return out
    raise WorkflowValidationError(f"step {step_id}: after must be a string or array")


def adaptive_workflow_spec(*, task_description: str = "adaptive orchestration") -> dict[str, Any]:
    """Builtin v2 spec: single dynamic root (product entry for mode=dynamic)."""
    return {
        "version": 2,
        "meta": {
            "name": "adaptive",
            "description": task_description,
        },
        "policy": {
            "approval_mode": "inherit",
            "on_error": "continue",
            "max_agents": 16,
            "concurrency": 4,
            "wall_clock_seconds": 1200,
        },
        "graph": {
            "nodes": [
                {
                    "id": "orchestrate",
                    "type": "dynamic",
                    "controller": {"agent_type": "review"},
                    "budget": {
                        "max_decision_rounds": 12,
                        "max_agents": 32,
                        "max_mutations": 80,
                        "max_fanout_items": 16,
                        "max_nested_dynamic_depth": 2,
                        "wall_clock_seconds": 1200,
                    },
                    "permissions": {
                        "actions": [
                            "spawn",
                            "fanout",
                            "reduce",
                            "support",
                            "splice_dag",
                            "nested_workflow",
                            "synthesize",
                            "replan",
                            "stop",
                        ],
                        "allow_nested_workflow": True,
                        "allow_write_tools": False,
                    },
                }
            ],
            "edges": [],
        },
    }


def _parse_policy(raw: dict[str, Any]) -> WorkflowPolicy:
    if not isinstance(raw, dict):
        raise WorkflowValidationError("policy must be an object")
    mode = raw.get("approval_mode", "inherit")
    if mode not in ("analysis_only", "trusted_workflow", "strict", "inherit"):
        raise WorkflowValidationError("policy.approval_mode invalid")
    on_error = raw.get("on_error", "continue")
    if on_error not in ("continue", "fail_fast"):
        raise WorkflowValidationError("policy.on_error must be continue or fail_fast")
    max_agents = _parse_int(raw.get("max_agents", DEFAULT_MAX_AGENTS), "policy.max_agents")
    concurrency = _parse_int(raw.get("concurrency", 4), "policy.concurrency")
    wall = _parse_int(
        raw.get("wall_clock_seconds", 600), "policy.wall_clock_seconds"
    )
    budget = raw.get("token_budget")
    worktree = raw.get("worktree", "off")
    if worktree not in ("off", "on"):
        raise WorkflowValidationError('policy.worktree must be "off" or "on"')
    if max_agents < 1 or max_agents > 32:
        raise WorkflowValidationError("policy.max_agents must be 1..32")
    if concurrency < 1 or concurrency > max_agents:
        raise WorkflowValidationError("policy.concurrency must be 1..max_agents")
    return WorkflowPolicy(
        approval_mode=mode,
        on_error=on_error,
        max_agents=max_agents,
        concurrency=concurrency,
        wall_clock_seconds=wall,
        token_budget=(
            _parse_int(budget, "policy.token_budget") if budget is not None else None
        ),
        worktree=worktree,
    )


def _parse_step(raw: Any, phase_id: str, step_index: int = 0) -> WorkflowStep:
    if not isinstance(raw, dict):
        raise WorkflowValidationError(f"phase {phase_id}: each step must be an object")
    raw_id = raw.get("id")
    step_id = str(raw_id).strip() if raw_id else ""
    if not step_id:
        step_id = f"{phase_id}_step_{step_index + 1}"
    step_type = raw.get("type")
    if step_type == "agent":
        label = raw.get("label")
        if not isinstance(label, str) or not label.strip():
            raise WorkflowValidationError(f"step {step_id}: label required")
        prompt = raw.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise WorkflowValidationError(f"step {step_id}: prompt required")
        return AgentStep(
            id=step_id.strip(),
            type="agent",
            label=label.strip(),
            agent_type=str(raw.get("agent_type", "general")),
            model=raw.get("model"),
            allowed_tools=_parse_allowed(raw.get("allowed_tools")),
            prompt=prompt.strip(),
            output_schema=_parse_schema(raw.get("output_schema")),
            timeout_seconds=_parse_int_opt(
                raw.get("timeout_seconds"),
                f"step {step_id}: timeout_seconds",
                min_val=1,
                max_val=3600,
            ),
        )
    if step_type == "fanout":
        items = raw.get("items")
        items_from_raw = raw.get("items_from")
        has_items = isinstance(items, list) and bool(items)
        has_items_from = items_from_raw is not None
        if has_items and has_items_from:
            raise WorkflowValidationError(
                f"step {step_id}: fanout.items and fanout.items_from are mutually exclusive"
            )
        if not has_items and not has_items_from:
            raise WorkflowValidationError(
                f"step {step_id}: fanout requires items or items_from"
            )
        parsed_items: list[str] | None = None
        parsed_items_from: ItemsFrom | None = None
        if has_items:
            assert isinstance(items, list)
            if len(items) > MAX_FANOUT_ITEMS:
                raise WorkflowValidationError(
                    f"step {step_id}: fanout.items exceeds max {MAX_FANOUT_ITEMS}"
                )
            parsed_items = [str(x) for x in items]
        else:
            parsed_items_from = _parse_items_from(items_from_raw, step_id)
        agent_raw = raw.get("agent")
        if agent_raw is None:
            agent_raw = _fanout_agent_from_flat_step(raw)
        elif isinstance(agent_raw, dict):
            flat = _fanout_agent_from_flat_step(raw)
            if flat:
                merged = dict(flat)
                merged.update(agent_raw)
                agent_raw = merged
        if not isinstance(agent_raw, dict):
            raise WorkflowValidationError(f"step {step_id}: fanout.agent required")
        concurrency = (
            _parse_int(raw.get("concurrency"), f"step {step_id}: concurrency")
            if raw.get("concurrency") is not None
            else None
        )
        if concurrency is not None and concurrency < 1:
            raise WorkflowValidationError(f"step {step_id}: concurrency must be >= 1")
        return FanoutStep(
            id=step_id.strip(),
            type="fanout",
            items=parsed_items,
            items_from=parsed_items_from,
            agent=_parse_agent_config(agent_raw),
            concurrency=concurrency,
        )
    if step_type == "pipeline":
        items = raw.get("items")
        stages_raw = raw.get("stages")
        if not isinstance(items, list) or not items:
            raise WorkflowValidationError(f"step {step_id}: pipeline.items required")
        if len(items) > MAX_FANOUT_ITEMS:
            raise WorkflowValidationError(
                f"step {step_id}: pipeline.items exceeds max {MAX_FANOUT_ITEMS}"
            )
        if not isinstance(stages_raw, list) or not stages_raw:
            raise WorkflowValidationError(f"step {step_id}: pipeline.stages required")
        stages = []
        for st in stages_raw:
            if not isinstance(st, dict):
                raise WorkflowValidationError(f"step {step_id}: invalid pipeline stage")
            stages.append(
                PipelineStage(
                    label_template=st.get("label_template"),
                    agent_type=str(st.get("agent_type", "general")),
                    model=st.get("model"),
                    prompt_template=str(st.get("prompt_template", "")),
                )
            )
        return PipelineStep(
            id=step_id.strip(),
            type="pipeline",
            items=[str(x) for x in items],
            stages=stages,
        )
    if step_type == "synthesis":
        label = raw.get("label")
        if not isinstance(label, str) or not label.strip():
            raise WorkflowValidationError(f"step {step_id}: label required")
        tmpl = raw.get("prompt_template")
        if not isinstance(tmpl, str) or not tmpl.strip():
            raise WorkflowValidationError(f"step {step_id}: prompt_template required")
        return SynthesisStep(
            id=step_id.strip(),
            type="synthesis",
            label=label.strip(),
            agent_type=str(raw.get("agent_type", "general")),
            model=raw.get("model"),
            allowed_tools=_parse_allowed(raw.get("allowed_tools")),
            prompt_template=tmpl.strip(),
            output_schema=_parse_schema(raw.get("output_schema")),
            timeout_seconds=_parse_int_opt(
                raw.get("timeout_seconds"),
                f"step {step_id}: timeout_seconds",
                min_val=1,
                max_val=3600,
            ),
        )
    if step_type == "reduce":
        label = raw.get("label")
        if not isinstance(label, str) or not label.strip():
            raise WorkflowValidationError(f"step {step_id}: label required")
        tmpl = raw.get("prompt_template")
        if not isinstance(tmpl, str) or not tmpl.strip():
            raise WorkflowValidationError(f"step {step_id}: prompt_template required")
        from_raw = raw.get("from") or raw.get("from_steps") or []
        if isinstance(from_raw, str):
            from_steps = [from_raw.strip()] if from_raw.strip() else []
        elif isinstance(from_raw, list):
            from_steps = [str(x).strip() for x in from_raw if str(x).strip()]
        else:
            raise WorkflowValidationError(f"step {step_id}: reduce.from must be string or array")
        if not from_steps:
            raise WorkflowValidationError(f"step {step_id}: reduce.from required")
        source_policy = raw.get("source_policy", "partial")
        if source_policy not in ("success", "partial"):
            raise WorkflowValidationError(
                f"step {step_id}: source_policy must be success or partial"
            )
        return ReduceStep(
            id=step_id.strip(),
            type="reduce",
            label=label.strip(),
            from_steps=from_steps,
            agent_type=str(raw.get("agent_type", "general")),
            model=raw.get("model"),
            allowed_tools=_parse_allowed(raw.get("allowed_tools")),
            prompt_template=tmpl.strip(),
            output_schema=_parse_schema(raw.get("output_schema")),
            timeout_seconds=_parse_int_opt(
                raw.get("timeout_seconds"),
                f"step {step_id}: timeout_seconds",
                min_val=1,
                max_val=3600,
            ),
            source_policy=source_policy,  # type: ignore[arg-type]
        )
    if step_type == "loop":
        max_rounds = _parse_int(raw.get("max_rounds", 3), f"step {step_id}: max_rounds")
        if max_rounds < 1 or max_rounds > MAX_LOOP_ROUNDS:
            raise WorkflowValidationError(
                f"step {step_id}: max_rounds must be 1..{MAX_LOOP_ROUNDS}"
            )
        body_raw = raw.get("steps")
        if not isinstance(body_raw, list) or not body_raw:
            raise WorkflowValidationError(f"step {step_id}: loop.steps required")
        body: list[WorkflowStep] = []
        for idx, child_raw in enumerate(body_raw):
            child = _parse_step(child_raw, f"{phase_id}/{step_id}", idx)
            if child.type == "loop":
                raise WorkflowValidationError(
                    f"step {step_id}: nested loop is not supported"
                )
            body.append(child)
        until = _parse_loop_until(raw.get("until"), step_id, body)
        return LoopStep(
            id=step_id.strip(),
            type="loop",
            max_rounds=max_rounds,
            steps=body,
            until=until,
        )
    if step_type == "dag":
        child_nodes_raw = raw.get("nodes")
        if not isinstance(child_nodes_raw, list) or not child_nodes_raw:
            raise WorkflowValidationError(f"step {step_id}: dag.nodes required")
        child_nodes: list[WorkflowStep] = []
        for idx, child_raw in enumerate(child_nodes_raw):
            child = _parse_step(child_raw, f"{phase_id}/{step_id}", idx)
            if child.type in ("dag", "dynamic"):
                raise WorkflowValidationError(
                    f"step {step_id}: nested dag/dynamic inside dag is not supported"
                )
            child_nodes.append(child)
        child_edges: list[tuple[str, str]] = []
        for eraw in raw.get("edges") or []:
            if not isinstance(eraw, dict):
                continue
            fr, to = eraw.get("from"), eraw.get("to")
            if isinstance(fr, str) and isinstance(to, str):
                child_edges.append((fr.strip(), to.strip()))
        # Sequential default if no edges
        if not child_edges and len(child_nodes) > 1:
            for i in range(len(child_nodes) - 1):
                child_edges.append((child_nodes[i].id, child_nodes[i + 1].id))
        output_from = raw.get("output_from")
        if output_from is not None and not isinstance(output_from, str):
            raise WorkflowValidationError(f"step {step_id}: output_from must be a string")
        if output_from is None and child_nodes:
            output_from = child_nodes[-1].id
        return DagStep(
            id=step_id.strip(),
            type="dag",
            nodes=child_nodes,
            edges=child_edges,
            output_from=output_from.strip() if isinstance(output_from, str) else None,
        )
    if step_type == "dynamic":
        ctrl = raw.get("controller") or {}
        if not isinstance(ctrl, dict):
            raise WorkflowValidationError(f"step {step_id}: controller must be an object")
        budget_raw = raw.get("budget") or {}
        if not isinstance(budget_raw, dict):
            raise WorkflowValidationError(f"step {step_id}: budget must be an object")
        perm_raw = raw.get("permissions") or {}
        if not isinstance(perm_raw, dict):
            raise WorkflowValidationError(f"step {step_id}: permissions must be an object")
        actions = perm_raw.get("actions")
        if actions is None:
            action_list = list(DYNAMIC_ACTIONS - {"nested_workflow"})
        elif isinstance(actions, list):
            action_list = [str(a) for a in actions]
            bad = [a for a in action_list if a not in DYNAMIC_ACTIONS]
            if bad:
                raise WorkflowValidationError(
                    f"step {step_id}: unknown dynamic actions {bad}"
                )
        else:
            raise WorkflowValidationError(f"step {step_id}: permissions.actions must be array")
        ctx_raw = raw.get("context") or {}
        if not isinstance(ctx_raw, dict):
            raise WorkflowValidationError(f"step {step_id}: context must be an object")
        include = ctx_raw.get("include_outputs", ["*"])
        if not isinstance(include, list):
            raise WorkflowValidationError(
                f"step {step_id}: context.include_outputs must be array"
            )
        return DynamicStep(
            id=step_id.strip(),
            type="dynamic",
            controller_agent_type=str(ctrl.get("agent_type", "review")),
            controller_model=ctrl.get("model"),
            controller_allowed_tools=_parse_allowed(ctrl.get("allowed_tools")),
            budget=DynamicBudget(
                max_decision_rounds=_parse_int(
                    budget_raw.get("max_decision_rounds", 12),
                    f"step {step_id}: budget.max_decision_rounds",
                ),
                max_agents=_parse_int(
                    budget_raw.get("max_agents", 32),
                    f"step {step_id}: budget.max_agents",
                ),
                max_mutations=_parse_int(
                    budget_raw.get("max_mutations", 80),
                    f"step {step_id}: budget.max_mutations",
                ),
                max_fanout_items=_parse_int(
                    budget_raw.get("max_fanout_items", 16),
                    f"step {step_id}: budget.max_fanout_items",
                ),
                max_nested_dynamic_depth=_parse_int(
                    budget_raw.get("max_nested_dynamic_depth", 2),
                    f"step {step_id}: budget.max_nested_dynamic_depth",
                ),
                wall_clock_seconds=_parse_int(
                    budget_raw.get("wall_clock_seconds", 1200),
                    f"step {step_id}: budget.wall_clock_seconds",
                ),
            ),
            permissions=DynamicPermissions(
                actions=action_list,
                allow_nested_workflow=bool(perm_raw.get("allow_nested_workflow", True)),
                allow_write_tools=bool(perm_raw.get("allow_write_tools", False)),
            ),
            context_include_outputs=[str(x) for x in include],
            max_context_chars=_parse_int(
                ctx_raw.get("max_context_chars", 48000),
                f"step {step_id}: context.max_context_chars",
            ),
        )
    if step_type == "support":
        uses = raw.get("uses")
        if not isinstance(uses, str) or not uses.strip():
            raise WorkflowValidationError(f"step {step_id}: support.uses required")
        from_raw = raw.get("from") or raw.get("from_steps") or []
        if isinstance(from_raw, str):
            from_steps = [from_raw.strip()] if from_raw.strip() else []
        elif isinstance(from_raw, list):
            from_steps = [str(x).strip() for x in from_raw if str(x).strip()]
        else:
            raise WorkflowValidationError(f"step {step_id}: support.from must be string or array")
        options = raw.get("options") or {}
        if not isinstance(options, dict):
            raise WorkflowValidationError(f"step {step_id}: support.options must be object")
        return SupportStep(
            id=step_id.strip(),
            type="support",
            uses=uses.strip(),
            from_steps=from_steps,
            options=dict(options),
        )
    raise WorkflowValidationError(f"step {step_id}: unknown type {step_type!r}")


def step_from_dict(raw: dict[str, Any], *, fallback_id: str = "step") -> WorkflowStep:
    """Rehydrate a step from checkpoint / graph serialization."""
    if "id" not in raw:
        raw = {**raw, "id": fallback_id}
    return _parse_step(raw, "restore", 0)


def _parse_loop_until(
    raw: Any, step_id: str, body: list[WorkflowStep]
) -> LoopUntil | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise WorkflowValidationError(f"step {step_id}: until must be an object")
    path = raw.get("path", "$")
    if not isinstance(path, str) or not path.strip():
        raise WorkflowValidationError(f"step {step_id}: until.path must be a string")
    path = path.strip()
    try:
        _validate_simple_json_path(path)
    except WorkflowValidationError as exc:
        raise WorkflowValidationError(f"step {step_id}: {exc}") from exc
    until_step = raw.get("step")
    body_ids = {s.id for s in body}
    if until_step is not None:
        if not isinstance(until_step, str) or not until_step.strip():
            raise WorkflowValidationError(f"step {step_id}: until.step must be a string")
        until_step = until_step.strip()
        if until_step not in body_ids:
            raise WorkflowValidationError(
                f"step {step_id}: until.step {until_step!r} is not in loop body"
            )
    return LoopUntil(
        path=path,
        equals=raw.get("equals", True),
        step=until_step,
    )

def _parse_items_from(raw: Any, step_id: str) -> ItemsFrom:
    if not isinstance(raw, dict):
        raise WorkflowValidationError(f"step {step_id}: items_from must be an object")
    source = raw.get("step")
    if not isinstance(source, str) or not source.strip():
        raise WorkflowValidationError(f"step {step_id}: items_from.step required")
    path = raw.get("path", "$")
    if not isinstance(path, str) or not path.strip():
        raise WorkflowValidationError(f"step {step_id}: items_from.path must be a string")
    path = path.strip()
    try:
        _validate_simple_json_path(path)
    except WorkflowValidationError as exc:
        raise WorkflowValidationError(f"step {step_id}: {exc}") from exc
    return ItemsFrom(step=source.strip(), path=path)


_PATH_SEGMENT_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)(?:\[(\d+)\])?$")


def _validate_simple_json_path(path: str) -> None:
    """Accept ``$``, ``$.a.b``, ``$.a[0].b`` only."""
    if path == "$":
        return
    if not path.startswith("$."):
        raise WorkflowValidationError(
            "items_from.path must be '$' or start with '$.' (e.g. $.targets)"
        )
    rest = path[2:]
    if not rest:
        raise WorkflowValidationError("items_from.path is incomplete after $.")
    for segment in rest.split("."):
        if not segment or not _PATH_SEGMENT_RE.match(segment):
            raise WorkflowValidationError(
                f"items_from.path has invalid segment {segment!r}"
            )


def resolve_simple_json_path(root: Any, path: str) -> Any:
    """Resolve a minimal JSONPath against ``root``."""
    _validate_simple_json_path(path)
    if path == "$":
        return root
    current = root
    for segment in path[2:].split("."):
        match = _PATH_SEGMENT_RE.match(segment)
        assert match is not None
        key, index_s = match.group(1), match.group(2)
        if not isinstance(current, dict) or key not in current:
            raise WorkflowValidationError(
                f"path {path!r}: missing key {key!r}"
            )
        current = current[key]
        if index_s is not None:
            index = int(index_s)
            if not isinstance(current, list):
                raise WorkflowValidationError(
                    f"path {path!r}: {key} is not an array"
                )
            if index < 0 or index >= len(current):
                raise WorkflowValidationError(
                    f"path {path!r}: index {index} out of range"
                )
            current = current[index]
    return current


def coerce_fanout_items(value: Any) -> list[str]:
    """Normalize a JSON value into fanout item strings."""
    if not isinstance(value, list):
        raise WorkflowValidationError("items_from path must resolve to an array")
    if not value:
        raise WorkflowValidationError("items_from resolved to an empty array")
    if len(value) > MAX_FANOUT_ITEMS:
        raise WorkflowValidationError(
            f"items_from resolved to {len(value)} items; max is {MAX_FANOUT_ITEMS}"
        )
    items: list[str] = []
    for entry in value:
        if isinstance(entry, str):
            items.append(entry)
        elif isinstance(entry, (dict, list)):
            items.append(json.dumps(entry, ensure_ascii=False))
        elif entry is None:
            items.append("null")
        else:
            items.append(str(entry))
    return items


def resolve_fanout_items_from_output(
    output: StepOutput,
    items_from: ItemsFrom,
) -> list[str]:
    """Resolve dynamic fanout items from a prior step output."""
    root = output.structured
    if root is None:
        text = (output.text or "").strip()
        if not text:
            raise WorkflowValidationError(
                f"items_from step {items_from.step!r} has no structured output"
            )
        try:
            root = json.loads(text)
        except json.JSONDecodeError as exc:
            raise WorkflowValidationError(
                f"items_from step {items_from.step!r}: text is not valid JSON"
            ) from exc
    resolved = resolve_simple_json_path(root, items_from.path)
    return coerce_fanout_items(resolved)


def _fanout_agent_from_flat_step(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Accept the common shorthand where fanout agent fields are on the step.

    The canonical IR keeps per-item agent config under ``step.agent``. LLMs
    often flatten ``label_template`` / ``prompt_template`` onto the fanout step,
    so normalize that shape before validation instead of failing the whole tool
    call with ``fanout.agent required``.
    """
    keys = (
        "label",
        "label_template",
        "agent_type",
        "model",
        "allowed_tools",
        "prompt",
        "prompt_template",
        "output_schema",
    )
    agent = {key: raw[key] for key in keys if key in raw}
    return agent or None


def _parse_agent_config(raw: dict[str, Any]) -> AgentStepConfig:
    prompt = raw.get("prompt")
    prompt_template = raw.get("prompt_template")
    if prompt is not None and not isinstance(prompt, str):
        raise WorkflowValidationError("agent.prompt must be a string")
    if prompt_template is not None and not isinstance(prompt_template, str):
        raise WorkflowValidationError("agent.prompt_template must be a string")
    return AgentStepConfig(
        label=raw.get("label"),
        label_template=raw.get("label_template"),
        agent_type=str(raw.get("agent_type") or raw.get("type") or "general"),
        model=raw.get("model"),
        allowed_tools=_parse_allowed(raw.get("allowed_tools")),
        prompt=raw.get("prompt"),
        prompt_template=raw.get("prompt_template"),
        output_schema=_parse_schema(raw.get("output_schema")),
        timeout_seconds=_parse_int_opt(
            raw.get("timeout_seconds"),
            "agent.timeout_seconds",
            min_val=1,
            max_val=3600,
        ),
    )


def _parse_allowed(raw: Any) -> list[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise WorkflowValidationError("allowed_tools must be an array")
    return [str(x) for x in raw]


def _parse_schema(raw: Any) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise WorkflowValidationError("output_schema must be an object")
    return raw


def _parse_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise WorkflowValidationError(f"{field} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise WorkflowValidationError(f"{field} must be an integer") from exc


def _parse_int_opt(
    value: Any, field: str, *, min_val: int, max_val: int
) -> int | None:
    """Parse an optional int with an inclusive range; None stays None."""
    if value is None:
        return None
    parsed = _parse_int(value, field)
    if parsed < min_val or parsed > max_val:
        raise WorkflowValidationError(
            f"{field} must be between {min_val} and {max_val}"
        )
    return parsed


def _collect_step_ids(step: WorkflowStep) -> list[str]:
    if step.type == "loop":
        return [step.id, *[sid for s in step.steps for sid in _collect_step_ids(s)]]
    if step.type == "dag":
        return [step.id, *[sid for s in step.nodes for sid in _collect_step_ids(s)]]
    return [step.id]


def _validate_graph_output_refs(graph: Any) -> None:
    """Topo-order template / items_from validation for a CompiledGraph."""
    from deepseek_tui.workflow.dag import CompiledGraph

    assert isinstance(graph, CompiledGraph)
    # Kahn order
    indeg = {nid: len(preds) for nid, preds in graph.predecessors.items()}
    queue = [nid for nid, d in indeg.items() if d == 0]
    prior: set[str] = set()
    while queue:
        nid = queue.pop()
        step = graph.nodes[nid]
        if step.type == "loop":
            visible = set(prior)
            for body_step in step.steps:
                _check_step_templates(body_step, visible, graph.nodes.keys())
                visible.add(body_step.id)
                prior.add(body_step.id)
        else:
            _check_step_templates(step, prior, graph.nodes.keys())
        prior.add(nid)
        for succ in graph.successors.get(nid, ()):
            indeg[succ] -= 1
            if indeg[succ] == 0:
                queue.append(succ)


def _check_step_templates(
    step: WorkflowStep, visible: set[str], all_ids: Any
) -> None:
    step_ids = set(all_ids)
    for template in _step_templates(step):
        for ref in _extract_output_refs(template):
            if ref not in step_ids and ref not in visible:
                # Allow refs to known graph ids even if not yet visible when
                # reduce wires from explicitly — still enforce topo when possible.
                if ref not in step_ids:
                    raise WorkflowValidationError(
                        f"step {step.id} references unknown output {ref}"
                    )
            if ref in step_ids and ref not in visible and step.type not in ("dynamic",):
                raise WorkflowValidationError(
                    f"step {step.id} references {ref} before it runs"
                )
    if step.type == "fanout" and step.items_from is not None:
        source = step.items_from.step
        if source not in step_ids:
            raise WorkflowValidationError(
                f"step {step.id} items_from references unknown step {source}"
            )
        if source not in visible:
            raise WorkflowValidationError(
                f"step {step.id} items_from references {source} before it runs"
            )
    if step.type == "reduce":
        for source in step.from_steps:
            if source not in step_ids:
                raise WorkflowValidationError(
                    f"step {step.id} from references unknown step {source}"
                )


def _validate_output_refs(phases: list[WorkflowPhase], step_ids: set[str]) -> None:
    prior: set[str] = set()

    def _check_templates(step: WorkflowStep, visible: set[str]) -> None:
        _check_step_templates(step, visible, step_ids)

    for phase in phases:
        for step in phase.steps:
            if step.type == "loop":
                visible = set(prior)
                for body_step in step.steps:
                    _check_templates(body_step, visible)
                    visible.add(body_step.id)
                    prior.add(body_step.id)
                prior.add(step.id)
            elif step.type == "dag":
                visible = set(prior)
                for body_step in step.nodes:
                    _check_templates(body_step, visible)
                    visible.add(body_step.id)
                    prior.add(body_step.id)
                prior.add(step.id)
            else:
                _check_templates(step, prior)
                prior.add(step.id)


def _step_templates(step: WorkflowStep) -> list[str]:
    if step.type == "agent":
        return [step.prompt]
    if step.type == "fanout":
        return [
            value
            for value in (step.agent.prompt, step.agent.prompt_template)
            if isinstance(value, str)
        ]
    if step.type == "pipeline":
        return [stage.prompt_template for stage in step.stages]
    if step.type in ("synthesis", "reduce"):
        return [step.prompt_template]
    return []


def _extract_output_refs(template: str) -> list[str]:
    refs = re.findall(r"\{\{outputs\.([a-zA-Z0-9_\-]+)(?:\.full)?\}\}", template)
    return list(refs)


# JSON-serializable views of workflow runtime state.


def snapshot_to_dict(snapshot: WorkflowSnapshot) -> dict[str, Any]:
    """Convert a snapshot for SSE / ToolResult metadata."""
    data = asdict(snapshot)
    data["agents"] = [asdict(a) for a in snapshot.agents]
    return data


# Template rendering for workflow prompts.

_OUTPUT_PREVIEW_RE = re.compile(
    r"\{\{outputs\.([a-zA-Z0-9_\-]+)\}\}"
)
_OUTPUT_FULL_RE = re.compile(
    r"\{\{outputs\.([a-zA-Z0-9_\-]+)\.full\}\}"
)
_OUTPUTS_INDEX_RE = re.compile(r"\{\{outputs\}\}")


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def make_preview(text: str, *, limit: int = PREVIEW_MAX_PER_STEP) -> str:
    line = text.replace("\n", " ").strip()
    return truncate_text(line, limit)


def make_step_output(text: str, structured: Any | None = None) -> StepOutput:
    preview = make_preview(text if text else "(empty)")
    return StepOutput(text=text, structured=structured, preview=preview)


def step_output_to_dict(out: StepOutput) -> dict[str, Any]:
    return {
        "text": out.text,
        "structured": out.structured,
        "preview": out.preview,
    }


def step_output_from_dict(raw: dict[str, Any]) -> StepOutput:
    return StepOutput(
        text=str(raw.get("text") or ""),
        structured=raw.get("structured"),
        preview=str(raw.get("preview") or make_preview(str(raw.get("text") or ""))),
    )


def evaluate_loop_until(
    until: LoopUntil,
    *,
    outputs: dict[str, StepOutput],
    body: list[WorkflowStep],
) -> bool:
    """Return True when the until condition is satisfied."""
    step_id = until.step or (body[-1].id if body else "")
    if not step_id:
        return False
    out = outputs.get(step_id)
    if out is None:
        return False
    root = out.structured
    if root is None:
        text = (out.text or "").strip()
        if not text:
            return False
        try:
            root = json.loads(text)
        except json.JSONDecodeError:
            return False
    try:
        value = resolve_simple_json_path(root, until.path)
    except WorkflowValidationError:
        return False
    return value == until.equals


def render_template(
    template: str,
    *,
    item: str | None = None,
    previous: StepOutput | None = None,
    outputs: dict[str, StepOutput] | None = None,
    task: str | None = None,
    round: int | None = None,
) -> str:
    text = template
    if task is not None:
        text = text.replace("{{task}}", task)
    else:
        text = text.replace("{{task}}", "")
    if round is not None:
        text = text.replace("{{round}}", str(round))
    else:
        text = text.replace("{{round}}", "")
    if item is not None:
        text = text.replace("{{item}}", item)
    if previous is not None:
        text = text.replace("{{previous}}", previous.preview)
    if outputs is not None:

        def full_sub(match: re.Match[str]) -> str:
            sid = match.group(1)
            out = outputs.get(sid)
            if out is None:
                return f"(missing output: {sid})"
            return truncate_text(out.text, FULL_TEXT_MAX)

        def preview_sub(match: re.Match[str]) -> str:
            sid = match.group(1)
            out = outputs.get(sid)
            if out is None:
                return f"(missing output: {sid})"
            return out.preview

        text = _OUTPUT_FULL_RE.sub(full_sub, text)
        text = _OUTPUT_PREVIEW_RE.sub(preview_sub, text)
        if "{{outputs}}" in text:
            lines = []
            for sid, out in outputs.items():
                lines.append(f"- {sid}: {truncate_text(out.preview, PREVIEW_MAX_FANOUT_ITEM)}")
            text = _OUTPUTS_INDEX_RE.sub("\n".join(lines) if lines else "(no outputs)", text)
    return text


# analysis_only — forced read-only tool allowlist
ANALYSIS_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        "read_file",
        "list_dir",
        "grep_files",
        "file_search",
        "git_status",
        "git_diff",
        "git_log",
        "git_show",
        "git_blame",
        "diagnostics",
        "project_map",
        "retrieve_tool_result",
        "checklist_list",
        "web_search",
        "fetch_url",
    }
)
