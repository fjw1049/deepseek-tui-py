"""Bounded, frozen-source A/A + A/B campaigns over the existing Eval Lab worker."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import signal
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.coverage import corpus_coverage
from evals.decision import DecisionPolicy, decide
from evals.experiments import load_run
from evals.report import summarize, write_json
from evals.runner import REPO_ROOT, RunOptions, dataset_hash, load_cases, validate_cases
from evals.schema import EvalCase, TrialResult
from evals.snapshots import freeze_source, tree_hash

ARMS = ("baseline", "repeat", "candidate")


class CampaignSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    hypothesis: str = Field(min_length=1)
    baseline_revision: str = "HEAD"
    candidate_revision: str = "working-tree"
    case_ids: list[str] = Field(min_length=1, max_length=200)
    mode: Literal["offline", "live"] = "offline"
    provider: str | None = None
    model: str | None = None
    judge_provider: str | None = None
    judge_model: str | None = None
    repetitions: int = Field(default=3, ge=1, le=20)
    max_live_requests: int = Field(default=20, ge=1)
    max_product_requests: int = Field(default=20, ge=1)
    max_output_tokens: int = Field(default=2048, ge=1)
    max_input_tokens: int | None = Field(default=None, gt=0)
    timeout_seconds: float = Field(default=120, gt=0)
    worker_timeout_seconds: float = Field(default=600, gt=0)
    campaign_timeout_seconds: float = Field(default=3600, gt=0)
    seed: int = 20261112
    policy: DecisionPolicy = Field(default_factory=DecisionPolicy)

    @model_validator(mode="after")
    def check_selection(self) -> CampaignSpec:
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("duplicate case IDs")
        if self.mode == "live" and (not self.provider or not self.model):
            raise ValueError("live campaigns need an explicit provider and model")
        return self


def schedule(spec: CampaignSpec) -> list[dict[str, Any]]:
    rng = random.Random(spec.seed)
    plan: list[dict[str, Any]] = []
    for trial in range(1, spec.repetitions + 1):
        cases = list(spec.case_ids)
        rng.shuffle(cases)
        for case_id in cases:
            arms = list(ARMS)
            rng.shuffle(arms)
            plan.extend({"arm": arm, "case_id": case_id, "trial": trial} for arm in arms)
    return plan


def selected_cases(spec: CampaignSpec) -> list[EvalCase]:
    corpus = load_cases()
    errors = validate_cases(corpus)
    if errors:
        raise ValueError("invalid corpus: " + "; ".join(errors))
    cases = [c for c in corpus if c.id in spec.case_ids]
    if len(cases) != len(spec.case_ids) or any(c.live != (spec.mode == "live") for c in cases):
        raise ValueError("select existing cases of one mode; offline and live must run separately")
    return cases


def configuration_hash() -> str:
    """Detect local routing/config changes without copying or publishing secrets."""
    from deepseek_tui.config.paths import user_config_path, user_deepseek_dir

    digest = hashlib.sha256()
    paths = [user_config_path(), *(user_deepseek_dir() / name
                                   for name in ("settings.json", "network.json"))]
    for path in paths:
        digest.update(str(path).encode() + b"\0")
        digest.update(path.read_bytes() if path.is_file() else b"missing")
    values = {k: v for k, v in os.environ.items() if k.startswith(("DEEPSEEK_", "EVAL_"))}
    digest.update(json.dumps(values, sort_keys=True).encode())
    return digest.hexdigest()


async def execute_worker(source: Path, request: Path, timeout: float) -> None:
    with request.with_suffix(".log").open("wb") as log:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "evals.worker", str(request), cwd=source,
            env={**os.environ, "PYTHONPATH": str(source / "src") + os.pathsep + str(source),
                 "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=log, stderr=log, start_new_session=True,
        )
        try:
            code = await asyncio.wait_for(process.wait(), timeout)
            if code:
                raise RuntimeError(f"worker exited {code}; see {request.with_suffix('.log')}")
        finally:
            # The product server is a grandchild. Stop the whole isolated group even
            # when the worker crashes, rather than leaving it writing in the background.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            if process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), 8)
                except TimeoutError:
                    pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()


def _collect(
    output: Path, arm: str, completed: list[dict[str, Any]], cases: list[EvalCase],
    spec: CampaignSpec,
) -> dict[str, Any]:
    batches = [entry for entry in completed if entry["arm"] == arm]
    if not batches:
        raise ValueError(f"missing campaign arm: {arm}")
    rows = []
    first = load_run(output / batches[0]["run"])
    for entry in batches:
        run = load_run(output / entry["run"])
        for row in run["cases"]:
            row = {**row, "trial": entry["trial"], "artifact_run": entry["run"]}
            rows.append(row)
    manifest = {**first["manifest"], "run_id": arm, "dataset_hash": dataset_hash(cases),
                "trials": spec.repetitions, "case_ids": spec.case_ids}
    manifest["settings"] = {**manifest["settings"],
                            "expected_trials": len(cases) * spec.repetitions,
                            "case_trials": {c.id: spec.repetitions for c in cases}}
    complete = len(batches) == len(cases) * spec.repetitions
    return {"manifest": manifest, "cases": rows,
            "status": "completed" if complete else "interrupted", "metrics": {}}


def _write_report(output: Path, result: dict[str, Any]) -> None:
    write_json(output / "decision.json", result)
    lines = [f"# {result['label']}", "", *[f"- {r}" for r in result["reasons"]]]
    if result.get("coverage"):
        coverage = result["coverage"]
        lines += ["", f"任务 {coverage['end_to_end_tasks']}；"
                  f"声明来源 {coverage['declared_sources']}；"
                  f"封存来源 {coverage['holdout_sources']}；"
                  f"缺少来源/类别的任务 {len(coverage['missing_metadata'])}。", coverage["note"]]
    if result.get("families"):
        lines += ["", "| 任务类别 | 独立来源 | 候选减基线 |", "|---|---:|---:|"]
        lines += [f"| {k} | {v['groups']} | {v['delta']:+.3f} |"
                  for k, v in result["families"].items()]
    comparison = result.get("comparison", {})
    if result.get("resources"):
        lines += ["", "## 代价与覆盖", "",
                  "含失败尝试。完整试验耗时包含启动和评审，不等于用户等待时间；未知费用不填零。",
                  "未配置代价上限时仅展示，不作为候选门槛。", "",
                  "| 指标 | 基线 | 候选 |", "|---|---:|---:|"]
        for key, label in (("mean_trial_duration_ms", "平均完整试验耗时 ms"),
                           ("cost_coverage", "完整计费覆盖率"),
                           ("known_cost_usd", "已知费用 USD"),
                           ("cost_per_success_usd", "每个完成任务成本 USD")):
            values = [result["resources"][arm][key] for arm in ("baseline", "candidate")]
            lines.append(f"| {label} | " + " | ".join(
                "未知/不适用" if v is None else f"{v:.4f}" for v in values) + " |")
    if result.get("efficiency"):
        efficiency = result["efficiency"]
        lines += ["", f"效率目标：{efficiency['metric']}；按来源等权的完成任务代价降幅 "
                  f"{efficiency['delta']}；探索性区间 {efficiency['interval']}。"]
    lines += ["", "## 逐题变化", "", "| 场景 | 基线 | 候选 |", "|---|---:|---:|"]
    for row in comparison.get("rows", []):
        lines.append(f"| {row['case_id']} | {row['a']} | {row['b']} |")
    lines += ["", result.get("note", ""), "",
              "原始证据与运行顺序见 campaign.json；每项 run 指向 runs/ 下的独立留档。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


async def run_campaign(spec: CampaignSpec, output: Path, root: Path = REPO_ROOT) -> dict[str, Any]:
    if any(k.startswith("EVAL_COMPRESSION_") for k in os.environ):
        raise ValueError("remove external compression overrides; compare frozen product sources")
    cases = selected_cases(spec)
    output = await asyncio.to_thread(output.resolve)
    output.mkdir(parents=True, exist_ok=False)
    state: dict[str, Any] = {"spec": spec.model_dump(), "status": "preparing",
                             "schedule": schedule(spec), "completed": [], "snapshots": {},
                             "coverage": corpus_coverage(cases)}
    write_json(output / "campaign.json", state)
    result: dict[str, Any] = {"decision": "insufficient_evidence", "label": "证据不足",
                              "reasons": [], "policy": spec.policy.model_dump()}
    try:
        if spec.mode == "live":
            from deepseek_tui.config.loader import ConfigLoader

            config = ConfigLoader().load(provider=spec.provider, model=spec.model,
                                         workspace=root, no_project_config=True)
            host = urlsplit(config.effective_provider_config().base_url or "").hostname
            if not host:
                raise ValueError(f"no endpoint configured for provider {spec.provider!r}")
            state["target"] = {"provider": spec.provider, "model": spec.model, "host": host}
        for arm, revision in (("baseline", spec.baseline_revision),
                              ("candidate", spec.candidate_revision)):
            state["snapshots"][arm] = freeze_source(root, revision, output / "sources" / arm)
        a, b = (state["snapshots"][arm] for arm in ("baseline", "candidate"))
        if a["evaluator_hash"] != b["evaluator_hash"]:
            raise ValueError("evaluator changed while freezing the two arms")
        if a["dependencies_hash"] != b["dependencies_hash"]:
            raise ValueError("dependency changes need separately provisioned environments")
        state["configuration_hash"] = configuration_hash()
        state["status"] = "running"
        write_json(output / "campaign.json", state)
        deadline = time.monotonic() + spec.campaign_timeout_seconds
        for number, entry in enumerate(state["schedule"], 1):
            if (output / "STOP").exists():
                raise InterruptedError("STOP requested; no further trial scheduled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("campaign time budget exhausted")
            if configuration_hash() != state["configuration_hash"]:
                raise ValueError("model routing or local configuration changed during campaign")
            source_arm = "candidate" if entry["arm"] == "candidate" else "baseline"
            source = output / "sources" / source_arm
            if tree_hash(source) != state["snapshots"][source_arm]["source_hash"]:
                raise ValueError("frozen source was modified")
            name = f"{number:04d}-{entry['arm']}"
            run_dir = output / "runs" / name
            options = RunOptions(
                mode=spec.mode, case_ids=(entry["case_id"],), output_dir=run_dir,
                provider=spec.provider, model=spec.model,
                judge_provider=spec.judge_provider, judge_model=spec.judge_model,
                max_live_requests=spec.max_live_requests, max_output_tokens=spec.max_output_tokens,
                max_product_requests=spec.max_product_requests,
                max_input_tokens=spec.max_input_tokens, timeout_seconds=spec.timeout_seconds,
            )
            request = output / "requests" / f"{name}.json"
            write_json(request, {**asdict(options), "output_dir": str(run_dir)})
            print(f"[{number}/{len(state['schedule'])}] {entry['arm']} "
                  f"{entry['case_id']} trial={entry['trial']}", flush=True)
            await execute_worker(source, request, min(remaining, spec.worker_timeout_seconds))
            run = load_run(run_dir)
            if (run["manifest"].get("case_ids") != [entry["case_id"]]
                    or [(r["case_id"], r["trial"]) for r in run["cases"]]
                    != [(entry["case_id"], 1)]):
                raise ValueError("worker results do not match the scheduled trial")
            if run["manifest"].get("settings", {}).get("source_changed_during_run"):
                raise ValueError("runner observed a source change during a trial")
            if tree_hash(source) != state["snapshots"][source_arm]["source_hash"]:
                raise ValueError("frozen source changed during a trial")
            state["completed"].append({**entry, "run": run_dir.relative_to(output).as_posix()})
            write_json(output / "campaign.json", state)
            if run["status"] != "completed" or any(r["status"] in {"skipped", "error"}
                                                    for r in run["cases"]):
                raise RuntimeError("trial contains missing results, runner or grading errors")
        if configuration_hash() != state["configuration_hash"]:
            raise ValueError("configuration changed during the final trial")
        for arm, snapshot in state["snapshots"].items():
            if tree_hash(output / "sources" / arm) != snapshot["source_hash"]:
                raise ValueError("frozen source changed before final comparison")
        runs = {arm: _collect(output, arm, state["completed"], cases, spec) for arm in ARMS}
        for arm, aggregate in runs.items():
            assert aggregate is not None
            directory = output / arm
            write_json(directory / "manifest.json", aggregate["manifest"])
            (directory / "cases.jsonl").write_text("".join(
                json.dumps(row, ensure_ascii=False) + "\n" for row in aggregate["cases"]
            ))
            records = [TrialResult.model_validate({k: v for k, v in row.items()
                                                  if k != "artifact_run"})
                       for row in aggregate["cases"]]
            summary = summarize(arm, records)
            write_json(directory / "summary.json", summary.model_dump())
            aggregate["metrics"] = summary.metrics
        result = decide(runs["baseline"], runs["candidate"], spec.policy, runs["repeat"])
        state["status"] = "completed"
    except (Exception, asyncio.CancelledError) as exc:
        state["status"] = "interrupted" if isinstance(
            exc, (InterruptedError, asyncio.CancelledError)
        ) else "error"
        result["reasons"] = [f"{type(exc).__name__}: {exc}"]
    finally:
        result["coverage"] = state["coverage"]
        write_json(output / "campaign.json", state)
        _write_report(output, result)
    return result
