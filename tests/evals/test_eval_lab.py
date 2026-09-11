from __future__ import annotations

import asyncio
import json
import sys

import httpx
import pytest

from deepseek_tui.client.base import LLMClient
from deepseek_tui.config.models import Config
from deepseek_tui.protocol.responses import (
    StreamDone,
    StreamTextDelta,
    StreamToolCallComplete,
    ToolCall,
    Usage,
)
from evals.compare import compare_metrics
from evals.experiments import compare_runs
from evals.graders.authority import grade_authority
from evals.graders.completion import grade_completion
from evals.graders.constraints import grade_constraints
from evals.graders.tooling import grade_tooling
from evals.harness import HarnessContext
from evals.harness.budget import BudgetedClient, BudgetExceeded
from evals.harness.workspace import FixtureContext, run_workspace_task, verify_files
from evals.runner import RunOptions, load_cases, run_evaluations
from evals.schema import EvalCase, EvalObservation
from evals.server import Experiments, StartRequest, create_app


def simple_case(grader, **kwargs):
    return EvalCase(
        id="test.case", suite="test", runner="live_decision", grader=grader, live=True, **kwargs
    )


def test_completion_contradiction_cannot_hide_positive_claim():
    c = simple_case("completion", input={"evidence": {"tests_passed": False}})
    result = grade_completion(
        c, EvalObservation(data={"assistant_text": "虽然编辑失败，但任务已经完成，测试全部通过。"})
    )
    assert not result.passed
    assert result.metrics["completion.false_complete_rate"] == 1


@pytest.mark.parametrize(
    "grader", [grade_authority, grade_tooling, grade_completion, grade_constraints]
)
def test_missing_evidence_is_not_a_pass(grader):
    with pytest.raises(ValueError):
        grader(simple_case("tooling"), EvalObservation())


def test_reversed_constraint_decision_fails():
    c = next(
        c for c in load_cases() if c.id == "constraints.live_archived_context_retains_restrictions"
    )
    result = grade_constraints(
        c,
        EvalObservation(
            data={
                "assistant_text": json.dumps(
                    {
                        "forbidden_paths": [],
                        "required_tests": [],
                        "tests_verified": True,
                    }
                )
            }
        ),
    )
    assert not result.passed
    assert "constraints.survival_rate" not in result.metrics
    good = grade_constraints(
        c, EvalObservation(data={"assistant_text": json.dumps(c.expect["response_json"])})
    )
    assert good.passed


def test_compare_rejects_skipped_even_if_mean_is_one():
    assert compare_metrics(
        {"gates": {"run.pass_rate": {"min": 1}}},
        {"skipped": 1, "metrics": {"run.pass_rate": {"mean": 1}}},
    )


class FailingClient(LLMClient):
    calls = 0

    async def stream_chat_completion(self, request):
        self.calls += 1
        raise TimeoutError("simulated provider failure")
        yield  # pragma: no cover


async def test_budget_debits_failed_provider_attempts():
    from deepseek_tui.protocol.messages import MessageRequest

    inner = FailingClient()
    ctx = HarnessContext(workspace=".", remaining_live_requests=1)
    client = BudgetedClient(inner, ctx)
    request = MessageRequest(model="test", messages=[])
    with pytest.raises(TimeoutError):
        _ = [e async for e in client.stream_chat_completion(request)]
    with pytest.raises(BudgetExceeded):
        _ = [e async for e in client.stream_chat_completion(request)]
    assert inner.calls == ctx.requests == 1
    assert ctx.metered_requests == 0


class FileTaskClient(LLMClient):
    def __init__(self):
        super().__init__()
        self.calls = 0
        self.prompts = []

    async def stream_chat_completion(self, request):
        self.calls += 1
        self.prompts.append(request.system_prompt)
        if self.calls == 1:
            yield StreamToolCallComplete(
                tool_call=ToolCall(id="read", name="read_file", arguments={"path": "app.json"})
            )
        elif self.calls == 2:
            yield StreamToolCallComplete(
                tool_call=ToolCall(
                    id="edit",
                    name="edit_file",
                    arguments={
                        "path": "app.json",
                        "old_string": '"timeout": 10',
                        "new_string": '"timeout": 30',
                    },
                )
            )
        else:
            yield StreamTextDelta(text="已修改 timeout，保留其他字段。")
        yield StreamDone(usage=Usage(input_tokens=100, output_tokens=20))


async def test_real_engine_executes_file_tools_and_verifies_outcome(monkeypatch):
    import evals.harness.workspace as ws

    client = FileTaskClient()
    monkeypatch.setattr(ws.ConfigLoader, "load", lambda *a, **k: Config())
    monkeypatch.setattr(ws, "build_llm_client", lambda cfg: client)
    case = next(c for c in load_cases() if c.id == "workspace.update_setting")
    ctx = HarnessContext(workspace=".", remaining_live_requests=10, prompt_suffix="TEST_VARIANT")
    observation = await run_workspace_task(case, ctx)
    assert all(check["passed"] for check in observation.data["checks"]), observation.data
    assert json.loads(observation.data["files"]["app.json"])["timeout"] == 30
    assert "app.json" in observation.data["diffs"]
    assert ctx.requests == 3
    assert all("TEST_VARIANT" in p for p in client.prompts)
    assert any(e["type"] == "ToolResultEvent" for e in ctx.trace)


def test_workspace_verifier_catches_partial_and_protected_changes(tmp_path):
    case = next(c for c in load_cases() if c.id == "workspace.protected_config")
    files = dict(case.setup["files"])
    files["result.json"] = '{"total":150,"tax":15}'
    assert all(c["passed"] for c in verify_files(case, files))
    files["settings.json"] = "{}"
    assert not all(c["passed"] for c in verify_files(case, files))
    ctx = FixtureContext(working_directory=tmp_path)
    with pytest.raises(ValueError):
        ctx.resolve_path("../outside")


async def test_cancellation_records_current_and_remaining_trials(tmp_path, monkeypatch):
    import evals.runner as runner

    started = asyncio.Event()

    async def block(*args):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(runner, "run_harness", block)
    case = simple_case("tooling")
    task = asyncio.create_task(
        run_evaluations(
            RunOptions(mode="live", trials=3, output_dir=tmp_path / "cancelled"), cases=[case]
        )
    )
    await started.wait()
    task.cancel()
    output, summary = await task
    assert summary.total == summary.skipped == 3
    assert summary.metrics["run.pass_rate"]["mean"] == 0
    assert len((output / "cases.jsonl").read_text().splitlines()) == 3


@pytest.fixture
async def lab(tmp_path):
    app = create_app(tmp_path / "artifacts")
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:7879"
        ) as client:
            yield client


async def test_independent_surface_and_request_boundaries(lab):
    page = await lab.get("/")
    assert page.status_code == 200 and "Eval Lab" in page.text
    assert (await lab.get("/api/bootstrap")).json()["cases"]
    assert (await lab.get("/api/threads")).status_code == 404
    assert (await lab.post("/api/runs", json={})).status_code == 403
    assert (
        await lab.post(
            "/api/runs", json={}, headers={"x-eval-request": "1", "origin": "https://evil.example"}
        )
    ).status_code == 403
    assert (await lab.get("/api/runs/bad%3Aid")).status_code == 400


async def test_start_actual_offline_worker_history_export_and_comparison(lab):
    cases = [c.id for c in load_cases() if not c.live]
    ids = []
    for label in ("基线", "候选"):
        response = await lab.post(
            "/api/runs", json={"label": label, "case_ids": cases}, headers={"x-eval-request": "1"}
        )
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        ids.append(run_id)
        for _ in range(100):
            detail = (await lab.get(f"/api/runs/{run_id}")).json()
            if detail["status"] not in {"running", "stopping"}:
                break
            await asyncio.sleep(0.05)
        assert detail["status"] == "completed", detail
        assert detail["summary"]["passed"] == len(cases)
    exported = await lab.get(f"/api/runs/{ids[0]}/export")
    assert len(exported.json()["cases"]) == len(cases)
    comparison = (await lab.get(f"/api/compare?a={ids[0]}&b={ids[1]}")).json()
    assert comparison["comparable"]
    assert comparison["delta"] == 0
    assert len((await lab.get("/api/runs")).json()) == 2


async def test_bad_selection_and_irrelevant_prompt_are_rejected(lab):
    headers = {"x-eval-request": "1"}
    for payload in (
        {"case_ids": ["missing"]},
        {"case_ids": ["workspace.update_setting"]},
        {"case_ids": ["tooling.reject_unknown_mcp_tool"], "prompt_suffix": "ignored"},
    ):
        assert (await lab.post("/api/runs", json=payload, headers=headers)).status_code == 400


def test_comparison_refuses_mismatched_grader_or_incomplete_run():
    run = {
        "manifest": {
            "dataset_hash": "a",
            "grader_hash": "g",
            "mode": "offline",
            "trials": 1,
            "settings": {"expected_trials": 1},
        },
        "status": "completed",
        "cases": [{"case_id": "x", "trial": 1, "status": "passed"}],
    }
    other = json.loads(json.dumps(run))
    other["manifest"]["grader_hash"] = "changed"
    assert not compare_runs(run, other)["comparable"]
    other = json.loads(json.dumps(run))
    other["cases"][0]["status"] = "skipped"
    assert not compare_runs(run, other)["comparable"]


async def test_stop_terminates_worker_and_keeps_cancelled_state(tmp_path, monkeypatch):
    import evals.server as server

    original = asyncio.create_subprocess_exec

    async def idle_worker(*args, **kwargs):
        return await original(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)

    monkeypatch.setattr(server.asyncio, "create_subprocess_exec", idle_worker)
    service = Experiments(tmp_path / "runs")
    run_id = await service.start(StartRequest(case_ids=["tooling.reject_unknown_mcp_tool"]))
    process = service.active[run_id]
    try:
        await service.stop(run_id)
        if service.monitors:
            await asyncio.gather(*list(service.monitors))
        assert process.returncode is not None
        assert service.detail(run_id)["status"] == "cancelled"
        assert not service.active
    finally:
        await service.close()


async def test_live_failure_persists_trace_and_debits_request_budget(tmp_path, monkeypatch):
    import evals.harness.live as live

    client = FailingClient()
    monkeypatch.setattr(live.ConfigLoader, "load", lambda *a, **k: Config())
    monkeypatch.setattr(live, "build_llm_client", lambda cfg: client)
    case = simple_case("authority", input={"messages": [{"role": "user", "content": "hello"}]})
    output, summary = await run_evaluations(
        RunOptions(mode="live", trials=2, max_live_requests=1, output_dir=tmp_path / "failed"),
        cases=[case],
    )
    rows = [json.loads(line) for line in (output / "cases.jsonl").read_text().splitlines()]
    assert summary.errors == 1 and summary.skipped == 1
    assert rows[0]["observation"]["usage"]["requests"] == 1
    assert "cost_usd" not in rows[0]["observation"]["usage"]
    trace = output / rows[0]["observation"]["data"]["trace_file"]
    assert json.loads(trace.read_text())[0]["type"] == "model_request"
