import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deepseek_tui.protocol.messages import MessageRequest
from deepseek_tui.protocol.responses import StreamDone, Usage
from evals.public_benchmarks import parallel
from evals.public_benchmarks.campaign import collect, summarize
from evals.public_benchmarks.parallel import fits, pending_tasks
from evals.public_benchmarks.worker import RecordedClient, Recorder


def test_parallel_adoption_does_not_repeat_completed_or_running_tasks():
    assert pending_tasks(
        ["done", "running", "next"], [{"task": "done"}], [{"task": "running"}]
    ) == ["next"]


def test_parallel_memory_budget_and_slots():
    assert fits([{"memory_mb": 4096}], 2048)
    assert not fits([{"memory_mb": 2048}, {"memory_mb": 2048}], 2048)
    assert not fits([{"memory_mb": 4096}], 8192)
    assert fits([], 8192)


@pytest.mark.parametrize("first_state,expected_launches", [("completed", 3), ("quota", 2)])
def test_parallel_scheduler_stops_on_quota_without_duplicate_trials(
    tmp_path, monkeypatch, first_state, expected_launches
):
    out = tmp_path
    (out / "configs").mkdir()
    (out / "source.tar.gz").write_bytes(b"frozen")
    names = ["done", "one", "two", "three"]
    manifest = {"tasks": names, "source_sha256": hashlib.sha256(b"frozen").hexdigest()}
    (out / "manifest.json").write_text(json.dumps(manifest))
    (out / "pilot.json").write_text("{}")
    (out / "results.jsonl").write_text(
        json.dumps(
            {"task": "done", "job": str(out / "old"), "reward": 1, "runtime_state": "completed"}
        )
        + "\n"
    )
    for name in names:
        task = out / "datasets/terminal-bench-2.1/tasks" / name
        task.mkdir(parents=True)
        (task / "task.toml").write_text("[environment]\nmemory_mb=2048\n")
    launched, snapshots = [], []

    def fake_process(command, **kwargs):
        config = json.loads(Path(command[-1]).read_text())
        task = Path(config["tasks"][0]["path"]).name
        launched.append(task)
        trial = out / "jobs" / config["job_name"] / "trial"
        (trial / "agent").mkdir(parents=True)
        state = first_state if task == "one" else "completed"
        (trial / "agent/status.json").write_text(json.dumps({"state": state, "requests": 1}))
        (trial / "result.json").write_text(
            json.dumps(
                {"verifier_result": {"rewards": {"reward": 1 if state == "completed" else 0}}}
            )
        )
        return SimpleNamespace(pid=100 + len(launched), returncode=0, poll=lambda: 0)

    monkeypatch.setattr(parallel.subprocess, "Popen", fake_process)
    monkeypatch.setattr(
        parallel.time,
        "sleep",
        lambda _: snapshots.append(json.loads((out / "progress.json").read_text())),
    )
    parallel.run(out, out, {"progress": {"current_task": "done"}})
    assert len(launched) == expected_launches
    assert len(set(launched)) == len(launched)
    assert max(len(s["active_tasks"]) for s in snapshots) == 2
    result = json.loads((out / "progress.json").read_text())
    assert result["state"] == ("completed" if first_state == "completed" else "blocked")


def test_partial_score_is_not_official_gap():
    rows = [{"reward": 1, "runtime_state": "completed", "requests": 2}]
    partial = summarize(rows, 89, 88.2)
    assert partial["graded_pass_rate_percent"] == 100
    assert partial["gap_to_official_percentage_points"] is None
    assert summarize(rows, 1, 88.2)["gap_to_official_percentage_points"] == pytest.approx(11.8)
    # A campaign without a published reference never reports a gap.
    assert summarize(rows, 1)["gap_to_official_percentage_points"] is None


def test_settings_keep_the_first_campaign_and_read_new_manifests():
    from evals.public_benchmarks.campaign import campaign_settings

    legacy = campaign_settings({"tasks": []})
    assert (legacy["provider"], legacy["model"], legacy["reference_percent"]) == (
        "endpoint", "glm-5-3", 88.2)
    assert (legacy["concurrency"], legacy["memory_budget_mb"]) == (2, 8192)
    custom = campaign_settings({
        "model": "openrouter/vendor/model", "official_reference": None,
        "parallel": {"concurrency": 4, "memory_budget_mb": 16384}, "docker_platform": "",
    })
    assert (custom["provider"], custom["model"]) == ("openrouter", "vendor/model")
    assert custom["reference_percent"] is None
    assert (custom["concurrency"], custom["memory_budget_mb"]) == (4, 16384)


def test_new_campaign_requires_a_model_and_trials_receive_the_manifest(tmp_path, monkeypatch):
    import argparse

    from evals.public_benchmarks.campaign import (
        MANIFEST_ENV,
        add_campaign_arguments,
        load_manifest,
        trial_env,
    )

    parser = argparse.ArgumentParser()
    add_campaign_arguments(parser)
    with pytest.raises(SystemExit, match="--model"):
        load_manifest(tmp_path, tmp_path, parser.parse_args([]))
    monkeypatch.delenv("DOCKER_DEFAULT_PLATFORM", raising=False)
    env = trial_env(tmp_path, {"docker_platform": ""})
    assert env[MANIFEST_ENV] == str(tmp_path / "manifest.json")
    assert "DOCKER_DEFAULT_PLATFORM" not in env
    assert trial_env(tmp_path, {"docker_platform": "linux/amd64"})[
        "DOCKER_DEFAULT_PLATFORM"] == "linux/amd64"


def test_report_without_reference_makes_no_comparison(tmp_path):
    from evals.public_benchmarks.analyze import analyze

    (tmp_path / "manifest.json").write_text(json.dumps({
        "tasks": ["a"], "model": "endpoint/other", "official_reference": None,
        "gateway": "测试网关",
    }))
    metrics = analyze(tmp_path)
    text = (tmp_path / "analysis.md").read_text()
    assert metrics["official_reference_percent"] is None
    assert "endpoint/other" in text and "未设定参考分" in text
    assert "88.2" not in text and "众安" not in text


def test_fast_timeout_separates_setup_idle_and_verifier():
    from evals.public_benchmarks.parallel import fast_timeout

    item = {"started_at": 0}
    assert fast_timeout(item, None, 299) is None
    assert fast_timeout(item, None, 300) == "fast_setup_timeout"
    assert fast_timeout(item, {"state": "running", "idle_seconds": 300}, 400) == "fast_idle_timeout"
    assert fast_timeout(item, {"state": "completed", "idle_seconds": 999}, 400) is None
    assert fast_timeout(item, {"state": "completed"}, 1800) == "fast_total_timeout"


def test_fast_policy_spares_trials_started_before_it(tmp_path):
    import os

    from evals.public_benchmarks.parallel import fast_timeout, load_fast_policy

    assert load_fast_policy(tmp_path) is None
    (tmp_path / "fast-policy.json").write_text(json.dumps({"total_seconds": 600}))
    os.utime(tmp_path / "fast-policy.json", (5000, 5000))
    policy = load_fast_policy(tmp_path)
    assert policy == {"setup_seconds": 300, "idle_seconds": 300, "total_seconds": 600,
                      "created_at": 5000}
    # An adopted trial keeps the budget it was started under.
    assert fast_timeout({"started_at": 1000}, {"state": "running"}, 9000, policy) is None
    assert fast_timeout({"started_at": 6000}, {"state": "running"}, 6600, policy) == (
        "fast_total_timeout")


def test_a_trial_past_its_deadline_is_stopped_alone_and_counts_toward_the_guard(
    tmp_path, monkeypatch
):
    out = tmp_path
    (out / "source.tar.gz").write_bytes(b"frozen")
    names = ["one", "two", "three", "four"]
    (out / "manifest.json").write_text(json.dumps({
        "tasks": names, "source_sha256": hashlib.sha256(b"frozen").hexdigest(),
        "supervisor_timeout_seconds": -1, "parallel": {"concurrency": 1},
    }))
    (out / "pilot.json").write_text("{}")
    for name in names:
        task = out / "datasets/terminal-bench-2.1/tasks" / name
        task.mkdir(parents=True)
        (task / "task.toml").write_text("[environment]\nmemory_mb=2048\n")
    launched, processes, signals = [], {}, []

    def fake_process(command, **kwargs):
        config = json.loads(Path(command[-1]).read_text())
        launched.append(Path(config["tasks"][0]["path"]).name)
        trial = out / "jobs" / config["job_name"] / "trial"
        (trial / "agent").mkdir(parents=True)
        (trial / "agent/status.json").write_text(json.dumps({"state": "running"}))
        process = SimpleNamespace(pid=100 + len(launched), returncode=None, stopped=False)
        process.poll = lambda: 0 if process.stopped else None
        processes[process.pid] = process
        return process

    def stop(pid, sig):
        signals.append(sig)
        processes[pid].stopped = True

    monkeypatch.setattr(parallel.subprocess, "Popen", fake_process)
    monkeypatch.setattr(parallel, "signal_trial", stop)
    monkeypatch.setattr(parallel.time, "sleep", lambda _: None)
    parallel.run(out, out)
    # Each overdue trial is stopped on its own; three in a row trip the guard.
    assert launched == ["one", "two", "three"]
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
    assert [row["supervisor_timeout_reason"] for row in rows] == ["supervisor_timeout"] * 3
    result = json.loads((out / "progress.json").read_text())
    assert (result["state"], result["reason"]) == ("blocked", "consecutive_failures")


def test_collect_preserves_verifier_failure_and_runtime_success(tmp_path):
    trial = tmp_path / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "result.json").write_text(json.dumps({"verifier_result": {"rewards": {"reward": 0}}}))
    (trial / "agent/status.json").write_text(json.dumps({"state": "completed", "requests": 3}))
    result = collect(tmp_path, "task", 0)
    assert result["reward"] == 0
    assert result["runtime_state"] == "completed"


@pytest.mark.asyncio
async def test_quota_stops_retry_and_secrets_are_redacted(tmp_path):
    class QuotaClient:
        async def stream_chat_completion(self, request):
            raise RuntimeError("insufficient_quota secret-token")
            yield

    log = Recorder(tmp_path, ["secret-token"])
    client = RecordedClient(QuotaClient(), log, 10)
    request = MessageRequest(model="test", messages=[])
    with pytest.raises(RuntimeError):
        async for _ in client.stream_chat_completion(request):
            pass
    assert client.fatal == "quota"
    with pytest.raises(RuntimeError, match="quota"):
        async for _ in client.stream_chat_completion(request):
            pass
    assert client.requests == 1
    log.file.close()
    assert "secret-token" not in (tmp_path / "trace.jsonl").read_text()


@pytest.mark.asyncio
async def test_usage_and_request_limit(tmp_path):
    class Client:
        async def stream_chat_completion(self, request):
            yield StreamDone(usage=Usage(input_tokens=12, output_tokens=3))

    log = Recorder(tmp_path)
    client = RecordedClient(Client(), log, 1)
    request = MessageRequest(model="test", messages=[])
    async for _ in client.stream_chat_completion(request):
        pass
    assert client.usage["input_tokens"] == 12
    assert client.metered == 1
    with pytest.raises(RuntimeError, match="request_limit"):
        async for _ in client.stream_chat_completion(request):
            pass
    log.file.close()
