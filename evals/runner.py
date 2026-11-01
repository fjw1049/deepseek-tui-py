"""Case discovery, validation, execution, and durable artifact production."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from deepseek_tui.config.models import Config
from deepseek_tui.engine.prompts import AppMode, build_system_prompt
from deepseek_tui.tools.registry import build_default_registry
from evals.graders import GRADERS, grade
from evals.harness import HARNESSES, HarnessContext, run_harness
from evals.harness.budget import BudgetExceeded
from evals.harness.product import EnvironmentInvalid
from evals.report import append_result, summarize, write_json
from evals.rubric import CHECK_TYPES
from evals.schema import EvalCase, EvalObservation, RunManifest, RunSummary, TrialResult

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SUITES_ROOT = Path(__file__).resolve().parent / "suites"
DEFAULT_ARTIFACTS_ROOT = Path(__file__).resolve().parent / "artifacts"
_EVALUATED_PATHS = ("src", "evals", "contracts", "pyproject.toml", "uv.lock")
LIVE_RUNNERS = {"judge_probe", "live_decision", "live_cache", "product_session", "workspace_task"}


@dataclass(frozen=True, slots=True)
class RunOptions:
    mode: str = "offline"
    suites: tuple[str, ...] = ()
    provider: str | None = None
    model: str | None = None
    trials: int = 1
    max_cases: int | None = None
    max_live_requests: int = 20
    max_output_tokens: int = 2048
    max_cost_usd: float | None = None
    timeout_seconds: float = 120.0
    output_dir: Path | None = None
    case_ids: tuple[str, ...] = ()
    label: str = ""
    prompt_suffix: str = ""
    concurrency: int = 1
    judge_provider: str | None = None
    judge_model: str | None = None
    max_input_tokens: int | None = None


def load_cases(root: Path = DEFAULT_SUITES_ROOT) -> list[EvalCase]:
    cases: list[EvalCase] = []
    for path in sorted(root.rglob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        documents = raw if isinstance(raw, list) else [raw]
        for document in documents:
            if document is None:
                continue
            payload = dict(document)
            payload["source_file"] = path.relative_to(REPO_ROOT).as_posix()
            cases.append(EvalCase.model_validate(payload))
    return cases


def validate_cases(cases: list[EvalCase], repo_root: Path = REPO_ROOT) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            errors.append(f"duplicate case id: {case.id}")
        seen.add(case.id)
        if case.runner not in HARNESSES:
            errors.append(f"{case.id}: unknown runner {case.runner!r}")
        if case.grader not in GRADERS:
            errors.append(f"{case.id}: unknown grader {case.grader!r}")
        if case.live and case.runner not in LIVE_RUNNERS:
            errors.append(f"{case.id}: unsupported live runner {case.runner!r}")
        if not case.live and case.runner in LIVE_RUNNERS:
            errors.append(f"{case.id}: live runner requires live=true")
        if case.runner == "product_session":
            if not case.expect.get("rubric") or not case.input.get("turns"):
                errors.append(f"{case.id}: product session needs turns and a rubric")
            for check in case.expect.get("checks", []):
                if check.get("type") not in CHECK_TYPES or not check.get("name"):
                    errors.append(f"{case.id}: invalid check {check!r}")
        for related in case.related_paths:
            if not (repo_root / related).exists():
                errors.append(f"{case.id}: related path does not exist: {related}")
    return errors


def dataset_hash(cases: list[EvalCase]) -> str:
    payload = [case.model_dump(mode="json", exclude={"source_file"}) for case in cases]
    return _hash_json(payload)


def _hash_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _git_bytes(*args: str) -> bytes:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=False,
        )
        return result.stdout
    except (OSError, subprocess.CalledProcessError):
        return b""


def _git_value(*args: str) -> str:
    value = _git_bytes(*args)
    return value.decode(errors="replace").strip() if value else "unknown"


def _dirty_state_hash() -> str:
    """Hash changes to what runs under evaluation; Workbench UI code is not exercised."""
    digest = hashlib.sha256()
    digest.update(_git_bytes("diff", "--binary", "HEAD", "--", *_EVALUATED_PATHS))
    untracked = _git_bytes(
        "ls-files",
        "--others",
        "--exclude-standard",
        "--",
        *_EVALUATED_PATHS,
    ).decode(errors="replace")
    for relative in sorted(line for line in untracked.splitlines() if line):
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        digest.update(relative.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _manifest(run_id: str, cases: list[EvalCase], options: RunOptions) -> RunManifest:
    prompt = build_system_prompt(
        mode=AppMode.AGENT,
        workspace=REPO_ROOT,
        project_context_enabled=False,
    )
    tools = build_default_registry(Config(), mode="agent").to_api_tools()
    versions: dict[str, str] = {}
    for package in ("pydantic", "PyYAML"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            continue
    return RunManifest(
        run_id=run_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        git_commit=_git_value("rev-parse", "HEAD"),
        dirty_diff_hash=_dirty_state_hash(),
        dataset_hash=dataset_hash(cases),
        prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(),
        tool_catalog_hash=_hash_json(tools),
        python_version=platform.python_version(),
        package_versions=versions,
        mode="live" if options.mode == "live" else "offline",
        provider=options.provider,
        model=options.model,
        trials=options.trials,
        case_ids=[case.id for case in cases],
        grader_hash=_hash_json(
            {
                str(p.relative_to(REPO_ROOT)): p.read_text()
                for p in [
                    *sorted((REPO_ROOT / "evals" / "graders").glob("*.py")),
                    REPO_ROOT / "evals" / "judge.py",
                    REPO_ROOT / "evals" / "rubric.py",
                ]
            }
        ),
        settings={
            "label": options.label,
            "prompt_suffix": options.prompt_suffix,
            "max_live_requests": options.max_live_requests,
            "max_output_tokens": options.max_output_tokens,
            "max_cost_usd": options.max_cost_usd,
            "timeout_seconds": options.timeout_seconds,
            "judge_provider": options.judge_provider or options.provider,
            "judge_model": options.judge_model or options.model,
            "retry_policy": "metered-attempts-v1",
            "expected_trials": sum(options.trials if c.live else 1 for c in cases),
        },
    )


async def run_evaluations(
    options: RunOptions,
    *,
    cases: list[EvalCase] | None = None,
) -> tuple[Path, RunSummary]:
    if options.mode not in {"offline", "live"}:
        raise ValueError(f"unsupported eval mode: {options.mode!r}")
    if options.trials < 1:
        raise ValueError("trials must be positive")
    if options.max_cases is not None and options.max_cases < 1:
        raise ValueError("max_cases must be positive")
    if options.max_live_requests < 0:
        raise ValueError("max_live_requests cannot be negative")
    if options.max_output_tokens < 1 or options.timeout_seconds <= 0:
        raise ValueError("output-token and timeout budgets must be positive")
    if options.max_cost_usd is not None and options.max_cost_usd <= 0:
        raise ValueError("max_cost_usd must be positive")
    if options.concurrency < 1:
        raise ValueError("concurrency must be positive")
    selected = list(cases if cases is not None else load_cases())
    errors = validate_cases(selected)
    if errors:
        raise ValueError("invalid eval cases:\n" + "\n".join(f"- {error}" for error in errors))
    if options.suites:
        selected = [case for case in selected if case.suite in options.suites]
    if options.case_ids:
        unknown = set(options.case_ids) - {c.id for c in selected}
        if unknown:
            raise ValueError(f"unknown selected cases: {sorted(unknown)}")
        selected = [case for case in selected if case.id in options.case_ids]
    if options.mode == "offline":
        selected = [case for case in selected if not case.live]
    if options.max_cases is not None:
        selected = selected[: options.max_cases]
    if not selected:
        requested = ", ".join(options.suites) if options.suites else options.mode
        raise ValueError(f"no eval cases selected for {requested}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    commit = _git_value("rev-parse", "--short", "HEAD") or "unknown"
    run_id = f"{stamp}-{commit}"
    output = options.output_dir or DEFAULT_ARTIFACTS_ROOT / run_id
    output.mkdir(parents=True, exist_ok=False)
    manifest = _manifest(run_id, selected, options)
    write_json(output / "manifest.json", manifest.model_dump(mode="json"))

    context = HarnessContext(
        workspace=str(REPO_ROOT),
        provider=options.provider,
        model=options.model,
        max_output_tokens=options.max_output_tokens,
        remaining_live_requests=options.max_live_requests,
        max_cost_usd=options.max_cost_usd,
        prompt_suffix=options.prompt_suffix,
        judge_provider=options.judge_provider,
        judge_model=options.judge_model,
        max_input_tokens=options.max_input_tokens,
        turn_timeout_seconds=options.timeout_seconds,
        artifacts_dir=output,
    )
    results: list[TrialResult] = []
    stop_reason: str | None = None
    slots = asyncio.Semaphore(options.concurrency)

    def trial_result(case: EvalCase, trial: int, **fields: Any) -> TrialResult:
        return TrialResult(
            case_id=case.id,
            suite=case.suite,
            risk=case.risk,
            source_file=case.source_file,
            tags=case.tags,
            related_paths=case.related_paths,
            trial=trial,
            **fields,
        )

    def finish(result: TrialResult) -> None:
        results.append(result)
        append_result(output / "cases.jsonl", result)
        if result.status in {"failed", "error"}:
            write_json(
                output / "failures" / f"{result.case_id}-trial-{result.trial}.json",
                result.model_dump(mode="json"),
            )

    async def run_trial(case: EvalCase, trial: int) -> None:
        nonlocal stop_reason
        started = time.monotonic()
        try:
            async with slots:
                if stop_reason or (case.live and context.remaining_live_requests <= 0):
                    reason = stop_reason or "live request budget exhausted"
                    finish(trial_result(case, trial, status="skipped", duration_ms=0, error=reason))
                    return
                if (
                    case.live
                    and options.max_cost_usd is not None
                    and context.cost_usd >= options.max_cost_usd
                ):
                    finish(
                        trial_result(
                            case,
                            trial,
                            status="skipped",
                            duration_ms=0,
                            error="known USD cost budget exhausted",
                        )
                    )
                    return
                started = time.monotonic()
                before = context.fork()
                trial_context = context.fork()
                try:
                    # A product session limits each turn itself and reports the
                    # timeout as evidence; this limit would discard what it did.
                    observation = await asyncio.wait_for(
                        run_harness(case, trial_context),
                        timeout=None if case.runner == "product_session"
                        else options.timeout_seconds,
                    )
                    verdict = grade(case, observation)
                    status: Literal["passed", "failed"] = "passed" if verdict.passed else "failed"
                    result = trial_result(
                        case,
                        trial,
                        status=status,
                        duration_ms=int((time.monotonic() - started) * 1000),
                        grade=verdict,
                        observation=observation,
                    )
                except BudgetExceeded as exc:
                    result = trial_result(
                        case,
                        trial,
                        status="skipped",
                        duration_ms=int((time.monotonic() - started) * 1000),
                        error=str(exc),
                    )
                except EnvironmentInvalid as exc:
                    stop_reason = f"环境无效，已停止运行：{exc}"
                    result = trial_result(
                        case,
                        trial,
                        status="skipped",
                        duration_ms=int((time.monotonic() - started) * 1000),
                        error=stop_reason,
                    )
                except Exception as exc:  # noqa: BLE001 - one case must not abort the run
                    result = trial_result(
                        case,
                        trial,
                        status="error",
                        duration_ms=int((time.monotonic() - started) * 1000),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                context.absorb(trial_context, before)
                if case.live:
                    if result.observation is None:
                        result.observation = EvalObservation()
                    requests = trial_context.requests - before.requests
                    priced = trial_context.priced_requests - before.priced_requests
                    result.observation.usage = {
                        key: value - before.usage.get(key, 0)
                        for key, value in trial_context.usage.items()
                    }
                    cost = trial_context.cost_usd - before.cost_usd
                    result.observation.usage.update(
                        {
                            "requests": requests,
                            "metered_requests": trial_context.metered_requests
                            - before.metered_requests,
                            "priced_requests": priced,
                            "known_cost_usd": cost,
                        }
                    )
                    if requests > 0 and priced == requests:
                        result.observation.usage["cost_usd"] = cost
                    write_json(
                        output / "traces" / f"{case.id}-trial-{trial}.json", trial_context.trace
                    )
                    result.observation.data["trace_file"] = f"traces/{case.id}-trial-{trial}.json"
                finish(result)
        except asyncio.CancelledError:
            stop_reason = "用户已停止运行"
            finish(
                trial_result(
                    case,
                    trial,
                    status="skipped",
                    duration_ms=int((time.monotonic() - started) * 1000),
                    error="用户停止：当前试验已中断，不能作为成功结果",
                )
            )

    planned = [
        (case, trial)
        for case in selected
        for trial in range(1, (options.trials if case.live else 1) + 1)
    ]
    try:
        # Exclusive cases hold one desktop, so nothing may run beside them.
        await asyncio.gather(
            *(run_trial(c, t) for c, t in planned if not c.input.get("exclusive"))
        )
        for case, trial in planned:
            if case.input.get("exclusive"):
                await run_trial(case, trial)
    except asyncio.CancelledError:
        # gather drops tasks it cancelled before their first step: account for them.
        recorded = {(result.case_id, result.trial) for result in results}
        for case, trial in planned:
            if (case.id, trial) not in recorded:
                finish(
                    trial_result(
                        case, trial, status="skipped", duration_ms=0, error="用户已停止运行"
                    )
                )
    finally:
        await asyncio.shield(context.close())
        end_hash = _dirty_state_hash()
        manifest.settings["source_changed_during_run"] = end_hash != manifest.dirty_diff_hash
        manifest.settings["end_dirty_diff_hash"] = end_hash
        write_json(output / "manifest.json", manifest.model_dump(mode="json"))
        summary = summarize(run_id, results)
        write_json(output / "summary.json", summary.model_dump(mode="json"))
    return output, summary
