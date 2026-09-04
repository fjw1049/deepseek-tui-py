"""Versioned data contracts shared by cases, runners, graders, and reports."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EvalCase(BaseModel):
    """One auditable evaluation scenario loaded from YAML."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    id: str
    suite: str
    risk: Literal["low", "medium", "high", "critical"] = "medium"
    runner: str
    grader: str
    live: bool = False
    tags: list[str] = Field(default_factory=list)
    related_paths: list[str] = Field(default_factory=list)
    setup: dict[str, Any] = Field(default_factory=dict)
    input: dict[str, Any] = Field(default_factory=dict)
    expect: dict[str, Any] = Field(default_factory=dict)
    source_file: str = ""

    @field_validator("id", "suite", "runner", "grader")
    @classmethod
    def _non_empty_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class EvalObservation(BaseModel):
    """Sanitizable evidence returned by a harness."""

    model_config = ConfigDict(extra="forbid")

    data: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    usage: dict[str, int | float] = Field(default_factory=dict)


class GradeResult(BaseModel):
    """Machine-readable verdict for one trial."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    metrics: dict[str, int | float | bool] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class TrialResult(BaseModel):
    """Persisted result for one case/trial pair."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    suite: str
    risk: str
    source_file: str = ""
    tags: list[str] = Field(default_factory=list)
    related_paths: list[str] = Field(default_factory=list)
    trial: int
    status: Literal["passed", "failed", "skipped", "error"]
    duration_ms: int
    grade: GradeResult | None = None
    observation: EvalObservation | None = None
    error: str | None = None


class RunManifest(BaseModel):
    """Identity of the code, dataset, prompt, tools, and model under test."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    run_id: str
    started_at: str
    git_commit: str
    dirty_diff_hash: str
    dataset_hash: str
    prompt_hash: str
    tool_catalog_hash: str
    python_version: str
    package_versions: dict[str, str] = Field(default_factory=dict)
    mode: Literal["offline", "live"]
    provider: str | None = None
    model: str | None = None
    trials: int = 1
    case_ids: list[str] = Field(default_factory=list)


class RunSummary(BaseModel):
    """Compact aggregate consumed by baseline comparison and CI."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    run_id: str
    completed_at: str
    total: int
    passed: int
    failed: int
    skipped: int
    errors: int
    metrics: dict[str, dict[str, int | float]] = Field(default_factory=dict)
