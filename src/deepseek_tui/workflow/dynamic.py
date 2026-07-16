"""Dynamic workflow controller: decision loop + graph mutations."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from deepseek_tui.workflow.dag import (
    CompiledGraph,
    GraphEdge,
    add_node,
    assert_acyclic,
    remove_node,
    step_to_dict,
)
from deepseek_tui.workflow.models import (
    AgentStep,
    AgentStepConfig,
    DYNAMIC_ACTIONS,
    DynamicStep,
    FanoutStep,
    ItemsFrom,
    ReduceStep,
    SupportStep,
    SynthesisStep,
    WorkflowFailedError,
    WorkflowRunContext,
    WorkflowValidationError,
    make_step_output,
    parse_workflow_spec,
    step_from_dict,
)

# Actions that schedule new graph work (incompatible with stop / replan).
_WORK_ACTIONS = frozenset(
    {"spawn", "fanout", "reduce", "support", "splice_dag", "nested_workflow"}
)

DECISION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": sorted(DYNAMIC_ACTIONS),
                    },
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "agent_type": {"type": "string"},
                    "prompt": {"type": "string"},
                    "prompt_template": {"type": "string"},
                    "after": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "from": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "items": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "items_from": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string"},
                            "path": {"type": "string"},
                        },
                    },
                    "uses": {"type": "string"},
                    "options": {"type": "object"},
                    "nodes": {"type": "array"},
                    "edges": {"type": "array"},
                    "workflow_name": {"type": "string"},
                    "spec": {"type": "object"},
                    "output_schema": {"type": "object"},
                    "reason": {"type": "string"},
                    "success": {"type": "boolean"},
                },
                "required": ["action"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["actions"],
}


def decision_loop_signature(decision: dict[str, Any]) -> str:
    """Stable fingerprint of a decision for stall / repeat detection."""
    actions = decision.get("actions")
    if not isinstance(actions, list):
        actions = []
    normalized: list[dict[str, Any]] = []
    for raw in actions:
        if not isinstance(raw, dict):
            continue
        entry: dict[str, Any] = {
            "action": str(raw.get("action") or "").strip(),
        }
        for key in (
            "id",
            "prompt",
            "prompt_template",
            "after",
            "from",
            "items",
            "items_from",
            "uses",
            "workflow_name",
            "success",
        ):
            if key in raw:
                entry[key] = raw[key]
        normalized.append(entry)
    blob = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def validate_decision(
    decision: dict[str, Any],
    *,
    step: DynamicStep,
    previous_signatures: list[str] | None = None,
) -> str:
    """Validate controller decision invariants; return signature.

    Guards (lightweight — not full event-sourcing):
    - ``actions`` non-empty array of objects with known/permitted actions
    - ``stop`` must be the sole action when present
    - ``synthesize`` may follow same-batch work but must be last (and unique)
    - ``replan`` cannot share a batch with new work actions
    - identical consecutive decision signatures are rejected (stall)
    """
    actions = decision.get("actions")
    if not isinstance(actions, list) or not actions:
        raise WorkflowValidationError(
            "dynamic decision.actions must be a non-empty array"
        )

    allowed = set(step.permissions.actions)
    kinds: list[str] = []
    for i, action_raw in enumerate(actions):
        if not isinstance(action_raw, dict):
            raise WorkflowValidationError(f"action[{i}] must be an object")
        action = str(action_raw.get("action") or "").strip()
        if action not in DYNAMIC_ACTIONS:
            raise WorkflowValidationError(f"unknown action {action!r}")
        if action not in allowed:
            raise WorkflowValidationError(f"action {action!r} not permitted")
        kinds.append(action)

    kind_set = set(kinds)
    if "stop" in kind_set and len(kinds) != 1:
        raise WorkflowValidationError(
            "stop must be the only action in a decision batch"
        )
    if "synthesize" in kind_set:
        if kinds.count("synthesize") != 1 or kinds[-1] != "synthesize":
            raise WorkflowValidationError(
                "synthesize must be the last (and only synthesize) action "
                "in a decision batch"
            )
    if "replan" in kind_set and kind_set & _WORK_ACTIONS:
        raise WorkflowValidationError(
            "replan cannot be combined with new work actions in the same batch"
        )

    signature = decision_loop_signature(decision)
    prev = previous_signatures or []
    if prev and prev[-1] == signature:
        raise WorkflowFailedError(
            "dynamic controller repeated the same decision (stall detected)"
        )
    return signature


def build_controller_prompt(
    step: DynamicStep,
    *,
    task: str,
    graph: CompiledGraph,
    ctx: WorkflowRunContext,
    round_idx: int,
) -> str:
    budget = step.budget
    used_mutations = ctx.budgets_used.get("mutations", 0)
    used_agents = len(ctx.spawned_agent_ids)
    agents_left = max(0, budget.max_agents - used_agents)
    include = step.context_include_outputs or ["*"]
    allow_all = "*" in include
    include_set = set(include)

    node_summaries: list[str] = []
    for nid, node in list(graph.nodes.items())[:80]:
        if nid == step.id:
            status = "running"
        elif nid in ctx.completed_step_ids:
            status = "done"
        elif nid in ctx.failed_step_ids:
            status = "failed"
        elif nid in ctx.skipped_step_ids:
            status = "skipped"
        else:
            status = "pending"
        preview = ""
        if nid in ctx.outputs:
            preview = ctx.outputs[nid].preview[:200]
        node_summaries.append(
            f"- {nid} ({node.type}) [{status}] preds={sorted(graph.predecessors.get(nid, []))} {preview}"
        )

    output_lines: list[str] = []
    used_chars = 0
    max_chars = max(1024, int(step.max_context_chars or 48_000))
    for sid, out in ctx.outputs.items():
        if not allow_all and sid not in include_set:
            continue
        line = f"- {sid}: {out.preview[:160]}"
        # Keep room for header / node list; outputs get the configured budget.
        if used_chars + len(line) + 1 > max_chars:
            output_lines.append("…(outputs truncated by max_context_chars)")
            break
        output_lines.append(line)
        used_chars += len(line) + 1

    return (
        "You are a workflow dynamic controller. Decide the next graph mutations.\n"
        f"Runtime task:\n{task}\n\n"
        f"Decision round {round_idx}/{budget.max_decision_rounds}.\n"
        f"Budgets left: agents≈{agents_left}, "
        f"mutations≈{max(0, budget.max_mutations - used_mutations)}, "
        f"max_fanout_items={budget.max_fanout_items}.\n"
        f"Allowed actions: {', '.join(step.permissions.actions)}.\n"
        "Return structured JSON with an actions array.\n"
        "Closed loop: after each decision the runtime RUNS newly ready spawned "
        "nodes to completion, then calls you again with their outputs.\n"
        "Prefer: spawn/fanout to gather evidence, observe results next round, "
        "then synthesize or stop. Use replan to drop unfinished generated work "
        "and rethink while keeping completed outputs.\n"
        "Do NOT put this controller node id in after/from — spawned work is "
        "ready immediately unless you name other work-node predecessors.\n"
        "after/from must reference existing nodes or ids created earlier in "
        "THIS actions batch.\n\n"
        "Current graph nodes:\n"
        + "\n".join(node_summaries)
        + "\n\nOutputs index:\n"
        + ("\n".join(output_lines) if output_lines else "(none)")
    )

def apply_decision_actions(
    step: DynamicStep,
    decision: dict[str, Any],
    *,
    graph: CompiledGraph,
    ctx: WorkflowRunContext,
    round_idx: int,
    parent_id: str,
) -> dict[str, Any]:
    """Apply controller actions; return control flags."""
    actions = decision.get("actions")
    if not isinstance(actions, list) or not actions:
        raise WorkflowValidationError("dynamic decision.actions must be a non-empty array")

    flags = {
        "stop": False,
        "stop_success": True,
        "synthesize_ids": [],
        "replan": False,
        "replan_dropped": [],
        "nested_specs": [],
        "new_node_ids": [],
    }
    allowed = set(step.permissions.actions)

    for i, action_raw in enumerate(actions):
        if not isinstance(action_raw, dict):
            raise WorkflowValidationError(f"action[{i}] must be an object")
        action = str(action_raw.get("action") or "").strip()
        if action not in DYNAMIC_ACTIONS:
            raise WorkflowValidationError(f"unknown action {action!r}")
        if action not in allowed:
            raise WorkflowValidationError(f"action {action!r} not permitted")

        used = ctx.budgets_used.get("mutations", 0)
        if used >= step.budget.max_mutations and action not in ("stop", "synthesize", "replan"):
            raise WorkflowFailedError("dynamic max_mutations exceeded")

        ns = f"dyn/{parent_id}/r{round_idx}"
        if action == "stop":
            flags["stop"] = True
            flags["stop_success"] = bool(action_raw.get("success", True))
            continue

        if action == "replan":
            flags["replan"] = True
            # Drop unfinished generated work; keep completed outputs.
            pending = [
                nid
                for nid in list(ctx.generated_node_ids)
                if nid not in ctx.completed_step_ids
                and nid not in ctx.failed_step_ids
                and nid != parent_id
            ]
            dropped: list[str] = []
            for nid in pending:
                if nid not in ctx.skipped_step_ids:
                    ctx.skipped_step_ids.append(nid)
                remove_node(graph, nid)
                dropped.append(nid)
            ctx.generated_node_ids = [
                nid for nid in ctx.generated_node_ids if nid not in dropped
            ]
            flags["replan_dropped"] = dropped
            ctx.budgets_used["mutations"] = used + 1
            continue

        if action == "nested_workflow":
            if not step.permissions.allow_nested_workflow:
                raise WorkflowValidationError("nested_workflow not permitted")
            if ctx.nested_dynamic_depth >= step.budget.max_nested_dynamic_depth:
                raise WorkflowFailedError("max_nested_dynamic_depth exceeded")
            name = action_raw.get("workflow_name")
            raw_spec = action_raw.get("spec")
            if isinstance(name, str) and name.strip():
                flags["nested_specs"].append({"name": name.strip()})
            elif isinstance(raw_spec, dict):
                flags["nested_specs"].append({"spec": raw_spec})
            else:
                raise WorkflowValidationError(
                    "nested_workflow requires workflow_name or spec"
                )
            ctx.budgets_used["mutations"] = used + 1
            continue

        node_id = str(action_raw.get("id") or f"{ns}/{action}_{i}").strip()
        after = _resolve_after(action_raw, parent_id=parent_id)

        if action == "spawn":
            prompt = str(action_raw.get("prompt") or action_raw.get("prompt_template") or "")
            if not prompt.strip():
                raise WorkflowValidationError("spawn requires prompt")
            new_step: Any = AgentStep(
                id=node_id,
                type="agent",
                label=str(action_raw.get("label") or node_id),
                agent_type=str(action_raw.get("agent_type") or "explore"),
                prompt=prompt,
                output_schema=action_raw.get("output_schema")
                if isinstance(action_raw.get("output_schema"), dict)
                else None,
            )
        elif action == "fanout":
            items = action_raw.get("items")
            items_from = action_raw.get("items_from")
            parsed_items = None
            parsed_from = None
            if isinstance(items, list) and items:
                if len(items) > step.budget.max_fanout_items:
                    raise WorkflowValidationError("fanout items exceed budget")
                parsed_items = [str(x) for x in items]
            elif isinstance(items_from, dict):
                src = items_from.get("step")
                path = items_from.get("path", "$")
                if not isinstance(src, str):
                    raise WorkflowValidationError("items_from.step required")
                parsed_from = ItemsFrom(step=src, path=str(path))
            else:
                raise WorkflowValidationError("fanout requires items or items_from")
            prompt_t = str(
                action_raw.get("prompt_template")
                or action_raw.get("prompt")
                or "Investigate {{item}} for task:\n{{task}}"
            )
            new_step = FanoutStep(
                id=node_id,
                type="fanout",
                items=parsed_items,
                items_from=parsed_from,
                agent=AgentStepConfig(
                    label_template=str(action_raw.get("label") or "inspect {{item}}"),
                    agent_type=str(action_raw.get("agent_type") or "explore"),
                    prompt_template=prompt_t,
                    output_schema=action_raw.get("output_schema")
                    if isinstance(action_raw.get("output_schema"), dict)
                    else None,
                ),
            )
        elif action in ("reduce", "synthesize"):
            from_steps = _resolve_join_from(
                action_raw,
                parent_id=parent_id,
                completed=ctx.completed_step_ids,
                batch_new=flags["new_node_ids"],
            )
            tmpl = str(
                action_raw.get("prompt_template")
                or action_raw.get("prompt")
                or "Synthesize upstream outputs for task:\n{{task}}\n\n{{outputs}}"
            )
            label = str(action_raw.get("label") or "synthesis")
            if action == "synthesize":
                new_step = SynthesisStep(
                    id=node_id,
                    type="synthesis",
                    label=label,
                    agent_type=str(action_raw.get("agent_type") or "review"),
                    prompt_template=tmpl,
                    output_schema=action_raw.get("output_schema")
                    if isinstance(action_raw.get("output_schema"), dict)
                    else None,
                )
                flags["synthesize_ids"].append(node_id)
                flags["stop"] = True
                flags["stop_success"] = True
            else:
                new_step = ReduceStep(
                    id=node_id,
                    type="reduce",
                    label=label,
                    from_steps=from_steps,
                    agent_type=str(action_raw.get("agent_type") or "review"),
                    prompt_template=tmpl,
                    output_schema=action_raw.get("output_schema")
                    if isinstance(action_raw.get("output_schema"), dict)
                    else None,
                )
            after = list(dict.fromkeys([*after, *from_steps]))
        elif action == "support":
            uses = str(action_raw.get("uses") or "").strip()
            if not uses:
                raise WorkflowValidationError("support requires uses")
            from_steps = _resolve_join_from(
                action_raw,
                parent_id=parent_id,
                completed=ctx.completed_step_ids,
                batch_new=flags["new_node_ids"],
                required=False,
            )
            new_step = SupportStep(
                id=node_id,
                type="support",
                uses=uses,
                from_steps=from_steps,
                options=dict(action_raw.get("options") or {})
                if isinstance(action_raw.get("options"), dict)
                else {},
            )
            after = list(dict.fromkeys([*after, *from_steps]))
        elif action == "splice_dag":
            nodes_raw = action_raw.get("nodes")
            if not isinstance(nodes_raw, list) or not nodes_raw:
                raise WorkflowValidationError("splice_dag requires nodes")
            for j, nraw in enumerate(nodes_raw):
                if not isinstance(nraw, dict):
                    continue
                child = step_from_dict(
                    {**nraw, "id": nraw.get("id") or f"{node_id}/n{j}"}
                )
                if "after" in nraw:
                    child_after = _resolve_after(nraw, parent_id=parent_id)
                elif j == 0:
                    child_after = list(after)
                else:
                    child_after = []
                add_node(
                    graph,
                    child,
                    after=child_after,
                    phase_id=f"dyn/{parent_id}",
                    phase_title="Dynamic",
                    require_preds_exist=True,
                )
                ctx.generated_node_ids.append(child.id)
                flags["new_node_ids"].append(child.id)
            for eraw in action_raw.get("edges") or []:
                if not isinstance(eraw, dict):
                    continue
                fr, to = eraw.get("from"), eraw.get("to")
                if (
                    isinstance(fr, str)
                    and isinstance(to, str)
                    and fr in graph.nodes
                    and to in graph.nodes
                ):
                    graph.edges.append(GraphEdge(from_id=fr, to_id=to))
                    graph.predecessors.setdefault(to, set()).add(fr)
                    graph.successors.setdefault(fr, set()).add(to)
            ctx.budgets_used["mutations"] = used + 1
            continue
        else:
            raise WorkflowValidationError(f"unhandled action {action!r}")

        add_node(
            graph,
            new_step,
            after=after,
            phase_id=f"dyn/{parent_id}",
            phase_title="Dynamic",
            require_preds_exist=True,
        )
        ctx.generated_node_ids.append(new_step.id)
        flags["new_node_ids"].append(new_step.id)
        ctx.budgets_used["mutations"] = ctx.budgets_used.get("mutations", 0) + 1

    # Mutations must keep the runtime graph a DAG.
    assert_acyclic(graph)
    return flags


def _resolve_after(action_raw: dict[str, Any], *, parent_id: str) -> list[str]:
    """Predecessor ids for a generated node.

    Default (missing ``after``): no hard deps — ready as soon as the mutation
    lands, so the controller can observe outputs in the *next* decision round.

    The live controller id is never a valid hard predecessor mid-loop; strip it
    if the model names it.
    """
    if "after" not in action_raw:
        return []
    after = _as_str_list(action_raw.get("after"))
    return [a for a in after if a != parent_id]


def _resolve_join_from(
    action_raw: dict[str, Any],
    *,
    parent_id: str,
    completed: list[str],
    batch_new: list[str],
    required: bool = True,
) -> list[str]:
    explicit = _as_str_list(action_raw.get("from"))
    if explicit:
        from_steps = [x for x in explicit if x != parent_id]
    else:
        # Prefer nodes created earlier in this decision batch, then completed work.
        from_steps = list(
            dict.fromkeys(
                [
                    *batch_new,
                    *[x for x in completed if x != parent_id][-8:],
                ]
            )
        )
    if required and not from_steps:
        raise WorkflowValidationError(
            "reduce/synthesize requires from=[...] or prior completed/spawned nodes"
        )
    return from_steps


def _as_str_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def parse_nested_spec(payload: dict[str, Any], *, cwd: Any = None) -> Any:
    """Resolve nested_workflow payload to WorkflowSpec."""
    if "spec" in payload and isinstance(payload["spec"], dict):
        return parse_workflow_spec(payload["spec"])
    name = payload.get("name")
    if isinstance(name, str) and name.strip():
        from deepseek_tui.workflow.catalog import resolve_workflow

        return resolve_workflow(name.strip(), cwd=cwd)
    raise WorkflowValidationError("nested_workflow payload invalid")
