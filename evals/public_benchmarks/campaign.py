"""Sequential, resumable Harbor campaign. Every attempt has its own directory."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import random
import shutil
import signal
import subprocess
import time
from pathlib import Path

STOP_STATES = {"quota", "authentication", "persistent_api_error"}
# Consecutive outcomes that point at the environment rather than the model.
FAILURE_STATES = {"infrastructure_error", "runtime_error", "idle_timeout"}
HARBOR_VERSION = "0.24.0"
MANIFEST_ENV = "PUBLIC_BENCHMARK_MANIFEST"
# The first campaign's manifest predates these fields; resuming it keeps its values.
LEGACY = {
    "model": "endpoint/glm-5-3",
    "official_reference": {
        "score_percent": 88.2,
        "scaffold": "Claude Code 2.1.207",
        "source": "https://huggingface.co/zai-org/GLM-5.3/blob/main/README.md",
    },
}


def campaign_settings(manifest):
    """Every tunable campaign value, read from the manifest with recorded defaults."""
    provider, _, model = manifest.get("model", LEGACY["model"]).partition("/")
    reference = manifest.get("official_reference", LEGACY["official_reference"]) or {}
    parallel = manifest.get("parallel") or {}
    return {
        "provider": provider,
        "model": model,
        "reference_percent": reference.get("score_percent"),
        "reference_scaffold": reference.get("scaffold", ""),
        "reference_source": reference.get("source", ""),
        "gateway": manifest.get("gateway", "当前配置的模型网关"),
        "temperature": manifest.get("temperature", 1.0),
        "top_p": manifest.get("top_p", 1.0),
        "max_output_tokens": manifest.get("max_output_tokens", 65536),
        "request_limit": manifest.get("request_limit_per_task", 600),
        "idle_timeout": manifest.get("idle_timeout_seconds", 900),
        "task_timeout": manifest.get("task_timeout_seconds", 21600),
        # Setup + agent budget + verification.
        "supervisor_timeout": manifest.get("supervisor_timeout_seconds", 25200),
        "concurrency": parallel.get("concurrency", 2),
        "memory_budget_mb": parallel.get("memory_budget_mb", 8192),
        "docker_platform": manifest.get("docker_platform", "linux/amd64"),
    }


def add_campaign_arguments(parser):
    """Options that only apply when a new campaign directory gets its manifest."""
    group = parser.add_argument_group("new campaign")
    group.add_argument("--model", help="provider/model route, e.g. endpoint/glm-5-3")
    group.add_argument("--limit", type=int, help="run only the first N shuffled tasks")
    group.add_argument("--seed", type=int, default=20261019)
    group.add_argument("--reference-percent", type=float)
    group.add_argument("--reference-scaffold", default="")
    group.add_argument("--reference-source", default="")
    group.add_argument("--gateway", default="当前配置的模型网关")
    group.add_argument("--temperature", type=float, default=1.0)
    group.add_argument("--top-p", type=float, default=1.0)
    group.add_argument("--max-output-tokens", type=int, default=65536)
    group.add_argument("--request-limit", type=int, default=600)
    group.add_argument("--idle-timeout", type=int, default=900)
    group.add_argument("--task-timeout", type=int, default=21600)
    group.add_argument("--supervisor-timeout", type=int, default=25200)
    group.add_argument("--concurrency", type=int, default=2)
    group.add_argument("--memory-budget-mb", type=int, default=8192)
    group.add_argument("--docker-platform", default="linux/amd64",
                       help="empty to use the host platform")


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def load_manifest(out, root, options=None):
    """The frozen manifest, created from ``options`` the first time."""
    dataset = out / "datasets/terminal-bench-2.1"
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        actual = hashlib.sha256((out / "source.tar.gz").read_bytes()).hexdigest()
        if actual != manifest["source_sha256"]:
            raise RuntimeError("Frozen source changed; use a new campaign directory")
        return manifest
    if options is None or not options.model or "/" not in options.model:
        raise SystemExit("A new campaign needs --model provider/model")
    names = sorted(p.parent.name for p in (dataset / "tasks").glob("*/task.toml"))
    random.Random(options.seed).shuffle(names)
    if options.limit:
        names = names[: options.limit]
    reference = None
    if options.reference_percent is not None:
        reference = {
            "score_percent": options.reference_percent,
            "scaffold": options.reference_scaffold,
            "source": options.reference_source,
        }
    manifest = {
        "created_at": time.time(),
        "dataset": "Terminal-Bench 2.1",
        "tasks": names,
        "dataset_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=dataset, text=True
        ).strip(),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "source_sha256": hashlib.sha256((out / "source.tar.gz").read_bytes()).hexdigest(),
        "model": options.model,
        "gateway": options.gateway,
        "upstream_identity_verified": False,
        "harbor_version": HARBOR_VERSION,
        "bootstrap_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in out.glob("uv-*.tar.gz")
        },
        "temperature": options.temperature,
        "top_p": options.top_p,
        "max_output_tokens": options.max_output_tokens,
        "reasoning_effort": "provider default (unverified for this gateway)",
        "trials_per_task": 1,
        "task_timeout_seconds": options.task_timeout,
        "idle_timeout_seconds": options.idle_timeout,
        "supervisor_timeout_seconds": options.supervisor_timeout,
        "request_limit_per_task": options.request_limit,
        "parallel": {
            "concurrency": options.concurrency,
            "memory_budget_mb": options.memory_budget_mb,
        },
        "docker_platform": options.docker_platform,
        "scope": (
            "production Engine.create + Engine.run, single-agent file/shell tools; "
            "no UI, MCP, subagents, personal plugins"
        ),
        "official_reference": reference,
        "host": f"{platform.system()} {platform.machine()}",
    }
    write_json(manifest_path, manifest)
    return manifest


def trial_env(out, settings):
    env = dict(
        os.environ,
        PYTHONUNBUFFERED="1",
        PYTHONPATH=str(Path(__file__).resolve().parents[2]),
        # The adapter exports this campaign's model and budgets, not built-in ones.
        **{MANIFEST_ENV: str(out / "manifest.json")},
    )
    if settings["docker_platform"]:
        env["DOCKER_DEFAULT_PLATFORM"] = settings["docker_platform"]
    return env


def summarize(rows, total, reference=None):
    graded = [r for r in rows if r.get("reward") is not None]
    passed = sum(r["reward"] == 1 for r in graded)
    complete = len(rows) == total and len(graded) == total
    return {
        "planned": total,
        "attempted": len(rows),
        "graded": len(graded),
        "passed": passed,
        "graded_pass_rate_percent": 100 * passed / len(graded) if graded else None,
        "coverage_percent": 100 * len(graded) / total,
        "full_suite_pass_rate_percent": 100 * passed / total if complete else None,
        "official_reference_percent": reference,
        "gap_to_official_percentage_points": (
            100 * passed / total - reference if complete and reference is not None else None
        ),
        "comparison": (
            "directional only: gateway identity, scaffold, hardware and repetition count differ"
        ),
        "runtime_states": {
            state: sum(r.get("runtime_state") == state for r in rows)
            for state in sorted({r.get("runtime_state", "unknown") for r in rows})
        },
        "requests": sum(r.get("requests", 0) for r in rows),
        "cost_usd": None,
    }


def counts_as_failure(row):
    """An environment failure or a trial the supervisor had to stop."""
    return row["runtime_state"] in FAILURE_STATES or bool(row.get("supervisor_timeout_reason"))


def collect(job, task, returncode):
    results = list(job.glob("*/result.json"))
    result = json.loads(results[0].read_text()) if len(results) == 1 else {}
    statuses = list(job.glob("*/agent/status.json"))
    status = json.loads(statuses[0].read_text()) if len(statuses) == 1 else {}
    rewards = (result.get("verifier_result") or {}).get("rewards") or {}
    reward = rewards.get("reward")
    if reward is None and len(rewards) == 1:
        reward = next(iter(rewards.values()))
    return {
        "task": task,
        "job": str(job),
        "finished_at": time.time(),
        "returncode": returncode,
        "reward": reward,
        "runtime_state": status.get("state", "infrastructure_error"),
        "requests": status.get("requests", 0),
        "usage": status.get("usage"),
        "exception": result.get("exception_info"),
        "runtime_error": status.get("error"),
    }


def main(directory, options=None):
    root = Path(__file__).resolve().parents[2]
    out = Path(directory).resolve()
    out.mkdir(parents=True, exist_ok=True)
    lock = (out / "campaign.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    dataset = out / "datasets/terminal-bench-2.1"
    manifest = load_manifest(out, root, options)
    settings = campaign_settings(manifest)
    reference = settings["reference_percent"]
    ledger = out / "results.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    finished = {r["task"] for r in rows}
    base = json.loads((out / "pilot.json").read_text())
    base["jobs_dir"] = str(out / "jobs")
    failures = 0
    for index, name in enumerate(manifest["tasks"]):
        if name in finished:
            continue
        jobname = f"{index + 1:03d}-{name}-{int(time.time())}"
        base["job_name"] = jobname
        base["tasks"] = [{"path": str(dataset / "tasks" / name)}]
        config = out / "configs" / (jobname + ".json")
        config.parent.mkdir(exist_ok=True)
        write_json(config, base)
        progress = {
            "state": "running",
            "pid": os.getpid(),
            "current_task": name,
            "job_name": jobname,
            "started_at": time.time(),
            "updated_at": time.time(),
            **summarize(rows, len(manifest["tasks"]), reference),
        }
        write_json(out / "progress.json", progress)
        if shutil.disk_usage(out).free < 10 * 1024**3:
            progress.update(state="blocked", reason="Less than 10 GiB free disk space")
            write_json(out / "progress.json", progress)
            return
        print(f"Starting {index + 1}/{len(manifest['tasks'])}: {name}", flush=True)
        timed_out = False
        with (out / "configs" / (jobname + ".console.log")).open("w") as log:
            process = subprocess.Popen(
                [str(out / "venv/bin/harbor"), "run", "--config", str(config)],
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=trial_env(out, settings),
                start_new_session=True,
            )
            deadline = time.monotonic() + settings["supervisor_timeout"]
            while process.poll() is None:
                progress.update(updated_at=time.time(), child_pid=process.pid)
                write_json(out / "progress.json", progress)
                if time.monotonic() >= deadline:
                    timed_out = True
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    break
                time.sleep(15)
        row = collect(out / "jobs" / jobname, name, process.returncode)
        if timed_out:
            row["supervisor_timeout_reason"] = "supervisor_timeout"
        with ledger.open("a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        failures = failures + 1 if counts_as_failure(row) else 0
        progress.update(summarize(rows, len(manifest["tasks"]), reference), updated_at=time.time())
        write_json(out / "summary.json", summarize(rows, len(manifest["tasks"]), reference))
        from evals.public_benchmarks.analyze import analyze

        analyze(out)
        if row["runtime_state"] in STOP_STATES or failures >= 3:
            progress.update(state="blocked", reason=row["runtime_state"])
            write_json(out / "progress.json", progress)
            return
    write_json(
        out / "progress.json",
        {
            "state": "completed",
            "updated_at": time.time(),
            **summarize(rows, len(manifest["tasks"]), reference),
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    add_campaign_arguments(parser)
    args = parser.parse_args()
    main(args.directory, args)
