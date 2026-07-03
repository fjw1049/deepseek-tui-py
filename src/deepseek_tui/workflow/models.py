"""Workflow models, validation, serialization, templates, constants.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal


class WorkflowAbortedError(Exception):
    pass


class WorkflowFailedError(Exception):
    pass


StepType = Literal["agent", "fanout", "pipeline", "synthesis"]
ApprovalMode = Literal["analysis_only", "trusted_workflow", "strict"]
OnErrorMode = Literal["continue", "fail_fast"]
AgentRunStatus = Literal["queued", "running", "done", "error", "skipped"]


@dataclass(slots=True)
class WorkflowMeta:
    name: str
    description: str


@dataclass(slots=True)
class WorkflowPolicy:
    approval_mode: ApprovalMode = "trusted_workflow"
    on_error: OnErrorMode = "continue"
    max_agents: int = 10
    concurrency: int = 4
    wall_clock_seconds: int = 600
    token_budget: int | None = None


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


@dataclass(slots=True)
class FanoutStep:
    id: str
    type: Literal["fanout"]
    items: list[str]
    agent: AgentStepConfig
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


WorkflowStep = AgentStep | FanoutStep | PipelineStep | SynthesisStep


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
    phases: list[WorkflowPhase]


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


# Parse and validate Workflow IR JSON.



class WorkflowValidationError(ValueError):
    pass


def parse_workflow_spec(raw: Any) -> WorkflowSpec:
    """Parse tool input into a validated WorkflowSpec."""
    if not isinstance(raw, dict):
        raise WorkflowValidationError("workflow spec must be a JSON object")
    if raw.get("spec") is not None and isinstance(raw.get("spec"), dict):
        raw = raw["spec"]
    version = raw.get("version", 1)
    if version != 1:
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
    phases_raw = raw.get("phases")
    if not isinstance(phases_raw, list) or not phases_raw:
        raise WorkflowValidationError("phases must be a non-empty array")

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
            if step.id in step_ids:
                raise WorkflowValidationError(f"duplicate step id: {step.id}")
            step_ids.add(step.id)
            if step.type in ("agent", "synthesis", "fanout"):
                agent_step_count += 1
            elif step.type == "pipeline":
                agent_step_count += len(step.stages) * max(1, len(step.items))
            steps.append(step)
        phases.append(WorkflowPhase(id=phase_id.strip(), title=title.strip(), steps=steps))

    if agent_step_count == 0:
        raise WorkflowValidationError("workflow must include at least one agent step")

    _validate_output_refs(phases, step_ids)
    return WorkflowSpec(version=1, meta=meta, policy=policy, phases=phases)


def _parse_policy(raw: dict[str, Any]) -> WorkflowPolicy:
    if not isinstance(raw, dict):
        raise WorkflowValidationError("policy must be an object")
    mode = raw.get("approval_mode", "trusted_workflow")
    if mode not in ("analysis_only", "trusted_workflow", "strict"):
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
        )
    if step_type == "fanout":
        items = raw.get("items")
        if not isinstance(items, list) or not items:
            raise WorkflowValidationError(f"step {step_id}: fanout.items required")
        if len(items) > MAX_FANOUT_ITEMS:
            raise WorkflowValidationError(
                f"step {step_id}: fanout.items exceeds max {MAX_FANOUT_ITEMS}"
            )
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
            items=[str(x) for x in items],
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
        )
    raise WorkflowValidationError(f"step {step_id}: unknown type {step_type!r}")


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


def _validate_output_refs(phases: list[WorkflowPhase], step_ids: set[str]) -> None:
    ordered: list[WorkflowStep] = [s for p in phases for s in p.steps]
    prior: set[str] = set()
    for step in ordered:
        for template in _step_templates(step):
            for ref in _extract_output_refs(template):
                if ref not in step_ids:
                    raise WorkflowValidationError(
                        f"step {step.id} references unknown output {ref}"
                    )
                if ref not in prior:
                    raise WorkflowValidationError(
                        f"step {step.id} references {ref} before it runs"
                    )
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
    if step.type == "synthesis":
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


PREVIEW_MAX_PER_STEP = 2000
PREVIEW_MAX_FANOUT_ITEM = 800
FULL_TEXT_MAX = 32_768
DEFAULT_WALL_CLOCK_SECONDS = 600
DEFAULT_CONCURRENCY = 4
DEFAULT_MAX_AGENTS = 10


def make_preview(text: str, *, limit: int = PREVIEW_MAX_PER_STEP) -> str:
    line = text.replace("\n", " ").strip()
    return truncate_text(line, limit)


def make_step_output(text: str, structured: Any | None = None) -> StepOutput:
    preview = make_preview(text if text else "(empty)")
    return StepOutput(text=text, structured=structured, preview=preview)


def render_template(
    template: str,
    *,
    item: str | None = None,
    previous: StepOutput | None = None,
    outputs: dict[str, StepOutput] | None = None,
) -> str:
    text = template
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


# (constants moved above make_preview)
MAX_FANOUT_ITEMS = 16
WAIT_TIMEOUT_MS = 3_600_000

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
