"""Two-slot supervisor; adopts the live trial without restarting its agent."""

import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import tomllib

from evals.public_benchmarks.analyze import analyze
from evals.public_benchmarks.campaign import STOP_STATES, collect, summarize, write_json


def pending_tasks(names, rows, active):
    claimed = {row["task"] for row in rows} | {row["task"] for row in active}
    return [name for name in names if name not in claimed]


def fits(active, memory_mb):
    return len(active) < 2 and sum(item["memory_mb"] for item in active) + memory_mb <= 8192


def fast_timeout(item, status, now):
    elapsed = now - item["started_at"]
    if elapsed >= 1800:
        return "fast_total_timeout"
    if status is None and elapsed >= 300:
        return "fast_setup_timeout"
    if status and status.get("state") == "running" and status.get("idle_seconds", 0) >= 300:
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


def main(directory, handoff):
    out = Path(directory).resolve()
    root = Path(__file__).resolve().parents[2]
    with (out / "campaign.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(out, root, json.loads(Path(handoff).read_text()))


def run(out, root, handoff):
    manifest = json.loads((out / "manifest.json").read_text())
    assert (
        hashlib.sha256((out / "source.tar.gz").read_bytes()).hexdigest()
        == manifest["source_sha256"]
    )
    ledger = out / "results.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    base = json.loads((out / "pilot.json").read_text())
    base["jobs_dir"] = str(out / "jobs")
    fast = (out / "fast-policy.json").exists()
    tasks = out / "datasets/terminal-bench-2.1/tasks"
    memory = {
        name: tomllib.loads((tasks / name / "task.toml").read_text())["environment"]["memory_mb"]
        for name in manifest["tasks"]
    }
    prior = handoff["progress"]
    active = []
    if prior["current_task"] not in {row["task"] for row in rows}:
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
                failures = (
                    failures + 1
                    if row["runtime_state"]
                    in {"infrastructure_error", "runtime_error", "idle_timeout"}
                    else 0
                )
                if row["runtime_state"] in STOP_STATES or failures >= 3:
                    reason = row["runtime_state"]
                write_json(out / "summary.json", summarize(rows, len(manifest["tasks"])))
                analyze(out)
                continue
            if fast:
                item["timeout_reason"] = item.get("timeout_reason") or fast_timeout(
                    item, status, time.time()
                )
            elif time.time() - item["started_at"] > 25200:
                reason = "supervisor_timeout"
            if reason or (out / "STOP").exists() or item.get("timeout_reason"):
                if (out / "STOP").exists():
                    reason = reason or "stop_requested"
                if not item.get("stopping_at"):
                    signal_trial(item["child_pid"], signal.SIGINT)
                    item["stopping_at"] = time.time()
                elif time.time() - item["stopping_at"] > 30:
                    signal_trial(item["child_pid"], signal.SIGKILL)
        pending = pending_tasks(manifest["tasks"], rows, active)
        if shutil.disk_usage(out).free < 10 * 1024**3:
            reason = reason or "disk_space_below_10GiB"
        while pending and not reason and fits(active, memory[pending[0]]):
            name = pending.pop(0)
            index = manifest["tasks"].index(name) + 1
            jobname = f"{index:03d}-{name}-{time.time_ns()}"
            base["job_name"] = jobname
            base["tasks"] = [{"path": str(tasks / name)}]
            config = out / "configs" / (jobname + ".json")
            write_json(config, base)
            with config.with_suffix(".console.log").open("w") as log:
                process = subprocess.Popen(
                    [str(out / "venv/bin/harbor"), "run", "--config", str(config)],
                    cwd=root,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env=dict(
                        os.environ,
                        DOCKER_DEFAULT_PLATFORM="linux/amd64",
                        PYTHONUNBUFFERED="1",
                        PYTHONPATH=str(root),
                    ),
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
            print(f"Started slot {len(active)}/2: {name}, PID {process.pid}", flush=True)
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
            "concurrency": 2,
            "memory_budget_mb": 8192,
            "active_tasks": [{k: v for k, v in item.items() if k != "process"} for item in active],
            **summarize(rows, len(manifest["tasks"])),
        }
        write_json(out / "progress.json", progress)
        if not active:
            if pending and not reason:
                raise RuntimeError("Next task cannot fit the declared memory budget")
            break
        time.sleep(5)


if __name__ == "__main__":
    main(*sys.argv[1:])
