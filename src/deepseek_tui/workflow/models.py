"""Workflow IR and runtime snapshot models."""

from __future__ import annotations

from dataclasses import dataclass, field
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
