"""Bounded parallel supervisor; can adopt a live trial without restarting its agent."""

import argparse
import fcntl
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

import tomllib

from evals.public_benchmarks.analyze import analyze
from evals.public_benchmarks.campaign import (
    STOP_STATES,
    add_campaign_arguments,
    campaign_settings,
    collect,
    counts_as_failure,
    load_manifest,
    summarize,
    trial_env,
    write_json,
)

FAST_DEFAULTS = {"setup_seconds": 300, "idle_seconds": 300, "total_seconds": 1800}
STOP_GRACE_SECONDS = 30


def pending_tasks(names, rows, active):
    claimed = {row["task"] for row in rows} | {row["task"] for row in active}
    return [name for name in names if name not in claimed]


def fits(active, memory_mb, concurrency=2, budget_mb=8192):
    return (
        len(active) < concurrency
        and sum(item["memory_mb"] for item in active) + memory_mb <= budget_mb
    )


def load_fast_policy(out):
    """Budgets for attempts started after ``fast-policy.json`` appeared, or None."""
    path = out / "fast-policy.json"
    if not path.exists():
        return None
    try:
        policy = json.loads(path.read_text() or "{}")
    except json.JSONDecodeError:
        policy = {}
    return {
        **FAST_DEFAULTS,
        **{key: policy[key] for key in FAST_DEFAULTS if key in policy},
        # Attempts already running keep the budget they were started under.
        "created_at": policy.get("created_at", path.stat().st_mtime),
    }


def fast_timeout(item, status, now, policy=None):
    policy = policy or {**FAST_DEFAULTS, "created_at": 0}
    if item["started_at"] < policy["created_at"]:
        return None
    elapsed = now - item["started_at"]
    if elapsed >= policy["total_seconds"]:
        return "fast_total_timeout"
    if status is None and elapsed >= policy["setup_seconds"]:
        return "fast_setup_timeout"
    if (
        status
        and status.get("state") == "running"
        and status.get("idle_seconds", 0) >= policy["idle_seconds"]
    ):
        return "fast_idle_timeout"
    return None


def signal_trial(pid, sig):
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


def finished(item, jobs):
    if item.get("process") is not None:
        return item["process"].poll() is not None
    result = jobs / item["job_name"] / "result.json"
    if result.exists() and json.loads(result.read_text()).get("finished_at"):
        return True
    status = subprocess.run(
        ["ps", "-p", str(item["child_pid"]), "-o", "stat="],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return status.returncode != 0 or status.stdout.strip().startswith("Z")


def main(directory, handoff=None, options=None):
    out = Path(directory).resolve()
    out.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    with (out / "campaign.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        load_manifest(out, root, options)
        run(out, root, json.loads(Path(handoff).read_text()) if handoff else None)


def run(out, root, handoff=None):
    manifest = load_manifest(out, root)
    settings = campaign_settings(manifest)
    reference = settings["reference_percent"]
    concurrency, budget = settings["concurrency"], settings["memory_budget_mb"]
    ledger = out / "results.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    base = json.loads((out / "pilot.json").read_text())
    base["jobs_dir"] = str(out / "jobs")
    tasks = out / "datasets/terminal-bench-2.1/tasks"
    memory = {
        name: tomllib.loads((tasks / name / "task.toml").read_text())["environment"]["memory_mb"]
        for name in manifest["tasks"]
    }
    active = []
    prior = (handoff or {}).get("progress") or {}
    if prior.get("current_task") and prior["current_task"] not in {row["task"] for row in rows}:
        active.append(
            {
                "task": prior["current_task"],
                "job_name": prior["job_name"],
                "child_pid": prior["child_pid"],
                "started_at": prior["started_at"],
                "memory_mb": memory[prior["current_task"]],
            }
        )
    reason = None
    failures = 0
    while True:
        policy = load_fast_policy(out)
        if (out / "STOP").exists():
            reason = reason or "stop_requested"
        for item in list(active):
            job = out / "jobs" / item["job_name"]
            states = list(job.glob("*/agent/status.json"))
            status = None
            if states:
                status = json.loads(states[0].read_text())
                state = status["state"]
                if state in STOP_STATES:
                    reason = state
            if finished(item, out / "jobs"):
                process = item.get("process")
                row = collect(job, item["task"], process.returncode if process else None)
                if row["runtime_state"] == "running":
                    row["runtime_state"] = "interrupted"
                if item.get("timeout_reason"):
                    row["supervisor_timeout_reason"] = item["timeout_reason"]
                with ledger.open("a") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                rows.append(row)
                active.remove(item)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                failures = failures + 1 if counts_as_failure(row) else 0
                if row["runtime_state"] in STOP_STATES:
                    reason = row["runtime_state"]
                elif failures >= 3:
                    reason = "consecutive_failures"
                write_json(out / "summary.json", summarize(rows, len(manifest["tasks"]), reference))
                analyze(out)
                continue
            if not item.get("timeout_reason"):
                now = time.time()
                # Stop only this trial; scheduling continues like the sequential runner.
                # Trials older than the fast policy keep the original deadline.
                item["timeout_reason"] = (
                    fast_timeout(item, status, now, policy) if policy is not None else None
                ) or (
                    "supervisor_timeout"
                    if now - item["started_at"] > settings["supervisor_timeout"]
                    else None
                )
            if reason or (out / "STOP").exists() or item.get("timeout_reason"):
                if (out / "STOP").exists():
                    reason = reason or "stop_requested"
                if not item.get("stopping_at"):
                    signal_trial(item["child_pid"], signal.SIGINT)
                    item["stopping_at"] = time.time()
                elif time.time() - item["stopping_at"] > STOP_GRACE_SECONDS:
                    signal_trial(item["child_pid"], signal.SIGKILL)
        pending = pending_tasks(manifest["tasks"], rows, active)
        if shutil.disk_usage(out).free < 10 * 1024**3:
            reason = reason or "disk_space_below_10GiB"
        while pending and not reason and fits(active, memory[pending[0]], concurrency, budget):
            name = pending.pop(0)
            index = manifest["tasks"].index(name) + 1
            jobname = f"{index:03d}-{name}-{time.time_ns()}"
            base["job_name"] = jobname
            base["tasks"] = [{"path": str(tasks / name)}]
            config = out / "configs" / (jobname + ".json")
            config.parent.mkdir(exist_ok=True)
            write_json(config, base)
            with config.with_suffix(".console.log").open("w") as log:
                process = subprocess.Popen(
                    [str(out / "venv/bin/harbor"), "run", "--config", str(config)],
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env=trial_env(out, settings),
                )
            active.append(
                {
                    "task": name,
                    "job_name": jobname,
                    "child_pid": process.pid,
                    "started_at": time.time(),
                    "memory_mb": memory[name],
                    "process": process,
                }
            )
            print(
                f"Started slot {len(active)}/{concurrency}: {name}, PID {process.pid}", flush=True
            )
        progress = {
            "state": "stopping"
            if reason and active
            else "blocked"
            if reason
            else "running"
            if active
            else "completed",
            "reason": reason,
            "pid": os.getpid(),
            "updated_at": time.time(),
            "concurrency": concurrency,
            "memory_budget_mb": budget,
            "active_tasks": [{k: v for k, v in item.items() if k != "process"} for item in active],
            **summarize(rows, len(manifest["tasks"]), reference),
        }
        write_json(out / "progress.json", progress)
        if not active:
            if pending and not reason:
                raise RuntimeError("Next task cannot fit the declared memory budget")
            break
        time.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("handoff", nargs="?", help="adopt the trial a sequential run left running")
    add_campaign_arguments(parser)
    args = parser.parse_args()
    main(args.directory, args.handoff, args)
