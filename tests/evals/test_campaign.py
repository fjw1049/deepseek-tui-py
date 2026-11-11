from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys

import pytest

from evals.campaign import CampaignSpec, execute_worker, run_campaign, schedule
from evals.runner import REPO_ROOT
from evals.snapshots import freeze_source, tree_hash


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    def git(*args):
        return subprocess.run(["git", "-c", "user.name=Eval Test", "-c",
                               "user.email=eval@example.invalid", *args],
                              cwd=root, check=True, capture_output=True).stdout
    git("init", "-q")
    for name, content in {"src/product.py": "old", "evals/runner.py": "current-evaluator",
                          "contracts/schema.json": "{}", "pyproject.toml": "", "uv.lock": "",
                          ".deepseek/config.toml": "must-not-copy"}.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    git("add", ".")
    git("commit", "-qm", "baseline")
    (root / "src/product.py").write_text("candidate")
    (root / "src/new.py").write_text("untracked-candidate")
    return root


def test_snapshots_preserve_dirty_worktree_and_share_the_current_evaluator(repository, tmp_path):
    original = (repository / "src/product.py").read_bytes()
    a, b = tmp_path / "a", tmp_path / "b"
    ma = freeze_source(repository, "HEAD", a)
    mb = freeze_source(repository, "working-tree", b)
    assert (a / "src/product.py").read_text() == "old"
    assert (b / "src/product.py").read_bytes() == original
    assert (b / "src/new.py").read_text() == "untracked-candidate"
    assert ma["evaluator_hash"] == mb["evaluator_hash"]
    assert ma["product_hash"] != mb["product_hash"]
    assert tree_hash(a) == ma["source_hash"] and tree_hash(b) == mb["source_hash"]
    assert not (a / ".deepseek").exists() and not (b / ".git").exists()
    assert (repository / "src/product.py").read_bytes() == original
    (b / "src/new.py").write_text("changed")
    assert tree_hash(b) != mb["source_hash"]


def test_snapshots_reject_symlinks_and_invalid_revisions(repository, tmp_path):
    (repository / "src/leak.py").symlink_to(repository / ".deepseek/config.toml")
    with pytest.raises(ValueError, match="symlinks"):
        freeze_source(repository, "working-tree", tmp_path / "link")
    with pytest.raises(subprocess.CalledProcessError):
        freeze_source(repository, "not-a-revision", tmp_path / "invalid")


def test_plan_is_reproducible_and_contains_every_pair():
    spec = CampaignSpec(hypothesis="test", case_ids=["a", "b"], repetitions=3)
    plan = schedule(spec)
    assert plan == schedule(spec) and len(plan) == 18
    assert {(p["arm"], p["case_id"], p["trial"]) for p in plan} == {
        (arm, case, trial) for arm in ("baseline", "repeat", "candidate")
        for case in ("a", "b") for trial in (1, 2, 3)
    }


async def test_real_offline_campaign_runs_frozen_workers_and_retains_evidence(tmp_path):
    spec = CampaignSpec(hypothesis="verify the pipeline", baseline_revision="working-tree",
                        case_ids=["tooling.reject_unknown_mcp_tool"], repetitions=2)
    output = tmp_path / "campaign"
    result = await run_campaign(spec, output)
    state = json.loads((output / "campaign.json").read_text())
    assert state["status"] == "completed", result
    assert len(state["completed"]) == 6
    assert result["decision"] == "insufficient_evidence"  # Offline passes are not agent gains.
    assert result["aa"]["comparable"] and result["comparison"]["comparable"]
    assert (output / "report.md").is_file()
    for arm in ("baseline", "repeat", "candidate"):
        rows = [json.loads(line)
                for line in (output / arm / "cases.jsonl").read_text().splitlines()]
        assert {row["trial"] for row in rows} == {1, 2}
        assert all((output / row["artifact_run"] / "scorecard.md").is_file() for row in rows)


@pytest.mark.parametrize("failure", [RuntimeError("worker crashed"), asyncio.CancelledError()])
async def test_failed_or_cancelled_campaign_never_leaves_a_success(tmp_path, monkeypatch, failure):
    import evals.campaign as campaign

    async def broken(*args):
        raise failure

    monkeypatch.setattr(campaign, "execute_worker", broken)
    spec = CampaignSpec(hypothesis="failure test", case_ids=["tooling.reject_unknown_mcp_tool"],
                        repetitions=1)
    output = tmp_path / "failed"
    result = await run_campaign(spec, output)
    state = json.loads((output / "campaign.json").read_text())
    assert state["status"] in {"error", "interrupted"}
    assert result["decision"] == "insufficient_evidence"
    assert not (output / "candidate" / "summary.json").exists()


async def test_stop_preserves_completed_trial_without_running_the_remaining_plan(
    tmp_path, monkeypatch,
):
    import evals.campaign as campaign

    output = tmp_path / "stopped"
    original = campaign.execute_worker

    async def stop_after_one(*args):
        await original(*args)
        (output / "STOP").touch()

    monkeypatch.setattr(campaign, "execute_worker", stop_after_one)
    spec = CampaignSpec(hypothesis="stop test", case_ids=["tooling.reject_unknown_mcp_tool"])
    result = await run_campaign(spec, output)
    state = json.loads((output / "campaign.json").read_text())
    assert state["status"] == "interrupted"
    assert len(state["completed"]) == 1
    assert result["decision"] == "insufficient_evidence"


async def test_worker_timeout_terminates_product_descendants(tmp_path, monkeypatch):
    import evals.campaign as campaign

    original = asyncio.create_subprocess_exec
    marker = tmp_path / "child.pid"
    script = (
        "import subprocess,sys,signal,time,pathlib\n"
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
        "signal.signal(signal.SIGTERM, lambda *args: (child.wait(), sys.exit(0)))\n"
        f"pathlib.Path({str(marker)!r}).write_text(str(child.pid))\n"
        "time.sleep(60)\n"
    )

    async def sleeping_worker(*args, **kwargs):
        return await original(sys.executable, "-c", script, **kwargs)

    monkeypatch.setattr(campaign.asyncio, "create_subprocess_exec", sleeping_worker)
    with pytest.raises(TimeoutError):
        await execute_worker(tmp_path, tmp_path / "request.json", 1)
    child = int(marker.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


async def test_cli_sigterm_records_interruption(tmp_path):
    spec = CampaignSpec(hypothesis="termination test", repetitions=3,
                        case_ids=["tooling.reject_unknown_mcp_tool"])
    request = tmp_path / "spec.json"
    request.write_text(spec.model_dump_json())
    output = tmp_path / "interrupted"
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "evals", "campaign", str(request), "--output", str(output),
        cwd=REPO_ROOT, env={**os.environ, "PYTHONPATH": f"{REPO_ROOT / 'src'}:{REPO_ROOT}"},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        for _ in range(250):
            if list((output / "requests").glob("*.json")):
                break
            await asyncio.sleep(0.02)
        assert list((output / "requests").glob("*.json"))
        process.terminate()
        await asyncio.wait_for(process.communicate(), 15)
        state = json.loads((output / "campaign.json").read_text())
        decision = json.loads((output / "decision.json").read_text())
        assert state["status"] == "interrupted"
        assert decision["decision"] == "insufficient_evidence" and process.returncode == 2
    finally:
        if process.returncode is None:
            process.kill()
        await process.wait()
