"""Sequential, resumable Harbor campaign. Every attempt has its own directory."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import random
import shutil
import signal
import subprocess
import time
from pathlib import Path

STOP_STATES = {"quota", "authentication", "persistent_api_error"}


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def summarize(rows, total):
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
        "official_reference_percent": 88.2,
        "gap_to_official_percentage_points": 100 * passed / total - 88.2 if complete else None,
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


def main(directory, limit=None):
    root = Path(__file__).resolve().parents[2]
    out = Path(directory).resolve()
    out.mkdir(parents=True, exist_ok=True)
    lock = (out / "campaign.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    dataset = out / "datasets/terminal-bench-2.1"
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        actual = hashlib.sha256((out / "source.tar.gz").read_bytes()).hexdigest()
        if actual != manifest["source_sha256"]:
            raise RuntimeError("Frozen source changed; use a new campaign directory")
    else:
        names = sorted(p.parent.name for p in (dataset / "tasks").glob("*/task.toml"))
        random.Random(20261019).shuffle(names)
        if limit:
            names = names[:limit]
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
            "model": "endpoint/glm-5-3",
            "upstream_identity_verified": False,
            "harbor_version": "0.24.0",
            "bootstrap_sha256": {
                path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in out.glob("uv-*.tar.gz")
            },
            "temperature": 1.0,
            "top_p": 1.0,
            "max_output_tokens": 65536,
            "reasoning_effort": (
                "provider default; official GLM-5.3 defaults to max, gateway unverified"
            ),
            "trials_per_task": 1,
            "concurrency": 1,
            "task_timeout_seconds": 21600,
            "idle_timeout_seconds": 900,
            "request_limit_per_task": 600,
            "scope": (
                "production Engine.create + Engine.run, single-agent file/shell tools; "
                "no UI, MCP, subagents, personal plugins"
            ),
            "official_reference": {
                "score_percent": 88.2,
                "scaffold": "Claude Code 2.1.207",
                "source": "https://huggingface.co/zai-org/GLM-5.3/blob/main/README.md",
            },
            "host": "Apple silicon, Docker/OrbStack; linux/amd64 emulation where required",
        }
        write_json(manifest_path, manifest)
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
            **summarize(rows, len(manifest["tasks"])),
        }
        write_json(out / "progress.json", progress)
        if shutil.disk_usage(out).free < 10 * 1024**3:
            progress.update(state="blocked", reason="Less than 10 GiB free disk space")
            write_json(out / "progress.json", progress)
            return
        print(f"Starting {index + 1}/{len(manifest['tasks'])}: {name}", flush=True)
        with (out / "configs" / (jobname + ".console.log")).open("w") as log:
            env = dict(
                os.environ,
                DOCKER_DEFAULT_PLATFORM="linux/amd64",
                PYTHONUNBUFFERED="1",
                PYTHONPATH=str(root),
            )
            process = subprocess.Popen(
                [str(out / "venv/bin/harbor"), "run", "--config", str(config)],
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
                env=env,
                start_new_session=True,
            )
            deadline = time.monotonic() + 25200  # setup + six-hour agent + verification
            while process.poll() is None:
                progress.update(updated_at=time.time(), child_pid=process.pid)
                write_json(out / "progress.json", progress)
                if time.monotonic() >= deadline:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                    break
                time.sleep(15)
        row = collect(out / "jobs" / jobname, name, process.returncode)
        with ledger.open("a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        failures = (
            failures + 1
            if row["runtime_state"] in {"infrastructure_error", "runtime_error", "idle_timeout"}
            else 0
        )
        progress.update(summarize(rows, len(manifest["tasks"])), updated_at=time.time())
        write_json(out / "summary.json", summarize(rows, len(manifest["tasks"])))
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
            **summarize(rows, len(manifest["tasks"])),
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    main(args.directory, args.limit)
