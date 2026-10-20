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
    partial = summarize(rows, 89)
    assert partial["graded_pass_rate_percent"] == 100
    assert partial["gap_to_official_percentage_points"] is None
    assert summarize(rows, 1)["gap_to_official_percentage_points"] == pytest.approx(11.8)


def test_fast_timeout_separates_setup_idle_and_verifier():
    from evals.public_benchmarks.parallel import fast_timeout

    item = {"started_at": 0}
    assert fast_timeout(item, None, 299) is None
    assert fast_timeout(item, None, 300) == "fast_setup_timeout"
    assert fast_timeout(item, {"state": "running", "idle_seconds": 300}, 400) == "fast_idle_timeout"
    assert fast_timeout(item, {"state": "completed", "idle_seconds": 999}, 400) is None
    assert fast_timeout(item, {"state": "completed"}, 1800) == "fast_total_timeout"


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
