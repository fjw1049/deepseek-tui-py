"""DAG compile, validation, and ready-set helpers for workflow v2."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from deepseek_tui.workflow.models import (
    AgentStep,
    DagStep,
    DynamicStep,
    FanoutStep,
    LoopStep,
    PipelineStep,
    ReduceStep,
    SupportStep,
    SynthesisStep,
    WorkflowPhase,
    WorkflowSpec,
    WorkflowStep,
    WorkflowValidationError,
)


@dataclass(slots=True)
class GraphEdge:
    from_id: str
    to_id: str


@dataclass
class CompiledGraph:
    """Executable DAG: nodes keyed by id + directed edges."""

    nodes: dict[str, WorkflowStep]
    edges: list[GraphEdge] = field(default_factory=list)
    predecessors: dict[str, set[str]] = field(default_factory=dict)
    successors: dict[str, set[str]] = field(default_factory=dict)
    phase_of: dict[str, str] = field(default_factory=dict)
    phase_titles: dict[str, str] = field(default_factory=dict)

    def root_ids(self) -> list[str]:
        return [nid for nid, preds in self.predecessors.items() if not preds]

    def ready_ids(self, completed: set[str], failed: set[str], skipped: set[str]) -> list[str]:
        """Nodes whose predecessors are all terminal enough to run.

        - Default: every predecessor completed or skipped.
        - ``reduce``/``synthesis`` with ``source_policy=partial`` (default for
          reduce): failed predecessors also count as terminal so a join can
          still run with available outputs.
        """
        terminal_ok = completed | skipped
        ready: list[str] = []
        for nid, preds in self.predecessors.items():
            if nid in terminal_ok or nid in failed or nid in skipped:
                continue
            if not preds:
                ready.append(nid)
                continue
            step = self.nodes.get(nid)
            accepts_partial = (
                isinstance(step, (ReduceStep, SynthesisStep))
                and step.source_policy == "partial"
            )
            if accepts_partial:
                if all(p in terminal_ok or p in failed for p in preds) and any(
                    p in completed for p in preds
                ):
                    ready.append(nid)
            elif all(p in terminal_ok for p in preds):
                ready.append(nid)
        return ready

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {nid: step_to_dict(step) for nid, step in self.nodes.items()},
            "edges": [{"from": e.from_id, "to": e.to_id} for e in self.edges],
            "phase_of": dict(self.phase_of),
            "phase_titles": dict(self.phase_titles),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CompiledGraph:
        from deepseek_tui.workflow.models import step_from_dict

        nodes_raw = raw.get("nodes") or {}
        if not isinstance(nodes_raw, dict):
            raise WorkflowValidationError("graph.nodes must be an object")
        nodes: dict[str, WorkflowStep] = {}
        for nid, nraw in nodes_raw.items():
            step = step_from_dict(nraw if isinstance(nraw, dict) else {}, fallback_id=str(nid))
            nodes[step.id] = step
        edges: list[GraphEdge] = []
        for eraw in raw.get("edges") or []:
            if not isinstance(eraw, dict):
                continue
            fr, to = eraw.get("from"), eraw.get("to")
            if isinstance(fr, str) and isinstance(to, str):
                edges.append(GraphEdge(from_id=fr, to_id=to))
        g = build_adjacency(nodes, edges)
        phase_of = {
            str(k): str(v)
            for k, v in (raw.get("phase_of") or {}).items()
            if isinstance(k, str)
        }
        phase_titles = {
            str(k): str(v)
            for k, v in (raw.get("phase_titles") or {}).items()
            if isinstance(k, str)
        }
        g.phase_of = phase_of
        g.phase_titles = phase_titles
        return g


def build_adjacency(
    nodes: dict[str, WorkflowStep], edges: list[GraphEdge]
) -> CompiledGraph:
    predecessors: dict[str, set[str]] = {nid: set() for nid in nodes}
    successors: dict[str, set[str]] = {nid: set() for nid in nodes}
    for edge in edges:
        if edge.from_id not in nodes:
            raise WorkflowValidationError(
                f"edge from unknown node {edge.from_id!r}"
            )
        if edge.to_id not in nodes:
            raise WorkflowValidationError(f"edge to unknown node {edge.to_id!r}")
        predecessors[edge.to_id].add(edge.from_id)
        successors[edge.from_id].add(edge.to_id)
    return CompiledGraph(
        nodes=nodes,
        edges=list(edges),
        predecessors=predecessors,
        successors=successors,
    )


def assert_acyclic(graph: CompiledGraph) -> None:
    """Kahn's algorithm — raise if a cycle exists in the static graph."""
    indeg = {nid: len(preds) for nid, preds in graph.predecessors.items()}
    queue = [nid for nid, d in indeg.items() if d == 0]
    seen = 0
    while queue:
        nid = queue.pop()
        seen += 1
        for succ in graph.successors.get(nid, ()):
            indeg[succ] -= 1
            if indeg[succ] == 0:
                queue.append(succ)
    if seen != len(graph.nodes):
        raise WorkflowValidationError("workflow graph contains a cycle")


def remove_node(graph: CompiledGraph, node_id: str) -> None:
    """Drop a node and all incident edges (used by dynamic replan)."""
    if node_id not in graph.nodes:
        return
    del graph.nodes[node_id]
    preds = graph.predecessors.pop(node_id, set())
    succs = graph.successors.pop(node_id, set())
    for pred in preds:
        graph.successors.get(pred, set()).discard(node_id)
    for succ in succs:
        graph.predecessors.get(succ, set()).discard(node_id)
    graph.edges = [
        e for e in graph.edges if e.from_id != node_id and e.to_id != node_id
    ]
    graph.phase_of.pop(node_id, None)


def compile_phases_to_graph(phases: list[WorkflowPhase]) -> CompiledGraph:
    """Lower v1 phase/step lists into a sequential DAG (compatible sugar)."""
    nodes: dict[str, WorkflowStep] = {}
    edges: list[GraphEdge] = []
    phase_of: dict[str, str] = {}
    phase_titles: dict[str, str] = {}
    prev_id: str | None = None

    for phase in phases:
        phase_titles[phase.id] = phase.title
        for step in phase.steps:
            if step.id in nodes:
                raise WorkflowValidationError(f"duplicate step id: {step.id}")
            nodes[step.id] = step
            phase_of[step.id] = phase.id
            if prev_id is not None:
                edges.append(GraphEdge(from_id=prev_id, to_id=step.id))
            prev_id = step.id
            # Loop body ids are nested; keep them off the top-level schedule —
            # the loop executor owns them. Same as v1 runtime.

    graph = build_adjacency(nodes, edges)
    graph.phase_of = phase_of
    graph.phase_titles = phase_titles
    assert_acyclic(graph)
    return graph


def compile_workflow_graph(spec: WorkflowSpec) -> CompiledGraph:
    """Return the executable graph for a parsed spec (v1 or v2)."""
    if spec.compiled_graph is not None:
        return spec.compiled_graph
    if spec.phases:
        return compile_phases_to_graph(spec.phases)
    raise WorkflowValidationError("workflow has neither phases nor graph")


def add_node(
    graph: CompiledGraph,
    step: WorkflowStep,
    *,
    after: Iterable[str] = (),
    phase_id: str = "dynamic",
    phase_title: str = "Dynamic",
    require_preds_exist: bool = False,
) -> None:
    """Mutate *graph* by inserting a generated node (dynamic controller)."""
    if step.id in graph.nodes:
        raise WorkflowValidationError(f"node id already exists: {step.id}")
    preds = [p for p in after if p and p != step.id]
    if require_preds_exist:
        missing = [p for p in preds if p not in graph.nodes]
        if missing:
            raise WorkflowValidationError(
                f"node {step.id}: unknown predecessor(s) {missing!r}; "
                "after/from must name existing nodes or earlier ids in this batch"
            )
    graph.nodes[step.id] = step
    graph.predecessors[step.id] = set()
    graph.successors[step.id] = set()
    graph.phase_of[step.id] = phase_id
    graph.phase_titles.setdefault(phase_id, phase_title)
    for pred in preds:
        if pred in graph.nodes:
            graph.predecessors[step.id].add(pred)
            graph.successors.setdefault(pred, set()).add(step.id)
            graph.edges.append(GraphEdge(from_id=pred, to_id=step.id))
        elif not require_preds_exist:
            # Legacy soft-admit path (should be rare); still records the pred so
            # readiness stays blocked until something else completes it — prefer
            # require_preds_exist=True for dynamic mutations.
            graph.predecessors[step.id].add(pred)


def step_to_dict(step: WorkflowStep) -> dict[str, Any]:
    """Serialize a step for checkpoint / v2 graph storage."""
    base: dict[str, Any] = {"id": step.id, "type": step.type}
    if step.type == "agent":
        base.update(
            {
                "label": step.label,
                "agent_type": step.agent_type,
                "model": step.model,
                "allowed_tools": step.allowed_tools,
                "prompt": step.prompt,
                "output_schema": step.output_schema,
                "timeout_seconds": step.timeout_seconds,
            }
        )
    elif step.type == "fanout":
        base.update(
            {
                "items": step.items,
                "items_from": (
                    {"step": step.items_from.step, "path": step.items_from.path}
                    if step.items_from
                    else None
                ),
                "concurrency": step.concurrency,
                "agent": {
                    "label": step.agent.label,
                    "label_template": step.agent.label_template,
                    "agent_type": step.agent.agent_type,
                    "model": step.agent.model,
                    "allowed_tools": step.agent.allowed_tools,
                    "prompt": step.agent.prompt,
                    "prompt_template": step.agent.prompt_template,
                    "output_schema": step.agent.output_schema,
                    "timeout_seconds": step.agent.timeout_seconds,
                },
            }
        )
    elif step.type == "pipeline":
        base.update(
            {
                "items": step.items,
                "stages": [
                    {
                        "label_template": s.label_template,
                        "agent_type": s.agent_type,
                        "model": s.model,
                        "prompt_template": s.prompt_template,
                    }
                    for s in step.stages
                ],
            }
        )
    elif step.type == "synthesis":
        base.update(
            {
                "label": step.label,
                "agent_type": step.agent_type,
                "model": step.model,
                "allowed_tools": step.allowed_tools,
                "prompt_template": step.prompt_template,
                "output_schema": step.output_schema,
                "timeout_seconds": step.timeout_seconds,
                "source_policy": step.source_policy,
            }
        )
    elif step.type == "reduce":
        base.update(
            {
                "label": step.label,
                "from": list(step.from_steps),
                "agent_type": step.agent_type,
                "model": step.model,
                "allowed_tools": step.allowed_tools,
                "prompt_template": step.prompt_template,
                "output_schema": step.output_schema,
                "timeout_seconds": step.timeout_seconds,
                "source_policy": step.source_policy,
            }
        )
    elif step.type == "loop":
        base.update(
            {
                "max_rounds": step.max_rounds,
                "steps": [step_to_dict(s) for s in step.steps],
                "until": (
                    {
                        "path": step.until.path,
                        "equals": step.until.equals,
                        "step": step.until.step,
                    }
                    if step.until
                    else None
                ),
            }
        )
    elif step.type == "dag":
        base.update(
            {
                "nodes": [step_to_dict(s) for s in step.nodes],
                "edges": [{"from": e[0], "to": e[1]} for e in step.edges],
                "output_from": step.output_from,
            }
        )
    elif step.type == "dynamic":
        base.update(
            {
                "controller": {
                    "agent_type": step.controller_agent_type,
                    "model": step.controller_model,
                    "allowed_tools": step.controller_allowed_tools,
                },
                "budget": {
                    "max_decision_rounds": step.budget.max_decision_rounds,
                    "max_agents": step.budget.max_agents,
                    "max_mutations": step.budget.max_mutations,
                    "max_fanout_items": step.budget.max_fanout_items,
                    "max_nested_dynamic_depth": step.budget.max_nested_dynamic_depth,
                    "wall_clock_seconds": step.budget.wall_clock_seconds,
                },
                "permissions": {
                    "actions": list(step.permissions.actions),
                    "allow_nested_workflow": step.permissions.allow_nested_workflow,
                    "allow_write_tools": step.permissions.allow_write_tools,
                },
                "context": {
                    "include_outputs": list(step.context_include_outputs),
                    "max_context_chars": step.max_context_chars,
                },
            }
        )
    elif step.type == "support":
        base.update(
            {
                "uses": step.uses,
                "from": list(step.from_steps),
                "options": dict(step.options),
            }
        )
    return base
